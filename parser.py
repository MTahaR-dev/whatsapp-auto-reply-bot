"""Turns WhatsApp chat-export zips into clean {them -> me} reply pairs.

Run once:
    python parser.py        ->  data/chats.json
"""

import io
import json
import os
import re
import zipfile
from collections import Counter
from datetime import datetime, timedelta

# ---------------------------------------------------------------- CONFIG

HERE = os.path.dirname(os.path.abspath(__file__))
EXPORT_DIR = os.path.expanduser(r"~\Downloads")
OUTPUT = os.path.join(HERE, "data", "chats.json")


def load_me():
    """Your display name EXACTLY as it appears in the export. From contacts.json."""
    path = os.path.join(HERE, "contacts.json")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            me = json.load(f).get("_me")
            if me:
                return me
    raise SystemExit(
        'Set "_me" in contacts.json to your display name as it appears in the\n'
        'export, e.g. open a _chat.txt and look at the name on your own lines.\n'
        "Copy contacts.example.json to contacts.json if you haven't yet."
    )


ME = load_me()

JUNK = (
    "omitted", "This message was deleted", "You deleted this message",
    "end-to-end encrypted", "changed the subject", "changed this group's icon",
    "created group", "added you", "joined using this group's invite link",
    "Missed voice call", "Missed video call", "null",
)

# Non-greedy sender + the FIRST ": " is what lets a sender named ":)" parse.
# A plain split(":") silently drops every message you ever sent.
LINE = re.compile(r"^‎?\[(\d{1,2}/\d{1,2}/\d{2,4}),\s([^\]]+)\]\s‎?(.+?): (.*)$")

MERGE_WINDOW = timedelta(minutes=5)     # same sender, close together = one turn
REPLY_WINDOW = timedelta(hours=6)       # answering days later isn't a reply


def is_junk(text):
    return any(j in text for j in JUNK) or not text.strip()


def parse_time(date_str, time_str):
    # WhatsApp uses U+202F before AM/PM and sprinkles U+200E around.
    stamp = f"{date_str} {time_str}".replace(" ", " ").replace("‎", "")
    for fmt in ("%d/%m/%Y %I:%M:%S %p", "%d/%m/%y %I:%M:%S %p",
                "%d/%m/%Y %H:%M:%S", "%d/%m/%y %H:%M:%S"):
        try:
            return datetime.strptime(stamp.strip(), fmt)
        except ValueError:
            continue
    return None


def parse_chat(raw_text):
    """-> [[timestamp, sender, message], ...]"""
    messages = []
    for line in raw_text.replace("\r\n", "\n").split("\n"):
        match = LINE.match(line)
        if match:
            date_str, time_str, sender, body = match.groups()
            messages.append([parse_time(date_str, time_str), sender.strip(), body])
        elif messages and line.strip():
            # No timestamp header = continuation of a multi-line message.
            messages[-1][2] += "\n" + line
    return messages


def collapse_runs(messages):
    """People send three texts in a row; merge them if they're close in time."""
    merged = []
    for stamp, sender, body in messages:
        if merged:
            last_stamp, last_sender, _ = merged[-1]
            close = (stamp is not None and last_stamp is not None
                     and stamp - last_stamp <= MERGE_WINDOW)
            if last_sender == sender and close:
                merged[-1][2] += " " + body
                merged[-1][0] = stamp
                continue
        merged.append([stamp, sender, body])
    return merged


def make_pairs(messages):
    clean = [m for m in messages if not is_junk(m[2])]
    merged = collapse_runs(clean)

    pairs = []
    for i in range(len(merged) - 1):
        stamp, sender, body = merged[i]
        next_stamp, next_sender, next_body = merged[i + 1]

        if sender == ME or next_sender != ME:
            continue
        if stamp and next_stamp and next_stamp - stamp > REPLY_WINDOW:
            continue

        pairs.append({"them": body.strip(), "me": next_body.strip()})
    return pairs


def read_export(zip_path):
    with zipfile.ZipFile(zip_path) as z:
        name = next((n for n in z.namelist() if n.endswith(".txt")), None)
        if name is None:
            return None
        with z.open(name) as f:
            return io.TextIOWrapper(f, encoding="utf-8", errors="replace").read()


def main():
    zips = [
        os.path.join(EXPORT_DIR, f)
        for f in os.listdir(EXPORT_DIR)
        if f.startswith("WhatsApp Chat - ") and f.endswith(".zip")
    ]
    if not zips:
        print(f"No WhatsApp exports found in {EXPORT_DIR}")
        return

    result = {"me": ME, "contacts": {}}
    total = 0

    for path in sorted(zips):
        filename_name = os.path.basename(path)[len("WhatsApp Chat - "):-len(".zip")]

        raw = read_export(path)
        if raw is None:
            print(f"  !! no .txt inside {filename_name}")
            continue

        messages = parse_chat(raw)

        # Take the name from INSIDE the chat: Windows replaces characters it
        # can't put in a filename (a zero-width joiner becomes "_"), and the key
        # would then never match the real WhatsApp chat title.
        others = [s for _, s, _ in messages if s != ME]
        contact = Counter(others).most_common(1)[0][0] if others else filename_name
        if contact != filename_name:
            print(f"  ~  filename {filename_name!r} -> real name {contact!r}")

        pairs = make_pairs(messages)

        senders = Counter(m[1] for m in messages)
        if ME not in senders:
            print(f"  !! '{ME}' not found in {contact}. Senders seen: {list(senders)}")

        my_words = [len(p["me"].split()) for p in pairs]
        result["contacts"][contact] = {
            "pair_count": len(pairs),
            "avg_words": round(sum(my_words) / len(my_words), 1) if my_words else 0,
            "pairs": pairs,
        }
        total += len(pairs)
        print(f"  {contact[:34]:<36} {len(pairs):>4} pairs")

    os.makedirs(os.path.dirname(OUTPUT), exist_ok=True)
    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"\n  {'TOTAL':<36} {total:>4} pairs")
    print(f"  saved -> {OUTPUT}")


if __name__ == "__main__":
    main()
