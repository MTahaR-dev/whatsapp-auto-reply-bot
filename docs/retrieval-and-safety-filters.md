# Retrieval amplifies sensitive content, and that can trip provider safety filters

*Observed while building this bot, August 2026.*

## Summary

Switching example selection from **random sampling** to **similarity-based retrieval** made replies noticeably better — but it also introduced a failure mode that random sampling never had: for certain incoming messages, the assembled prompt was rejected outright by the model provider.

The cause is retrieval doing exactly what it's supposed to do. Retrieval concentrates whatever is semantically nearest to the query. If the nearest content happens to be sensitive, the prompt ends up with a much higher density of sensitive content than the corpus average — and that can cross a filter threshold the corpus itself never would.

## Setup

The bot answers WhatsApp messages using the user's own chat history as few-shot examples.

- Corpus: ~970 real `them → me` pairs from personal WhatsApp chats, mostly Roman Urdu
- Retrieval: TF-IDF over the incoming side, cosine similarity
- Prompt: 15 retrieved examples + 10 random + recent conversation context
- Model: Gemini 3.5 Flash Lite

The corpus is ordinary private messaging between friends. Like most such corpora, a small fraction contains crude slang and explicit language.

## What happened

An incoming message reading `"Kya Haal hai Meri jaan?"` (roughly *"how are you, my love?"*) produced:

```
[empty response: prompt blocked (BlockedReason.PROHIBITED_CONTENT)]
```

Note this is `prompt_feedback.block_reason` — the **input** was rejected. The model never generated anything to be filtered.

The incoming message itself is unremarkable. What got blocked was the prompt built around it.

## Why

`"meri jaan"` is affectionate and intimate in register. TF-IDF retrieval returns the past exchanges closest to it in the corpus — which are the user's most intimate and crude messages. Fifteen of them, concentrated into a single prompt.

Individually, each of those messages sat unremarkably in a 970-pair corpus. Retrieved together, their density was high enough to trip the filter.

Random sampling would rarely draw five explicit messages at once. Similarity search on an intimate phrase does so reliably.

## Evidence it was retrieval, not the message

The same message text succeeded in one chat and failed in another, differing only in which examples were retrieved:

| Chat | Examples in prompt | Result |
|---|---|---|
| DM | 13 from that contact + 20 general | **blocked** |
| Group | 2 from that contact + 20 general | sent |

It was also non-deterministic across cycles. Ten of the twenty-five examples are randomly drawn each call, so the same incoming text was blocked on one scan and answered on the next. A near-identical message without the affectionate phrase (`"Kya Haal hai?"`) consistently succeeded.

That points at the retrieved set, not the query.

## Implications

**The failure surface of a RAG system is not the union of its parts.** Every document can be individually acceptable while some retrieved *combination* is not. Auditing a corpus document-by-document will not find this.

**Retrieval quality and safety-filter risk move together.** The better retrieval is at finding semantically close material, the more reliably it concentrates whatever cluster the query points at — including clusters you'd rather it didn't.

**It is query-dependent and therefore hard to test for.** Most queries never surface the problematic cluster. Only queries semantically near it do, which means ordinary testing can miss it entirely.

**It presents as an unexplained empty response.** The provider returns no text and no error. Without reading `prompt_feedback.block_reason` specifically, it looks like a network fault, a token-limit problem, or a bug in your own code. In this project it initially surfaced as a `NoneType` crash inside the error handler, because `response.candidates` was `None` rather than empty — which hid the real cause entirely.

## What this project does about it

Nothing automatic, deliberately.

The bot logs the reason, skips the message, and moves on. For this use case that's the right outcome: a message opening with *"meri jaan"* is one the user should probably answer personally anyway.

Options for systems where silently skipping isn't acceptable:

- **Retry with retrieval disabled.** Falling back to random sampling for one call usually clears it, at the cost of reply quality.
- **Cap examples from any one similarity cluster.** Diversity-aware retrieval (e.g. MMR) reduces concentration by construction.
- **Filter the corpus at index time.** Cleanest, but you lose genuine voice — the crude messages are part of how the person actually writes.
- **Distinguish input blocks from output blocks in logs.** They have completely different causes and completely different fixes, and conflating them wastes debugging time.

## Caveat

This is a single observation on a single corpus with a single provider, not a controlled study. The mechanism is straightforward enough that it should generalise, but the thresholds involved are provider-specific and undocumented, and the corpus here is unusual — private multilingual messaging rather than the documents most RAG systems index.

Taken as: a thing worth knowing about, not a measured result.

## Proof
<img width="816" height="796" alt="Proof" src="https://github.com/user-attachments/assets/e286b82a-db07-486a-84b4-445eb421468e" />

