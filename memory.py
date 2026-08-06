"""Keeps learning new reply pairs after the initial export, so the bot stays current.

Pairs are tagged by author:
    export / human -> really you, used as style examples
    bot            -> generated, NEVER used as an example

Training on the bot's own output makes it imitate its imitation. That drift is
model collapse, and it's the easiest way to ruin this project a month from now.
"""

import hashlib
import json
import os
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
LIVE_FILE = os.path.join(HERE, "data", "live_pairs.json")

TRUSTED = ("export", "human")


def _fingerprint(contact, them, me):
    blob = f"{contact}|{them.strip()}|{me.strip()}"
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:16]


def load():
    if not os.path.exists(LIVE_FILE):
        return {"seen": [], "pairs": []}
    with open(LIVE_FILE, encoding="utf-8") as f:
        return json.load(f)


def save(store):
    os.makedirs(os.path.dirname(LIVE_FILE), exist_ok=True)
    with open(LIVE_FILE, "w", encoding="utf-8") as f:
        json.dump(store, f, ensure_ascii=False, indent=2)


def record(store, contact, them, me, source):
    """Adds one pair unless we've seen it before. Returns True if it was new."""
    if not them.strip() or not me.strip():
        return False

    fp = _fingerprint(contact, them, me)
    if fp in store["seen"]:
        return False

    store["seen"].append(fp)
    store["pairs"].append({
        "contact": contact,
        "them": them.strip(),
        "me": me.strip(),
        "source": source,
        "at": datetime.now().isoformat(timespec="seconds"),
    })
    return True


def harvest(store, contact, history, bot_sent):
    """
    Saves any them -> you exchanges from a scraped conversation.

    bot_sent lets us tell replies you typed from replies the bot sent.
    Returns (new_human_pairs, new_bot_pairs).
    """
    merged = []
    for who, text in history:
        if merged and merged[-1][0] == who:
            merged[-1][1] += " " + text
        else:
            merged.append([who, text])

    human_added = bot_added = 0

    for i in range(len(merged) - 1):
        who, text = merged[i]
        next_who, next_text = merged[i + 1]
        if who != "them" or next_who != "you":
            continue

        source = "bot" if next_text.strip() in bot_sent else "human"
        if record(store, contact, text, next_text, source):
            if source == "human":
                human_added += 1
            else:
                bot_added += 1

    return human_added, bot_added


def trusted_pairs_by_contact(store):
    """{contact: [{them, me}, ...]} using only pairs you actually wrote."""
    out = {}
    for p in store["pairs"]:
        if p["source"] in TRUSTED:
            out.setdefault(p["contact"], []).append({"them": p["them"], "me": p["me"]})
    return out


REPLIED_FILE = os.path.join(HERE, "data", "replied.json")


def load_replied():
    """
    {chat: last incoming message we answered}, persisted across restarts.

    Kept on disk because the restart loop relaunches the bot every crash. In
    memory only, a restart wipes it and the bot answers the same message again
    -- which is exactly what happens in groups, where the "did they speak last"
    rule doesn't apply.
    """
    if not os.path.exists(REPLIED_FILE):
        return {}
    try:
        with open(REPLIED_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (ValueError, OSError):
        return {}


def save_replied(replied):
    os.makedirs(os.path.dirname(REPLIED_FILE), exist_ok=True)
    try:
        with open(REPLIED_FILE, "w", encoding="utf-8") as f:
            json.dump(replied, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


def stats(store):
    counts = {}
    for p in store["pairs"]:
        counts[p["source"]] = counts.get(p["source"], 0) + 1
    return counts


if __name__ == "__main__":
    store = load()
    print(f"live pairs: {len(store['pairs'])}")
    for source, n in sorted(stats(store).items()):
        flag = "used" if source in TRUSTED else "IGNORED as examples"
        print(f"  {source:<8} {n:>4}   ({flag})")

    by_contact = trusted_pairs_by_contact(store)
    if by_contact:
        print("\ntrusted pairs learned since the export:")
        for contact, pairs in sorted(by_contact.items(), key=lambda x: -len(x[1])):
            print(f"  {contact[:34]:<36} {len(pairs):>4}")
