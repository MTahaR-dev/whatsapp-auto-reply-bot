"""
Selector doctor.

When the bot says "No unread chats" while WhatsApp clearly shows unread ones,
run this. It opens the same Chrome profile, tries every selector we rely on,
and reports which ones actually match anything on YOUR version of WhatsApp.

    python debug_selectors.py

Keep this file. WhatsApp reshuffles its markup every few months, and this is
how you diagnose it in 30 seconds instead of an evening.
"""

import os
import time

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

HERE = os.path.dirname(os.path.abspath(__file__))
PROFILE_DIR = os.path.join(HERE, "chrome_profile")


def build_driver():
    opts = Options()
    opts.add_argument(f"--user-data-dir={PROFILE_DIR}")
    opts.add_argument("--profile-directory=Default")
    opts.add_argument("--start-maximized")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    driver = webdriver.Chrome(options=opts)
    driver.get("https://web.whatsapp.com")
    return driver


def report(driver, label, selector, by=By.CSS_SELECTOR, show=3):
    try:
        found = driver.find_elements(by, selector)
    except Exception as e:
        print(f"  [ERR ] {label:<34} {e.__class__.__name__}")
        return []

    mark = "OK  " if found else "MISS"
    print(f"  [{mark}] {label:<34} {len(found):>3}  ({selector[:42]})")

    for el in found[:show]:
        try:
            text = (el.text or "").replace("\n", " | ")[:70]
            if text:
                print(f"           -> {text}")
        except Exception:
            pass
    return found


def main():
    driver = build_driver()
    try:
        print("\nWaiting for WhatsApp to load (scan QR if needed)...")
        WebDriverWait(driver, 180).until(
            lambda d: d.find_elements(By.ID, "pane-side")
            or d.find_elements(By.CSS_SELECTOR, '[aria-label*="Chat list"]')
            or d.find_elements(By.CSS_SELECTOR, '[data-testid="chat-list"]')
        )
        time.sleep(3)
        print("Loaded.\n")

        print("=" * 74)
        print("1. THE CHAT LIST CONTAINER")
        print("=" * 74)
        for label, sel in [
            ("#pane-side (what we use)", "#pane-side"),
            ('aria-label="Chat list"', '[aria-label*="Chat list"]'),
            ("data-testid=chat-list", '[data-testid="chat-list"]'),
            ("grid role", '[role="grid"]'),
            ("application role", '[role="application"]'),
        ]:
            report(driver, label, sel, show=0)

        print("\n" + "=" * 74)
        print("2. CHAT ROWS")
        print("=" * 74)
        for label, sel in [
            ('role="listitem" (what we use)', '[role="listitem"]'),
            ('role="row"', '[role="row"]'),
            ('role="gridcell"', '[role="gridcell"]'),
            ("#pane-side > div > div > div", "#pane-side > div > div > div"),
        ]:
            report(driver, label, sel, show=2)

        print("\n" + "=" * 74)
        print("3. UNREAD BADGES  <- the thing that's failing")
        print("=" * 74)
        for label, sel in [
            ('aria-label*="unread" (ours)', 'span[aria-label*="unread"]'),
            ('aria-label*="Unread" (ours)', 'span[aria-label*="Unread"]'),
            ("any element w/ unread label", '[aria-label*="unread"]'),
            ("any element w/ Unread label", '[aria-label*="Unread"]'),
            ("data-icon=unread", '[data-icon*="unread"]'),
            ("data-testid=unread", '[data-testid*="unread"]'),
            ("class contains unread", '[class*="unread"]'),
        ]:
            report(driver, label, sel)

        print("\n" + "=" * 74)
        print("4. THE 'UNREAD' FILTER TAB  <- likely a better approach entirely")
        print("=" * 74)
        for label, sel in [
            ("buttons in the filter bar", '[role="tablist"] button'),
            ("any tab role", '[role="tab"]'),
            ("aria-label Unread filter", '[aria-label*="Unread"]'),
        ]:
            report(driver, label, sel, show=6)

        print("\n" + "=" * 74)
        print("5. EVERY aria-label CONTAINING A DIGIT (badges live here)")
        print("=" * 74)
        seen = set()
        for el in driver.find_elements(By.CSS_SELECTOR, "[aria-label]"):
            try:
                label = el.get_attribute("aria-label") or ""
            except Exception:
                continue
            if any(ch.isdigit() for ch in label) and label not in seen:
                seen.add(label)
                print(f"    {el.tag_name:<6} aria-label={label!r}")
            if len(seen) > 25:
                break
        if not seen:
            print("    (none found)")

        print("\n" + "=" * 74)
        print("6. RAW HTML OF THE FIRST 2 CHAT ROWS")
        print("=" * 74)
        rows = (driver.find_elements(By.CSS_SELECTOR, '[role="listitem"]')
                or driver.find_elements(By.CSS_SELECTOR, '[role="row"]')
                or driver.find_elements(By.CSS_SELECTOR, '[role="gridcell"]'))
        for i, row in enumerate(rows[:2]):
            try:
                html = row.get_attribute("outerHTML") or ""
                print(f"\n  --- row {i} ({len(html)} chars, first 1400) ---")
                print("  " + html[:1400].replace("><", ">\n  <"))
            except Exception as e:
                print(f"  couldn't read row {i}: {e}")

        print("\n" + "=" * 74)
        print("7. MESSAGE BUBBLES  <- open a chat with text messages first!")
        print("=" * 74)
        input("\n  Open any chat that has TEXT messages, then press Enter...\n")
        time.sleep(1.5)

        main = driver.find_elements(By.CSS_SELECTOR, "#main")
        print(f"  #main found: {bool(main)}")
        scope = main[0] if main else driver

        for label, sel in [
            ("div[data-id]  (strategy A)", "div[data-id]"),
            ("[data-id] any tag", "[data-id]"),
            (".message-in  (strategy B)", "div.message-in"),
            (".message-out (strategy B)", "div.message-out"),
            ('role="row"    (strategy C)', '[role="row"]'),
            ('role="application"', '[role="application"]'),
            ("copyable-text", "[data-pre-plain-text]"),
            ("span.selectable-text", "span.selectable-text"),
            ("class*=selectable-text", '[class*="selectable-text"]'),
            ("class*=message", '[class*="message"]'),
        ]:
            report(scope, label, sel, show=2)

        print("\n  --- data-id values (true_=you, false_=them) ---")
        found_ids = False
        for el in scope.find_elements(By.CSS_SELECTOR, "[data-id]")[:8]:
            try:
                print(f"    {el.tag_name:<6} data-id={el.get_attribute('data-id')!r}")
                found_ids = True
            except Exception:
                pass
        if not found_ids:
            print("    (none -- strategy A is dead, we need another signal)")

        print("\n  --- RAW HTML OF THE LAST MESSAGE BUBBLE ---")
        candidates = (scope.find_elements(By.CSS_SELECTOR, "[data-pre-plain-text]")
                      or scope.find_elements(By.CSS_SELECTOR, '[role="row"]')
                      or scope.find_elements(By.CSS_SELECTOR, '[class*="message"]'))
        if candidates:
            html = candidates[-1].get_attribute("outerHTML") or ""
            print(f"  ({len(html)} chars, first 2000)\n")
            print("  " + html[:2000].replace("><", ">\n  <"))
        else:
            print("  NOTHING matched. Paste the output of the next block instead.")
            body = scope.get_attribute("innerHTML") or ""
            print(f"\n  --- #main innerHTML, first 2500 chars ---\n")
            print("  " + body[:2500].replace("><", ">\n  <"))

        print("\n\nDone. Paste section 7 -- that's what fixes the message reading.")
        input("Press Enter to close the browser...")

    finally:
        driver.quit()


if __name__ == "__main__":
    main()
