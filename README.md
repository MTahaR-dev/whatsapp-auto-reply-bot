# WhatsApp Auto-Reply Bot

Replies to your WhatsApp messages in **your own writing style**, learned from your real chat history.

It reads your exported chats, finds every `they said → you replied` pair, and stores them. When a new message arrives it **retrieves the most similar past exchanges** and feeds them to an LLM as few-shot examples — retrieval-augmented generation over your own message history. The result sounds like you — your slang, your message length, your habit of being short with some people and chatty with others — instead of a generic assistant.

Built with Selenium (WhatsApp Web) and the Google Gemini API.

---

## Demo

<!--
  HOW TO ADD YOUR VIDEO:

  Option A (easiest, plays inline on GitHub):
    Open an issue in this repo, drag the .mp4 into the comment box, wait for
    upload, then copy the generated user-images.githubusercontent.com URL and
    paste it below as a bare link on its own line. GitHub renders it as a
    player. Max 10 MB on free accounts.

  Option B (YouTube):
    [![Watch the demo](https://img.youtube.com/vi/VIDEO_ID/maxresdefault.jpg)](https://youtu.be/VIDEO_ID)

  Option C (GIF, always works, no player needed):
    ![Demo](docs/demo.gif)

  Delete this comment once the video is in.
-->

> **Demo video coming soon.**

<!-- PASTE VIDEO LINK BELOW THIS LINE -->


---

## How the retrieval works

```
incoming message
      |
      v
TF-IDF index over your past `them` messages for that contact
      |
      +-- 15 most similar exchanges   (how you answered this kind of thing)
      +-- 10 random exchanges         (your general range and tone)
      |
      v
prompt = examples + last 4 messages + what you've already said
      |
      v
Gemini -> sanitiser -> WhatsApp
```

Indexing the *incoming* side rather than the reply is the point: the question being answered is *"when someone said something like this before, what did I say back?"*

Similarity uses words **and** character 3-grams. Roman Urdu has no fixed spelling — `kya`/`kia`, `hai`/`hy`/`he`, `kar raha`/`krra` are the same words typed differently, and word matching alone misses them. Character n-grams overlap even when spelling doesn't.

Measured against random sampling across 6 contacts, the retrieved examples are **4.8x more relevant** to the message being answered.

---

## Why this isn't a pyautogui script

Most WhatsApp bot tutorials click fixed screen coordinates. That breaks the moment the window moves, the resolution changes, or a notification shifts the layout.

This one targets **DOM elements**, so window position is irrelevant. It also handles the parts that actually bite you in practice:

- WhatsApp's obfuscated class names change every few months → every lookup tries a list of fallback selectors
- Emoji are rendered as `<img>` tags, so `.text` silently drops them → the DOM is walked and `alt` attributes are swapped back in
- Selenium physically cannot type emoji (`send_keys` is BMP-only) → replies are inserted via Chrome DevTools instead
- Chat list rows go stale the instant one is clicked → rows are re-found by name before use

---

## Features

**Talks like you**
- **Retrieval-augmented**: TF-IDF over your history surfaces the exchanges most similar to the incoming message, so the model sees how you answered *this kind* of thing — measured at **4.8x more relevant** than random sampling
- Per-contact style: examples come from *that person's* chat, so the tone matches who you're talking to
- Word + character n-gram matching, so Roman Urdu spelling variants (`kya`/`kia`, `hai`/`hy`) still match
- Falls back to a general pool for people you have no history with

**Knows when to stay quiet**
- Only replies when *they* spoke last, so it never talks to itself
- Ignores messages older than 30 minutes
- Skips GIFs, stickers, voice notes and photos rather than replying to nothing
- Never repeats a reply it already sent

**Per-contact control** — `auto` (sends), `draft` (shows you, sends nothing), `never` (silent)

**Groups** — silent unless you're actually tagged, and it replies to the message that tagged you, not the last thing said

**Keeps learning** — every reply you type by hand is absorbed as a new example. Replies the *bot* wrote are stored but never reused as examples, which prevents it drifting away from your real voice over time.

**Output sanitising** — strips markdown, stray tags and prompt fragments before anything is sent

---

## Setup

### 1. Requirements

- Python 3.10+
- Google Chrome
- A free Gemini API key: <https://aistudio.google.com/apikey>

### 2. Install

```bash
git clone <your-repo-url>
cd whatsapp-auto-reply-bot

python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS / Linux

pip install -r requirements.txt
```

### 3. API key

Set it as an environment variable — never hardcode it.

```powershell
setx GEMINI_API_KEY "your_key_here"     # Windows, then REOPEN the terminal
```

```bash
export GEMINI_API_KEY="your_key_here"   # macOS / Linux
```

### 4. Export your chats

In WhatsApp on your phone, for each chat you want the bot to learn from:

> Chat → ⋮ menu → **Export chat** → **Without media**

Save the `.zip` files to your **Downloads** folder. Don't unzip them.

More chats = better results. A handful of your most active ones is plenty.

### 5. Configure

```bash
copy contacts.example.json contacts.json     # Windows
cp contacts.example.json contacts.json       # macOS / Linux
```

Open `contacts.json` and set:

**`_me`** — your display name **exactly** as it appears in the export. Unzip one export and look at a `_chat.txt`:

```
[15/06/2026, 8:38:33 PM] Alex: are you coming?
[15/06/2026, 8:39:02 PM] :): yeah
                         ^^^ this is your _me value
```

It's often a nickname or symbol, not your real name. Get this wrong and the parser finds zero of your messages.

**`_persona`** — your first name and a one-line description. The model needs to know whose voice it's copying.

**`_aliases`** — how people tag you in groups. Include your number without the `+`, since WhatsApp stores mentions as `@<number>` internally.

**Contacts** — chat names exactly as they appear in WhatsApp, emoji included:

```json
{
  "_persona": { "name": "Alex", "about": "a 21-year-old university student" },
  "_me": ":)",
  "_aliases": ["@YourName", "@<your-number-no-plus>"],
  "_default": "draft",

  "Best Friend": "auto",
  "Study Group": "draft",
  "Family": "never"
}
```

Start everyone on `draft` until you trust it.

### 6. Build your history

```bash
python parser.py
```

Reads the zips from Downloads and writes `data/chats.json`.

### 7. Test the replies — no WhatsApp involved

```bash
python brain.py
```

Sends three fake messages to the model and prints what it would reply. **Do this before running the bot.** If it doesn't sound like you, tune `SYSTEM_PROMPT` in `brain.py` — there's no point debugging the browser side until the voice is right.

### 8. Run it

```bash
python bot.py
```

A Chrome window opens with a QR code. Scan it once — the session is saved in `chrome_profile/` and you'll never scan again.

---

## Going live

The bot ships in **draft mode**. It writes replies to the terminal and sends nothing.

Three independent locks, all of which must be opened before a message can leave your phone:

1. `SEND_ENABLED = True` in `bot.py`
2. That contact set to `"auto"` in `contacts.json`
3. The model didn't return `SKIP` and the sanitiser didn't reject the output

Watch it draft for a while first. Then flip **one** contact to `auto`.

---

## Configuration

All in the CONFIG block at the top of `bot.py`:

| Setting | Default | What it does |
|---|---|---|
| `SEND_ENABLED` | `False` | Master switch. `False` = never sends |
| `MAX_MESSAGE_AGE_MINUTES` | `30` | Ignore anything older |
| `GROUP_POLICY` | `"mention"` | `mention` / `skip` / `learn` / `draft` |
| `POLL_SECONDS` | `30` | Seconds between scans |
| `MAX_PER_CYCLE` | `5` | Chats handled per scan |
| `HEADLESS` | `False` | Hide Chrome. Only after the QR is scanned |
| `USE_UNREAD_FILTER` | `False` | `True` = only WhatsApp's unread list |

Retrieval settings are in `brain.py`:

| Setting | Default | What it does |
|---|---|---|
| `RETRIEVAL` | `True` | `False` = random example sampling |
| `SIMILAR_EXAMPLES` | `15` | Top matches for the incoming message |
| `RANDOM_EXAMPLES` | `10` | Random extras, so your general range stays visible |
| `IGNORE_BACKLOG_ON_START` | `False` | `True` = ignore what's already unread |

Model settings live in `brain.py` — `MODEL_PREFERENCE` picks the cheapest working model, since full Flash models allow only ~20 free requests per day.

---

## Running in the background (Windows)

```
start_bot.bat      run with a console window, auto-restarts on crash
run_hidden.vbs     run with NO console window
stop_bot.bat       stop everything
```

**Autostart:** `Win+R` → `shell:startup` → put a shortcut to `run_hidden.vbs` there.

With no console, the log is your only visibility:

```powershell
Get-Content "logs\bot_YYYY-MM-DD.log" -Tail 30
```

---

## Files

```
bot.py                  main loop, WhatsApp automation, all the safety rules
brain.py                builds the prompt, calls Gemini, sanitises the output
retriever.py            TF-IDF similarity search over your past exchanges
memory.py               keeps learning new pairs while it runs
parser.py               chat export zips -> data/chats.json
debug_selectors.py      run this when WhatsApp changes its markup
contacts.example.json   template for your config
```

---

## When it breaks

WhatsApp changes its HTML every few months. When that happens the bot goes quiet or logs `NO MESSAGE BUBBLES FOUND`.

```bash
python debug_selectors.py
```

It opens the same Chrome profile, tries every selector, and reports which ones still match plus the raw HTML of a real message. Then update the relevant selector list in `bot.py` — each is an ordered list of candidates, so just add the new one on top.

**Other common issues**

| Symptom | Cause |
|---|---|
| `Another copy of the bot is already running` | Run `stop_bot.bat` |
| `DevToolsActivePort file doesn't exist` | Two bots sharing one Chrome profile |
| `429 RESOURCE_EXHAUSTED` | Free-tier quota. It pauses and resumes automatically |
| `'charmap' codec can't encode` | Non-UTF8 terminal. Use `start_bot.bat` |
| Parser finds 0 of your messages | `_me` in `contacts.json` is wrong |

---

## Privacy

**`.gitignore` keeps these out of the repo. Don't override it.**

- `chrome_profile/` — a live authenticated WhatsApp session. Anyone with this folder can read your messages as you.
- `contacts.json` — real names and your phone number
- `data/` — your parsed chat history
- `logs/` — message text

Your chat excerpts are sent to Google's API to generate replies. Strip anything sensitive before pointing this at chats you care about, and read Google's data-use terms for the tier you're on.

---

## A note on limits

Automated replying on a personal account isn't permitted under WhatsApp's Terms of Service, and bulk-send patterns can get accounts banned. That's why this has rate limits, human-like delays, and a per-cycle cap. Use it on your own account, with people who know, and keep it small.

For anything real, the supported route is the [WhatsApp Business Cloud API](https://developers.facebook.com/docs/whatsapp/cloud-api) — a proper REST API with no browser automation.

---

## License

MIT
