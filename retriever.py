"""TF-IDF retrieval over your past reply pairs.

Given an incoming message, finds the past exchanges most similar to it, so the
model sees how you answered *this kind* of message rather than 25 random ones.

No numpy or scikit-learn -- pure Python, so the project stays dependency-light.

Why character n-grams as well as words:
    Roman Urdu has no fixed spelling. "kya"/"kia", "hai"/"hy"/"he",
    "kar raha"/"krra" are the same words typed differently. Word matching alone
    misses those. Character 3-grams overlap even when the spelling doesn't, so
    "kya kar rahe ho" still matches "kia krre ho".
"""

import math
import re
from collections import Counter

WORD = re.compile(r"\w+", re.UNICODE)

CHAR_NGRAM = 3
MIN_TOKEN_DF = 1        # ignore tokens seen in fewer documents than this


def tokenize(text):
    """Words plus character 3-grams, so misspellings still overlap."""
    text = text.lower().strip()
    tokens = WORD.findall(text)

    squashed = re.sub(r"\s+", " ", text)
    tokens += [
        squashed[i:i + CHAR_NGRAM]
        for i in range(max(0, len(squashed) - CHAR_NGRAM + 1))
    ]
    return tokens


class TfidfIndex:
    """
    Ranks past `them` messages by similarity to a new one.

    We index the THEM side, not the reply: the question is "when someone said
    something like this before, what did I say back?"
    """

    def __init__(self, pairs):
        self.pairs = pairs
        self.doc_tokens = [tokenize(p["them"]) for p in pairs]

        df = Counter()
        for tokens in self.doc_tokens:
            df.update(set(tokens))

        n = max(1, len(pairs))
        self.idf = {
            t: math.log((n + 1) / (c + 1)) + 1.0
            for t, c in df.items() if c >= MIN_TOKEN_DF
        }

        self.vectors = [self._vector(t) for t in self.doc_tokens]

    def _vector(self, tokens):
        if not tokens:
            return {}, 0.0
        tf = Counter(tokens)
        longest = max(tf.values())
        vec = {}
        for term, count in tf.items():
            idf = self.idf.get(term)
            if idf:
                vec[term] = (count / longest) * idf
        norm = math.sqrt(sum(v * v for v in vec.values()))
        return vec, norm

    def search(self, query, k=15):
        """-> [(pair, score), ...] best first. Zero-score matches are dropped."""
        q_vec, q_norm = self._vector(tokenize(query))
        if not q_vec or q_norm == 0:
            return []

        scored = []
        for i, (vec, norm) in enumerate(self.vectors):
            if norm == 0:
                continue
            # Iterate the shorter vector -- queries are usually much shorter.
            small, large = (q_vec, vec) if len(q_vec) < len(vec) else (vec, q_vec)
            dot = 0.0
            for term, weight in small.items():
                other = large.get(term)
                if other:
                    dot += weight * other
            if dot > 0:
                scored.append((self.pairs[i], dot / (q_norm * norm)))

        scored.sort(key=lambda x: -x[1])
        return scored[:k]


# Building an index costs a pass over the pairs, so keep a few around.
_cache = {}
_CACHE_LIMIT = 8


def get_index(key, pairs):
    cache_key = (key, len(pairs))
    index = _cache.get(cache_key)
    if index is None:
        if len(_cache) >= _CACHE_LIMIT:
            _cache.clear()
        index = TfidfIndex(pairs)
        _cache[cache_key] = index
    return index
