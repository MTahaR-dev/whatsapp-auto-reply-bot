"""Generates replies in your own voice, using your past messages as examples.

Setup:
    pip install google-genai
    Key: https://aistudio.google.com/apikey
    setx GEMINI_API_KEY "your_key"      (then reopen the terminal)

Test standalone:
    python brain.py
    python brain.py --models
"""

import json
import os
import random
import re
import time

from google import genai
from google.genai import types

import memory
import retriever

# ---------------------------------------------------------------- CONFIG

MODEL = None            # None = auto-pick; hardcoded names get retired and 404

# Lite models first: full Flash gives only ~20 free requests per DAY.
MODEL_PREFERENCE = [
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
    "gemini-2.5-flash-lite",
    "gemini-flash-lite-latest",
    "gemini-flash-latest",
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-2.5-flash",
]

HERE = os.path.dirname(os.path.abspath(__file__))
CHATS_FILE = os.path.join(HERE, "data", "chats.json")

EXAMPLES_PER_CONTACT = 25
THIN_HISTORY = 15               # below this, top up with examples from other chats
GENERAL_EXAMPLES = 20

# Retrieval: choose examples by similarity to the incoming message rather than
# at random. Set False to go back to pure random sampling.
RETRIEVAL = True
SIMILAR_EXAMPLES = 15           # top matches for the message being answered
RANDOM_EXAMPLES = 10            # random ones, so the model still sees your range


# Who the bot is pretending to be. Override with "_persona" in contacts.json
# so no personal details live in tracked code.
DEFAULT_PERSONA = {
    "name": "the user",
    "about": "a university student",
}


def system_prompt(persona=None):
    p = {**DEFAULT_PERSONA, **(persona or {})}
    name, about = p["name"], p["about"]
    return f"""You are writing WhatsApp replies AS {name}, {about}.

    Study the example exchanges carefully. They are real messages {name} has sent. \
    Copy that voice exactly:
    - the mix of languages used, and when it switches between them
    - message length (usually very short)
    - punctuation habits, capitalisation, and emoji use
    - bluntness and sarcasm with close friends

    Hard rules:
    - Output ONLY the reply text. No quotes, no markdown, no explanation, no \
    "{name}:" prefix, no asterisks.
    - Match the length of the usual replies. One or two words is often correct.
    - ANSWER WHAT WAS ACTUALLY ASKED. Engage with the specific message in front \
    of you. Do not fall back on a vague all-purpose reply.
    - Never repeat something already said in this conversation. If your reply \
    would echo an earlier one, say something different instead.
    - Never invent facts about {name}'s life, plans, marks, or whereabouts. When \
    you genuinely can't know, deflect in {name}'s own words, drawn from the \
    examples -- never with a stock phrase.
    - Never mention being an AI, a bot, or a language model.
    - If the message needs a real human decision (money, family emergency, \
    anything serious), reply with exactly: SKIP
    """


def load_persona():
    path = os.path.join(HERE, "contacts.json")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f).get("_persona") or {}
    return {}


_PERSONA = load_persona()
PERSONA_NAME = _PERSONA.get("name", DEFAULT_PERSONA["name"])
SYSTEM_PROMPT = system_prompt(_PERSONA)


# ---------------------------------------------------------------- EXAMPLES

def load_chats(path=CHATS_FILE, include_live=True):
    """The export is a snapshot; memory.py keeps adding to it while the bot runs."""
    if not os.path.exists(path):
        raise SystemExit(f"{path} not found -- run `python parser.py` first.")
    with open(path, encoding="utf-8") as f:
        chats = json.load(f)

    if include_live:
        for contact, pairs in memory.trusted_pairs_by_contact(memory.load()).items():
            slot = chats["contacts"].setdefault(
                contact, {"pair_count": 0, "avg_words": 0, "pairs": []}
            )
            slot["pairs"].extend(pairs)
            slot["pair_count"] = len(slot["pairs"])
    return chats


def _select(pairs, query, key, n_similar, n_random):
    """
    Retrieve by similarity, then top up with random picks.

    Pure similarity would show the model one narrow topic and it starts
    parroting. The random half keeps your general range -- length, tone,
    the way you open and close a conversation -- in view.
    """
    if not pairs:
        return [], 0

    if not (RETRIEVAL and query):
        return random.sample(pairs, min(n_similar + n_random, len(pairs))), 0

    hits = retriever.get_index(key, pairs).search(query, k=n_similar)
    chosen = [pair for pair, _score in hits]

    # Top up with random picks. If retrieval found fewer than asked for -- a
    # short message, or one with no words in common with anything -- make up
    # the shortfall too, so the model always gets a full set of examples.
    shortfall = n_similar - len(chosen)
    seen = {id(p) for p in chosen}
    rest = [p for p in pairs if id(p) not in seen]
    if rest:
        chosen += random.sample(rest, min(n_random + shortfall, len(rest)))

    return chosen, len(hits)


def pick_examples(chats, contact, query=""):
    """Their own history if there's enough of it, otherwise top up from everyone."""
    contacts = chats["contacts"]
    own = contacts.get(contact, {}).get("pairs", [])

    if len(own) >= THIN_HISTORY:
        chosen, n_hits = _select(own, query, contact,
                                 SIMILAR_EXAMPLES, RANDOM_EXAMPLES)
        random.shuffle(chosen)
        how = f"{n_hits} similar + {len(chosen) - n_hits} random" if n_hits else "random"
        return chosen, f"{len(chosen)} from {contact} ({how})"

    pool = []
    for name, data in contacts.items():
        if name != contact:
            pool.extend(data["pairs"])

    general, n_hits = _select(pool, query, "__general__",
                              SIMILAR_EXAMPLES, GENERAL_EXAMPLES - SIMILAR_EXAMPLES)
    chosen = own + general
    random.shuffle(chosen)

    how = f"{n_hits} similar" if n_hits else "random"
    if own:
        return chosen, f"{len(own)} from {contact} + {len(general)} general ({how}, thin history)"
    return chosen, f"{len(general)} general ({how}, no history with {contact})"


def build_prompt(examples, contact, incoming, recent_context=None, avoid=None):
    lines = [f"Here is how {PERSONA_NAME} has replied in the past:\n"]
    for pair in examples:
        lines.append(f"Them: {pair['them']}")
        lines.append(f"{PERSONA_NAME}: {pair['me']}\n")

    lines.append(f"\nNow reply to a message from {contact}.")

    if recent_context:
        lines.append("\nThe last few messages in this conversation:")
        for who, text in recent_context:
            lines.append(f"{who}: {text}")

    if avoid:
        lines.append("\nYou have ALREADY sent these. Do not repeat any of them:")
        for text in avoid:
            lines.append(f"- {text}")

    lines.append(f"\nReply to this specific message: {incoming}")
    lines.append(f"{PERSONA_NAME}:")
    return "\n".join(lines)


# ---------------------------------------------------------------- API

_client = None
_resolved_model = None


class QuotaError(RuntimeError):
    """Rate limited. Retrying spends quota you've already run out of, so don't."""
    def __init__(self, message, retry_after=60):
        super().__init__(message)
        self.retry_after = retry_after


class BrainError(RuntimeError):
    """Transient failure. A normal Exception so the bot's loop can catch it."""


def get_client():
    global _client
    if _client is None:
        key = os.environ.get("GEMINI_API_KEY")
        if not key:
            raise BrainError(
                "GEMINI_API_KEY is not set.\n"
                '  setx GEMINI_API_KEY "your_key"   (then reopen the terminal)'
            )
        _client = genai.Client(api_key=key)
    return _client


def available_models():
    names = []
    for m in get_client().models.list():
        actions = getattr(m, "supported_actions", None) or []
        if actions and "generateContent" not in actions:
            continue
        names.append(m.name.replace("models/", ""))
    return names


def resolve_model(verbose=False):
    """Ask the API what exists rather than trusting a name Google may have retired."""
    global _resolved_model
    if _resolved_model:
        return _resolved_model
    if MODEL:
        _resolved_model = MODEL
        return _resolved_model

    try:
        found = available_models()
    except Exception as e:
        raise BrainError(f"couldn't list models (network down, or bad key?): {e}")

    for want in MODEL_PREFERENCE:
        if want in found:
            _resolved_model = want
            break
    else:
        flash = [n for n in found if "flash" in n]
        _resolved_model = flash[0] if flash else (found[0] if found else None)

    if not _resolved_model:
        raise BrainError("no usable models found for this API key")
    if verbose:
        print(f"  using model: {_resolved_model}")
    return _resolved_model


# ---------------------------------------------------------------- SANITISER

# Fragments of the prompt the model sometimes echoes back at us.
_NAME_RE = re.escape(PERSONA_NAME)
PROMPT_LEAK = re.compile(
    r"(voice\s*&\s*style|hard rules?|system prompt|here (is|are) (the|how)|"
    rf"{_NAME_RE} messages|example exchanges|as {_NAME_RE}|reply the way|"
    rf"^\s*(them|{_NAME_RE}|you|me)\s*:|\*\*|^#{{1,6}}\s)",
    re.IGNORECASE | re.MULTILINE,
)


def has_content(text):
    """Letters, digits or emoji. Bare punctuation like "*" doesn't count."""
    return any(c.isalnum() or ord(c) > 0x2100 for c in text)


def clean_reply(text):
    """
    Last gate before a real message goes out. Fails closed on anything odd.
    Returns (cleaned_text_or_None, reason). The reason matters -- a silent
    rejection is impossible to debug.
    """
    if not text:
        return None, "model returned nothing"

    original = text.strip()
    text = original

    for prefix in (f"{PERSONA_NAME}:", "You:", "Me:", "Reply:", "Response:"):
        if text.lower().startswith(prefix.lower()):
            text = text[len(prefix):].strip()

    text = text.replace("**", "").replace("__", "")
    text = re.sub(r"^\s*[\*\-•]\s+", "", text, flags=re.MULTILINE)

    # Strip stray XML/HTML tags. The model sometimes closes a tag it never
    # opened -- "Oye</id>" got sent to a real group.
    text = re.sub(r"</?[a-zA-Z][^>]{0,40}>", "", text)
    text = re.sub(r"</?\s*>", "", text)

    # Drop lines that are pure punctuation -- catches a lone "*" on its own line.
    # Emoji count as content: "😭😭" is a perfectly normal reply.
    text = "\n".join(l for l in text.split("\n") if has_content(l))

    # Strip stray markdown at either end, e.g. "Fit aap sunao *"
    text = text.strip()
    while text and text[0] in "*_`":
        text = text[1:].lstrip()
    while text and text[-1] in "*_`":
        text = text[:-1].rstrip()

    text = text.strip().strip('"').strip("'").strip()

    if not text:
        return None, f"nothing left after cleaning {original[:60]!r}"

    leak = PROMPT_LEAK.search(text)
    if leak:
        return None, f"prompt leak {leak.group(0)!r} in {text[:60]!r}"

    if len(text) > 300:
        return None, f"too long ({len(text)} chars): {text[:60]!r}"
    if text.count("\n") > 3:
        return None, f"too many lines ({text.count(chr(10)) + 1}): {text[:60]!r}"
    if not has_content(text):
        return None, f"punctuation only: {text[:60]!r}"

    return text, "ok"


_config_level = 0       # which fallback we've settled on


def build_config(level=0):
    """
    Config candidates, most capable first.

    Two options aren't universally supported and only fail once the request
    reaches Google -- not when the object is built. So we can't validate them
    up front; we try, and step down a level on a 400.

      0  thinking off + stop sequences
      1  stop sequences only        (model insists on thinking)
      2  thinking off only          (model rejects stop sequences)
      3  neither                    (always works)

    Thinking matters because those tokens come out of max_output_tokens -- on a
    long prompt the whole budget goes to thinking and the reply comes back empty.
    """
    base = dict(
        system_instruction=SYSTEM_PROMPT,
        temperature=0.9,
        max_output_tokens=800,
    )
    stops = ["\nThem:", f"\n{PERSONA_NAME}:", "</"]

    try:
        if level == 0:
            return types.GenerateContentConfig(
                thinking_config=types.ThinkingConfig(thinking_budget=0),
                stop_sequences=stops, **base)
        if level == 1:
            return types.GenerateContentConfig(stop_sequences=stops, **base)
        if level == 2:
            return types.GenerateContentConfig(
                thinking_config=types.ThinkingConfig(thinking_budget=0), **base)
    except Exception:
        pass
    return types.GenerateContentConfig(**base)


def generate_reply(contact, incoming, chats=None, recent_context=None, verbose=False,
                   avoid=None):
    """Returns the reply text, or None if it should be skipped."""
    chats = chats or load_chats()
    examples, source = pick_examples(chats, contact, query=incoming)
    prompt = build_prompt(examples, contact, incoming, recent_context, avoid)

    if verbose:
        print(f"    [examples: {source}]")

    global _config_level

    last_error = None
    for attempt in range(4):
        try:
            response = get_client().models.generate_content(
                model=resolve_model(), contents=prompt,
                config=build_config(_config_level),
            )
            break
        except Exception as e:
            text = str(e)

            if "429" in text or "RESOURCE_EXHAUSTED" in text:
                delay = 60
                found = (re.search(r"retry in ([\d.]+)s", text)
                         or re.search(r"'retryDelay': '(\d+)s'", text))
                if found:
                    delay = int(float(found.group(1))) + 5
                raise QuotaError(f"rate limited, wait {delay}s", retry_after=delay)

            # The model rejected an option. Drop to a simpler config and retry
            # straight away -- this isn't a network problem, waiting won't help.
            if ("400" in text or "INVALID_ARGUMENT" in text) and _config_level < 3:
                _config_level += 1
                print(f"    [model rejected a config option -- "
                      f"falling back to level {_config_level}]")
                continue

            last_error = e
            if attempt < 3:
                wait = 2 ** attempt
                if verbose:
                    print(f"    [network error, retrying in {wait}s: {type(e).__name__}]")
                time.sleep(wait)
    else:
        raise BrainError(f"gave up after 4 attempts: {last_error}")

    raw = (response.text or "").strip()

    if not raw:
        if verbose:
            finish = getattr(getattr(response, "candidates", [None])[0], "finish_reason", "?")
            print(f"    [empty response from the model, finish_reason={finish}]")
        return None

    if raw.upper().startswith("SKIP"):
        if verbose:
            print("    [model chose SKIP -- thought it needed a human]")
        return None

    reply, reason = clean_reply(raw)
    if reply is None:
        if verbose:
            print(f"    [rejected: {reason}]")
        return None

    # Belt and braces: the instruction not to repeat isn't always obeyed.
    if avoid and reply.strip().lower() in {a.strip().lower() for a in avoid}:
        if verbose:
            print(f"    [rejected as a repeat: {reply!r}]")
        return None

    return reply


# ---------------------------------------------------------------- CLI TEST

if __name__ == "__main__":
    import sys

    if "--models" in sys.argv:
        print("Models available to your API key:\n")
        for name in available_models():
            print(f"  {name}")
        raise SystemExit

    chats = load_chats()

    print("Contacts loaded:")
    for name, data in chats["contacts"].items():
        print(f"  {name[:34]:<36} {data['pair_count']:>4} pairs")

    print()
    resolve_model(verbose=True)

    # Uses the first two contacts you actually have history with, so the test
    # exercises real per-contact style rather than the generic pool.
    known = sorted(chats["contacts"], key=lambda c: -chats["contacts"][c]["pair_count"])
    tests = [(c, "kya kar rahe ho?") for c in known[:2]]
    tests.append(("Someone New", "hi, can we talk?"))

    print("\nGenerating test replies...\n")
    for contact, message in tests:
        print(f"  {contact}")
        print(f"    them: {message}")
        try:
            reply = generate_reply(contact, message, chats, verbose=True)
            print(f"    me  : {reply if reply else '[SKIP]'}\n")
        except Exception as e:
            print(f"    !! {e}\n")
