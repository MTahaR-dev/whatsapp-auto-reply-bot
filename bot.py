
import json
import os
import re
import socket
import sys
import time
import random
from datetime import datetime, timedelta

# Windows writes redirected output as cp1252, which can't encode emoji in chat names.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import (
    TimeoutException,
    NoSuchElementException,
    StaleElementReferenceException,
)

import brain
import memory

# ---------------------------------------------------------------- CONFIG

SEND_ENABLED = True             # master switch. False = draft only, sends nothing
MAX_PER_CYCLE = 5
POLL_SECONDS = 30

USE_UNREAD_FILTER = False       # False = scan all chats, decide by age instead
HEADLESS = False                # only enable after the QR is already scanned

IGNORE_BACKLOG_ON_START = False
MAX_MESSAGE_AGE_MINUTES = 30    # with the backlog guard off, this is the main gate

# mention = only reply in groups when tagged | skip | learn | draft
GROUP_POLICY = "mention"

HERE = os.path.dirname(os.path.abspath(__file__))
PROFILE_DIR = os.path.join(HERE, "chrome_profile")
CONTACTS_FILE = os.path.join(HERE, "contacts.json")

# How people tag you. Lives in contacts.json (gitignored) so your phone number
# never ends up in the repo. See contacts.example.json.
MY_ALIASES = ["@me"]


# ---------------------------------------------------------------- POLICY

def load_policies():
    if not os.path.exists(CONTACTS_FILE):
        raise SystemExit(
            "contacts.json not found.\n"
            "Copy contacts.example.json to contacts.json and fill in your details."
        )
    with open(CONTACTS_FILE, encoding="utf-8") as f:
        raw = json.load(f)

    # Identity lives in the config so no personal data sits in tracked code.
    global MY_ALIASES
    aliases = raw.get("_aliases")
    if aliases:
        MY_ALIASES = aliases

    return {k: v for k, v in raw.items() if not k.startswith("_")}, raw.get("_default", "draft")


def policy_for(name, rules, default):
    if name in rules:
        return rules[name]
    for key, value in rules.items():
        if key.lower() == name.lower():
            return value
    return default


# ---------------------------------------------------------------- BROWSER

def clear_stale_locks():
    removed = []
    for name in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
        path = os.path.join(PROFILE_DIR, name)
        if os.path.exists(path):
            try:
                os.remove(path)
                removed.append(name)
            except OSError:
                pass
    return removed


_instance_lock = None


def claim_single_instance(port=47281):
    """Two bots can't share one Chrome profile. A bound socket frees itself on crash."""
    global _instance_lock
    _instance_lock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        _instance_lock.bind(("127.0.0.1", port))
        _instance_lock.listen(1)
    except OSError:
        raise SystemExit(
            "\nAnother copy of the bot is already running.\n"
            "Run stop_bot.bat, wait a few seconds, then start again.\n"
        )


def chrome_options(headless):
    opts = Options()
    opts.add_argument(f"--user-data-dir={PROFILE_DIR}")
    opts.add_argument("--profile-directory=Default")
    opts.add_argument("--no-first-run")
    opts.add_argument("--no-default-browser-check")
    opts.add_argument("--disable-session-crashed-bubble")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])

    if headless:
        opts.add_argument("--headless=new")
        opts.add_argument("--window-size=1920,1080")   # narrow viewport hides the chat list
        # These three prevent "DevToolsActivePort file doesn't exist".
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument("--disable-gpu")
    else:
        opts.add_argument("--start-maximized")
    return opts


def build_driver():
    attempts = [(HEADLESS, "headless" if HEADLESS else "windowed")]
    if HEADLESS:
        attempts.append((False, "windowed (headless failed)"))

    last_error = None
    for headless, label in attempts:
        for retry in range(2):
            try:
                driver = webdriver.Chrome(options=chrome_options(headless))
                if "failed" in label:
                    print(f"  !! headless wouldn't start -- running {label}")
                driver.get("https://web.whatsapp.com")
                return driver
            except Exception as e:
                last_error = e
                if retry == 0:
                    removed = clear_stale_locks()
                    if removed:
                        print(f"  cleared stale lock(s): {', '.join(removed)} -- retrying")
                    time.sleep(3)

    raise SystemExit(
        "\nChrome wouldn't start.\n"
        "  1. Close any Chrome using the bot's profile, then:\n"
        "     taskkill /F /IM chromedriver.exe\n"
        f"  2. Or delete the profile: Remove-Item -Recurse -Force \"{PROFILE_DIR}\"\n\n"
        f"Original error: {last_error}"
    )


def wait_until_loaded(driver, timeout=180):
    print("Waiting for WhatsApp Web (scan the QR if it appears)...")
    WebDriverWait(driver, timeout).until(
        EC.presence_of_element_located((By.ID, "pane-side"))
    )
    print("Connected.\n")


# ---------------------------------------------------------------- SELECTORS
# WhatsApp obfuscates its class names and changes them often, so every lookup
# tries a list of candidates. When one breaks: F12, inspect, add a new one on top.

def first_match(scope, selectors):
    for sel in selectors:
        try:
            found = scope.find_elements(By.CSS_SELECTOR, sel)
            if found:
                return found[0]
        except NoSuchElementException:
            continue
    return None


def get_pane(driver):
    for by, sel in [
        (By.ID, "pane-side"),
        (By.CSS_SELECTOR, '[aria-label*="Chat list"]'),
        (By.CSS_SELECTOR, '[data-testid="chat-list"]'),
        (By.CSS_SELECTOR, '[role="grid"]'),
    ]:
        found = driver.find_elements(by, sel)
        if found:
            return found[0]
    return None


def all_chat_rows(scope):
    # list-item-N excludes the "end-to-end encrypted" notice that role=row would return
    for sel in ('[data-testid^="list-item"]', '[role="listitem"]', '[role="row"]'):
        found = scope.find_elements(By.CSS_SELECTOR, sel)
        if found:
            return found
    return []


def select_filter_tab(driver, wanted):
    """Click a chat-list tab. Returns True only if confirmed selected."""
    for el in driver.find_elements(By.CSS_SELECTOR,
                                   '[role="tab"], [role="tablist"] button, button'):
        try:
            text = (el.text or "").strip().lower()
            label = (el.get_attribute("aria-label") or "").strip().lower()
        except Exception:
            continue
        if text.startswith(wanted.lower()) or label.startswith(wanted.lower()):
            try:
                if el.get_attribute("aria-selected") != "true":
                    el.click()
                    time.sleep(1.2)
                return el.get_attribute("aria-selected") == "true"
            except Exception:
                return False
    return False


def find_unread_rows(driver):
    pane = get_pane(driver)
    if pane is None:
        print("  !! couldn't find the chat list -- run debug_selectors.py")
        return []

    if not USE_UNREAD_FILTER:
        select_filter_tab(driver, "All")
        return all_chat_rows(pane)

    if select_filter_tab(driver, "Unread"):
        return all_chat_rows(pane)

    # Fallback: hunt for the unread badge ourselves.
    badges = []
    for sel in ('[aria-label*="unread"]', '[aria-label*="Unread"]',
                '[data-icon*="unread"]', 'span[class*="unread"]'):
        badges = pane.find_elements(By.CSS_SELECTOR, sel)
        if badges:
            break

    rows, seen = [], set()
    for badge in badges:
        for xpath in ('./ancestor::div[@role="listitem"][1]',
                      './ancestor::div[@role="row"][1]'):
            try:
                row = badge.find_element(By.XPATH, xpath)
                if row.id not in seen:
                    seen.add(row.id)
                    rows.append(row)
                break
            except NoSuchElementException:
                continue
    return rows


# Row lines that are never the chat's name.
NOISE = re.compile(
    r"^(?:\d+\s*(?:unread|new)\b.*|unread\b.*"
    r"|\d{1,2}:\d{2}(?:\s*[apAP][mM])?"
    r"|\d{1,2}/\d{1,2}/\d{2,4}"
    r"|yesterday|today|typing\.{0,3}|online|\d{1,4})$",
    re.IGNORECASE,
)


def row_age_minutes(row):
    """Age of a chat's last message, read from the LIST so we don't have to open it."""
    try:
        text = row.text or ""
    except Exception:
        return None

    for line in text.split("\n"):
        line = line.strip()
        if line.lower() == "yesterday" or re.match(r"^\d{1,2}/\d{1,2}/\d{2,4}$", line):
            return 24 * 60

        match = re.match(r"^(\d{1,2}):(\d{2})\s*([apAP][mM])?$", line)
        if match:
            hour, minute, meridiem = int(match.group(1)), int(match.group(2)), match.group(3)
            if meridiem:
                meridiem = meridiem.lower()
                if meridiem == "pm" and hour != 12:
                    hour += 12
                elif meridiem == "am" and hour == 12:
                    hour = 0
            now = datetime.now()
            sent = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            age = (now - sent).total_seconds() / 60.0
            return age if age >= 0 else age + 24 * 60      # clock rolled past midnight
    return None


def row_chat_name(row):
    """span[title] holds the real name. row.text line 0 can be '1 unread message'."""
    try:
        for el in row.find_elements(By.CSS_SELECTOR, "span[title]"):
            title = (el.get_attribute("title") or "").strip()
            if title and not NOISE.match(title):
                return title
    except Exception:
        pass
    try:
        for line in (row.text or "").split("\n"):
            line = line.strip()
            if line and not NOISE.match(line):
                return line
    except Exception:
        pass
    return ""


def row_has_mention_badge(row):
    """WhatsApp's own '@' badge. Must be read BEFORE clicking -- opening clears it."""
    try:
        return bool(row.find_elements(
            By.CSS_SELECTOR,
            '[data-icon="mention"], [data-icon="status-mention"], '
            '[aria-label*="mention"], [aria-label*="Mention"]',
        ))
    except Exception:
        return False


def bubble_mentions_me(bubble):
    try:
        for el in bubble.find_elements(
            By.CSS_SELECTOR, 'a[href^="tel:"], span.mention, ._ao3e a, a[role="button"]'
        ):
            text = (el.text or "").strip()
            if text.startswith("@") and any(
                a.lower().lstrip("@") in text.lower() for a in MY_ALIASES
            ):
                return True
    except Exception:
        pass
    body = (bubble.text or "").lower()
    return any(alias.lower() in body for alias in MY_ALIASES)


def last_incoming_mentioning_me(driver, contact_name=""):
    incoming = [b for who, b in message_bubbles(driver, contact_name)
                if who == "them"][-25:]
    for bubble in reversed(incoming):
        if bubble_mentions_me(bubble):
            text = bubble_text(bubble, driver)
            if text:
                return text
    return None


# Header subtitle text that isn't the contact's name.
HEADER_NOISE = re.compile(
    r"^(?:click here for|tap here for|last seen|online|typing|"
    r"\d+ members?|you,|group|contact info)",
    re.IGNORECASE,
)


def get_chat_title(driver):
    """The header holds both the name and a subtitle; skip the subtitle."""
    header = first_match(driver, ["#main header", "header"])
    if header is None:
        return ""
    for sel in ("span[title]", 'span[dir="auto"]'):
        for el in header.find_elements(By.CSS_SELECTOR, sel):
            try:
                text = (el.get_attribute("title") or el.text or "").strip()
            except Exception:
                continue
            if text and not HEADER_NOISE.match(text) and not NOISE.match(text):
                return text
    return ""


def is_group_chat(driver, contact_name=""):
    """
    Detect a group. Counting distinct senders alone is NOT enough -- one person
    talking in a group looks exactly like a DM, and the mention gate is skipped.
    """
    header = first_match(driver, ["#main header", "header"])

    if header is not None:
        # "click here for group info" vs "click here for contact info"
        try:
            blob = " ".join(filter(None, [
                header.text or "",
                header.get_attribute("aria-label") or "",
                header.get_attribute("innerHTML") or "",
            ])).lower()
            if "group info" in blob or "group-info" in blob:
                return True
        except Exception:
            pass

        try:
            for el in header.find_elements(By.CSS_SELECTOR, 'span[title], span[dir="auto"]'):
                sub = (el.get_attribute("title") or el.text or "").strip()
                if sub.count(",") >= 1 and (
                    sub.lower().endswith("you") or " you" in sub.lower()
                ):
                    return True
                if re.match(r"^\d+\s+members?$", sub, re.IGNORECASE):
                    return True
        except Exception:
            pass

    if first_match(driver, [
        'header [data-icon="default-group"]',
        'header [data-icon="group"]',
        '#main header img[src*="group"]',
    ]):
        return True

    # Last resort: more than one person has sent a message here.
    senders = set()
    for who, bubble in message_bubbles(driver, contact_name)[-20:]:
        if who == "them":
            sender = preplain_sender(bubble)
            if sender:
                senders.add(sender)
    if len(senders) > 1:
        return True

    # In a group every incoming bubble is tagged with its sender's name; in a
    # DM none are. So a sender name that isn't the chat title means group.
    if contact_name and senders and contact_name not in senders:
        return True

    return False


# Delivery ticks appear only on messages you sent.
OUTGOING_ICON = re.compile(r"^(?:msg|status)-(?:check|dblcheck|time|clock)", re.I)
PREPLAIN = re.compile(r"^\s*\[[^\]]*\]\s*(.*?):\s*$")


def preplain_sender(row):
    tags = row.find_elements(By.CSS_SELECTOR, "[data-pre-plain-text]")
    if not tags:
        return ""
    match = PREPLAIN.match(tags[0].get_attribute("data-pre-plain-text") or "")
    return match.group(1).strip() if match else ""


def bubble_direction(row, contact_name=""):
    """Ticks mean it's mine. Otherwise compare the sender to the chat name."""
    try:
        for icon in row.find_elements(By.CSS_SELECTOR, "[data-icon]"):
            if OUTGOING_ICON.match(icon.get_attribute("data-icon") or ""):
                return "you"
    except Exception:
        pass

    sender = preplain_sender(row)
    if sender and contact_name and sender == contact_name:
        return "them"
    if sender and any(a.lower().lstrip("@") == sender.lower() for a in MY_ALIASES):
        return "you"
    return "them"          # unknown defaults to incoming: safer than ignoring real messages


def message_bubbles(driver, contact_name=""):
    """Must be scoped to #main -- the chat list uses role=row too."""
    main = first_match(driver, ["#main"])
    if main is None:
        return []
    rows = main.find_elements(By.CSS_SELECTOR, '[role="row"]')
    if not rows:
        rows = main.find_elements(By.CSS_SELECTOR, "div[data-id]")
    return [(bubble_direction(row, contact_name), row) for row in rows]


# Bubble text that's really a timestamp or a voice-note duration.
NOT_A_MESSAGE = re.compile(r"^(?:\d{1,2}:\d{2}(?:\s*[apAP]\.?[mM]\.?)?\s*)+$")


# Walks an element and rebuilds its text, swapping each emoji <img> for its alt.
# WhatsApp renders emoji as images, so .text silently drops them -- an emoji-only
# message reads as empty, and "Pagal hai? 😭" loses the 😭.
# aria-hidden elements are skipped: that's where the timestamp lives.
EMOJI_TEXT_JS = """
const walk = (n, out) => {
  if (n.nodeType === 3) { out.push(n.nodeValue); return; }
  if (n.nodeType !== 1) return;
  if (n.getAttribute && n.getAttribute('aria-hidden') === 'true') return;
  if (n.nodeName === 'IMG') { out.push(n.getAttribute('alt') || ''); return; }
  n.childNodes.forEach(c => walk(c, out));
};
const out = [];
walk(arguments[0], out);
return out.join('');
"""


def element_text(driver, el):
    try:
        raw = driver.execute_script(EMOJI_TEXT_JS, el) or ""
    except Exception:
        try:
            raw = el.text or ""
        except Exception:
            return ""
    # Drop the whitespace that markup indentation leaves between nodes.
    return "\n".join(l.strip() for l in raw.split("\n") if l.strip()).strip()


def bubble_text(bubble, driver=None):
    """No text element means no message -- don't fall back to the bubble's raw text."""
    for sel in ("span.selectable-text span", "span.selectable-text",
                '[class*="selectable-text"]'):
        try:
            for el in bubble.find_elements(By.CSS_SELECTOR, sel):
                text = element_text(driver, el) if driver else (el.text or "").strip()
                if text and not NOT_A_MESSAGE.match(text):
                    return text
        except Exception:
            continue

    # Emoji-only messages render as large standalone images with no
    # selectable-text wrapper, so read the copyable-text container directly.
    if driver is not None:
        for sel in ("[data-pre-plain-text]", '[class*="copyable-text"]'):
            try:
                for el in bubble.find_elements(By.CSS_SELECTOR, sel):
                    text = element_text(driver, el)
                    if text and not NOT_A_MESSAGE.match(text):
                        return text
            except Exception:
                continue
    return ""


def bubble_is_media(bubble):
    try:
        return bool(bubble.find_elements(
            By.CSS_SELECTOR,
            'img[src^="blob:"], video, audio, canvas, '
            '[data-icon="media-play"], [data-icon="audio-play"], '
            '[data-icon="media-download"], [data-icon="sticker"], '
            '[data-icon="document"], [aria-label*="sticker"], [aria-label*="GIF"]',
        ))
    except Exception:
        return False


def get_recent_messages(driver, count=6, contact_name=""):
    out = []
    for who, bubble in message_bubbles(driver, contact_name)[-count * 2:]:
        text = bubble_text(bubble, driver)
        if text:
            out.append((who, text))
    return out[-count:]


def bubble_time(bubble):
    """From data-pre-plain-text: "[7:14 PM, 8/6/2026] Ali Raza: "."""
    tags = bubble.find_elements(By.CSS_SELECTOR, "[data-pre-plain-text]")
    if not tags:
        return None
    match = re.match(r"\s*\[([^\]]+)\]", tags[0].get_attribute("data-pre-plain-text") or "")
    if not match:
        return None

    stamp = match.group(1).replace(" ", " ").replace("‎", "").strip().upper()

    # "8/6/2026" is ambiguous: exports use D/M/Y, the DOM uses M/D/Y. Parse both
    # and keep whichever is closest to now without being in the future.
    now = datetime.now()
    best = None
    for fmt in ("%I:%M %p, %d/%m/%Y", "%I:%M %p, %m/%d/%Y",
                "%H:%M, %d/%m/%Y", "%H:%M, %m/%d/%Y"):
        try:
            candidate = datetime.strptime(stamp, fmt)
        except ValueError:
            continue
        if candidate > now + timedelta(minutes=5):
            continue
        if best is None or candidate > best:
            best = candidate
    return best


def last_incoming_age_minutes(driver, contact_name=""):
    incoming = [b for who, b in message_bubbles(driver, contact_name) if who == "them"]
    for bubble in reversed(incoming[-5:]):
        when = bubble_time(bubble)
        if when:
            return (datetime.now() - when).total_seconds() / 60.0
    return None


def send_message(driver, text):
    """send_keys can't type emoji (BMP only), so use CDP Input.insertText."""
    box = first_match(driver, [
        'footer div[contenteditable="true"]',
        'div[contenteditable="true"][data-tab="10"]',
        '#main div[contenteditable="true"]',
    ])
    if box is None:
        print("      !! message box not found")
        return False

    text = " ".join(line for line in text.split("\n") if line.strip())

    try:
        box.click()
        time.sleep(0.2)
    except Exception as e:
        print(f"      !! couldn't focus the message box: {e}")
        return False

    try:
        driver.execute_cdp_cmd("Input.insertText", {"text": text})
    except Exception:
        stripped = "".join(ch for ch in text if ord(ch) <= 0xFFFF).strip()
        if not stripped:
            print("      !! emoji-only reply and CDP failed, skipping")
            return False
        try:
            box.send_keys(stripped)
        except Exception as e:
            print(f"      !! typing failed: {e}")
            return False

    time.sleep(0.2)
    try:
        box.send_keys(Keys.ENTER)
    except Exception as e:
        print(f"      !! couldn't press Enter: {e}")
        return False
    return True


# ---------------------------------------------------------------- MAIN CYCLE

def click_row(driver, row):
    """
    Open a chat from the list.

    A native click aims at the element's centre and fails if anything overlaps
    it -- rows low in the list sit behind the footer bar. So: scroll it into
    view first, then fall back to a JS click, which dispatches the event
    directly and ignores what's painted on top.
    """
    try:
        driver.execute_script(
            "arguments[0].scrollIntoView({block:'center', behavior:'instant'});", row
        )
        time.sleep(0.3)
    except Exception:
        pass

    try:
        row.click()
        return True
    except Exception:
        pass

    try:
        driver.execute_script("arguments[0].click();", row)
        return True
    except Exception:
        pass

    # Last resort: click the inner cell rather than the row wrapper.
    try:
        inner = first_match(row, ['[data-testid="cell-frame-container"]',
                                  '[role="gridcell"]', "div"])
        if inner is not None:
            driver.execute_script("arguments[0].click();", inner)
            return True
    except Exception:
        pass

    return False


def handle_chat(driver, row, chats, rules, default, store, bot_sent, replied,
                cooldown, known_name=""):
    mention_badge = row_has_mention_badge(row)      # read before clicking; opening clears it

    if not click_row(driver, row):
        print(f"  !! couldn't open {known_name or 'chat'} -- retrying next cycle")
        return

    try:
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "#main"))
        )
    except TimeoutException:
        print("  !! chat pane didn't load")
        return

    name = known_name or get_chat_title(driver)

    # Poll for bubbles instead of guessing a sleep -- messages stream in after #main.
    deadline = time.time() + 8
    while time.time() < deadline:
        if message_bubbles(driver, name):
            break
        time.sleep(0.4)
    time.sleep(0.6)

    age = last_incoming_age_minutes(driver, name)
    if age is not None and age > MAX_MESSAGE_AGE_MINUTES:
        print(f"\n  {name}   [last message {age:.0f}m old -> skipping]")
        return

    policy = policy_for(name, rules, default)
    is_group = is_group_chat(driver, name)
    tagged_message = None

    if is_group and policy != "never":
        if GROUP_POLICY == "skip":
            print(f"\n  {name}   [GROUP -> skipped]")
            return

        if GROUP_POLICY == "learn":
            policy = "never"

        elif GROUP_POLICY == "mention":
            tagged_message = last_incoming_mentioning_me(driver, name)
            if not (mention_badge or tagged_message):
                print(f"\n  {name}   [GROUP -> not tagged, learning only]")
                history = get_recent_messages(driver, count=12, contact_name=name)
                h, b = memory.harvest(store, name, history, bot_sent)
                if h or b:
                    memory.save(store)
                    print(f"    learned {h} new reply(s) from you")
                return
            policy = "draft" if policy == "never" else policy
        else:
            policy = "draft"

    label = f"GROUP@, {policy}" if (is_group and tagged_message) else \
            (f"GROUP, {policy}" if is_group else policy)
    print(f"\n  {name}   [{label}]")

    history = get_recent_messages(driver, count=12, contact_name=name)

    # Learn before replying -- anything you typed yourself is the best training data.
    learned_human, learned_bot = memory.harvest(store, name, history, bot_sent)
    if learned_human or learned_bot:
        memory.save(store)
        note = f"    learned {learned_human} new reply(s) from you"
        if learned_bot:
            note += f"  (+{learned_bot} bot replies logged, not used as examples)"
        print(note)

    if policy == "never":
        print("    -> protected contact, not replying. Go read it yourself.")
        return

    incoming = [t for who, t in history if who == "them"]
    if not incoming:
        bubbles = message_bubbles(driver, name)
        if not bubbles:
            print("    -> NO MESSAGE BUBBLES FOUND. Run: python debug_selectors.py")
        else:
            outgoing = sum(1 for who, _ in bubbles if who == "you")
            print(f"    -> {len(bubbles)} bubbles ({outgoing} yours), no readable "
                  f"incoming text -- media only")
        return

    # A GIF/sticker/voice note has nothing to reply to, and answering the last
    # TEXT message instead means responding to something already moved past.
    bubbles = message_bubbles(driver, name)
    if bubbles:
        who_last, last_bubble = bubbles[-1]
        if who_last == "them" and not bubble_text(last_bubble, driver):
            kind = "media" if bubble_is_media(last_bubble) else "unreadable"
            print(f"    -> their last message is {kind}, not replying")
            return

    # Only reply when they spoke last, or the bot re-answers itself every cycle.
    # Groups are exempt: other people talk between your tag and now.
    if not is_group and history and history[-1][0] != "them":
        print("    -> I spoke last, waiting for them to reply")
        return

    last = tagged_message or incoming[-1]

    if replied.get(name) == last:
        print("    -> already replied to this message, skipping")
        return

    print(f"    them: {last}")

    # What I've already said here, so the model doesn't say it again.
    already_said = [t for who, t in history if who == "you"][-6:]

    try:
        reply = brain.generate_reply(
            contact=name,
            incoming=last,
            chats=chats,
            recent_context=history[:-1][-4:],
            avoid=already_said,
            verbose=True,
        )
    except brain.QuotaError as e:
        cooldown["until"] = time.time() + e.retry_after
        print(f"    !! quota exhausted -- pausing all replies for {e.retry_after}s")
        return
    except Exception as e:
        print(f"    !! brain error: {str(e).splitlines()[0][:120]}")
        return

    if reply is None:
        print("    -> reply rejected (SKIP, or it leaked prompt text)")
        return

    if policy == "auto" and SEND_ENABLED:
        if send_message(driver, reply):
            print(f"    SENT: {reply}")
            replied[name] = last
            bot_sent.add(reply.strip())     # so we don't train on our own output
        time.sleep(random.uniform(3, 7))
    else:
        why = "draft policy" if policy == "draft" else "SEND_ENABLED is False"
        replied[name] = last
        print(f"    DRAFT: {reply}")
        print(f"    (not sent -- {why})")


def run_cycle(driver, chats, rules, default, store, bot_sent, backlog, started_at,
              replied, cooldown):
    remaining = cooldown["until"] - time.time()
    if remaining > 0:
        print(f"API cooling down, {remaining:.0f}s left -- skipping this scan.")
        return

    rows = find_unread_rows(driver)
    if not rows:
        print("No chats found.")
        return

    queue = []
    skipped = {}

    def note(reason):
        skipped[reason] = skipped.get(reason, 0) + 1

    for row in rows:
        try:
            name = row_chat_name(row)
            age = row_age_minutes(row)
        except StaleElementReferenceException:
            note("row went stale")
            continue

        if not name:
            note("unreadable name")
            continue

        if name in backlog:
            # Leaves the backlog once a message arrives newer than our start time.
            arrived = (datetime.now() - timedelta(minutes=age)) if age is not None else None
            if arrived is not None and arrived > started_at:
                backlog.discard(name)
                print(f"  - {name[:28]:<30} new message -> off the backlog")
            else:
                note("startup backlog")
                continue

        if age is None:
            note("no readable timestamp")
            continue
        if age > MAX_MESSAGE_AGE_MINUTES:
            note(f"older than {MAX_MESSAGE_AGE_MINUTES}m")
            continue

        print(f"  - {name[:28]:<30} QUEUED ({age:.0f}m old)")
        queue.append((row, name, age))

    summary = ", ".join(f"{n} {reason}" for reason, n in sorted(skipped.items()))
    print(f"{len(rows)} chats scanned, {len(queue)} to handle."
          + (f"   skipped: {summary}" if summary else ""))

    # Rows go stale the moment one is clicked, so re-find each by name.
    for _row, name, age in queue[:MAX_PER_CYCLE]:
        fresh_row = None
        try:
            for candidate in find_unread_rows(driver):
                try:
                    if row_chat_name(candidate) == name:
                        fresh_row = candidate
                        break
                except StaleElementReferenceException:
                    continue
        except StaleElementReferenceException:
            continue

        if fresh_row is None:
            continue

        try:
            handle_chat(driver, fresh_row, chats, rules, default, store, bot_sent,
                        replied, cooldown, known_name=name)
        except StaleElementReferenceException:
            print(f"  {name}: page re-rendered, retrying next cycle")
        except Exception as e:
            print(f"  {name}: {type(e).__name__}: {str(e).splitlines()[0][:90]}")


def main():
    test_mode = "--test" in sys.argv
    global IGNORE_BACKLOG_ON_START, MAX_MESSAGE_AGE_MINUTES
    if test_mode:
        IGNORE_BACKLOG_ON_START = False
        MAX_MESSAGE_AGE_MINUTES = 60 * 24 * 365
        print("*** TEST MODE: age limits disabled ***\n")

    claim_single_instance()

    chats = brain.load_chats()
    rules, default = load_policies()
    store = memory.load()
    bot_sent = {p["me"] for p in store["pairs"] if p["source"] == "bot"}

    total = sum(c["pair_count"] for c in chats["contacts"].values())
    live = len([p for p in store["pairs"] if p["source"] in memory.TRUSTED])
    print(f"Loaded {total} reply pairs across {len(chats['contacts'])} contacts "
          f"({live} learned live since the export).")
    print(f"SEND_ENABLED = {SEND_ENABLED}"
          f"{'' if SEND_ENABLED else '   (draft only)'}")
    print(f"GROUP_POLICY = {GROUP_POLICY}")
    print("Ctrl+C to stop.\n")

    driver = build_driver()
    cycles = 0
    try:
        wait_until_loaded(driver)

        backlog = set()
        replied = {}
        cooldown = {"until": 0.0}
        started_at = datetime.now()

        if IGNORE_BACKLOG_ON_START:
            time.sleep(2)
            backlog = {row_chat_name(r) for r in find_unread_rows(driver)}
            backlog.discard("")
            started_at = datetime.now()
            if backlog:
                print(f"Ignoring {len(backlog)} chat(s) already unread at startup:")
                for n in sorted(backlog):
                    print(f"  - {n}")
                print("(picked up as soon as a NEW message arrives)\n")

        while True:
            try:
                run_cycle(driver, chats, rules, default, store, bot_sent,
                          backlog, started_at, replied, cooldown)
            except Exception as e:
                print(f"cycle error (continuing): {e}")

            cycles += 1
            if cycles % 10 == 0:
                chats = brain.load_chats()      # fold in newly learned pairs
                print("  [refreshed example pool]")

            print(f"\n--- sleeping {POLL_SECONDS}s ---\n")
            time.sleep(POLL_SECONDS)
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        memory.save(store)
        driver.quit()


if __name__ == "__main__":
    main()
