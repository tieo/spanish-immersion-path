"""The word lists of the vocabulary check: a yes/no test of which Spanish words the
learner knows, by frequency band.

The learner sees real words and made-up ones that look Spanish, one at a time, and says
whether they know each. Saying "know" to made-up words shows how much they over-claim,
and the known share of each band is corrected for it (the checklist method of Meara &
Buxton 1987, as in X_Lex). The result calibrates how the app estimates which words of a
video the learner knows (server/state.py).

Real words: the deck's words (build/vocab.json) that are nouns, verbs, adjectives or
adverbs, at least four letters long, by their rank in Spanish (wordfreq), in BANDS.
Made-up words: built from letter sequences of Spanish words (a third-order letter
model over the same words), kept when they are not Spanish words at all: not in
wordfreq's Spanish list, not one of the deck's words, and not within one letter of a
frequent Spanish word, so a misread real word does not count as over-claiming.

Output: data/vocab_check.json, {"bands": [{"label", "from", "to", "zipf", "words": [[word,
zipf], ...]}], "pseudo": [...]}, from which the server draws each check.
"""

import json
import random
import re
import statistics

from wordfreq import top_n_list, zipf_frequency

from config import BUILD, DATA

BANDS = [(0, 500, "top 500"), (500, 1000, "500–1k"), (1000, 2000, "1k–2k"),
         (2000, 4000, "2k–4k"), (4000, 8000, "4k–8k"), (8000, 16000, "8k–16k")]
POS = {"NOUN", "VERB", "ADJ", "ADV"}
PER_BAND = 60
PSEUDO = 200
LETTERS = re.compile(r"^[a-záéíóúüñ]{4,12}$")


def edits1(word):
    """Every string one deletion, substitution, insertion or swap away from word."""
    letters = "abcdefghijklmnopqrstuvwxyzáéíóúüñ"
    splits = [(word[:i], word[i:]) for i in range(len(word) + 1)]
    return ({a + b[1:] for a, b in splits if b}
            | {a + c + b[1:] for a, b in splits if b for c in letters}
            | {a + c + b for a, b in splits for c in letters}
            | {a + b[1] + b[0] + b[2:] for a, b in splits if len(b) > 1})


def main():
    rng = random.Random(7)
    vocab = json.load(open(BUILD / "vocab.json", encoding="utf-8"))
    rank = {w: i for i, w in enumerate(top_n_list("es", 50000))}
    deck = {e["lemma"] for e in vocab}
    bands = []
    for lo, hi, label in BANDS:
        words = sorted({e["lemma"] for e in vocab if e["pos"] in POS and LETTERS.match(e["lemma"])
                        and lo <= rank.get(e["lemma"], 10 ** 9) < hi})
        chosen = rng.sample(words, min(PER_BAND, len(words)))
        bands.append({"label": label, "from": lo, "to": hi,
                      "zipf": round(statistics.median(zipf_frequency(w, "es") for w in chosen), 2),
                      "words": [[w, round(zipf_frequency(w, "es"), 2)] for w in sorted(chosen)]})
        print(f"{label}: {len(words)} candidates, {len(chosen)} kept")

    # Third-order letter model over the deck's content words.
    source = [e["lemma"] for e in vocab if e["pos"] in POS and LETTERS.match(e["lemma"])]
    model = {}
    for w in source:
        padded = "^^" + w + "$"
        for i in range(len(padded) - 2):
            model.setdefault(padded[i:i + 2], []).append(padded[i + 2])
    frequent = set(top_n_list("es", 30000))
    near = set()
    for w in frequent:
        if LETTERS.match(w):
            near |= edits1(w)
    pseudo = set()
    while len(pseudo) < PSEUDO:
        w, ctx = "", "^^"
        while len(w) < 13:
            c = rng.choice(model[ctx])
            if c == "$":
                break
            w, ctx = w + c, ctx[1] + c
        if (5 <= len(w) <= 10 and w not in deck and zipf_frequency(w, "es") == 0
                and w not in near and not any(c in w for c in "áéíóú")):
            pseudo.add(w)
    json.dump({"bands": bands, "pseudo": sorted(pseudo)}, open(DATA / "vocab_check.json", "w"),
              ensure_ascii=False, indent=1)
    print(f"{len(pseudo)} made-up words, e.g. {rng.sample(sorted(pseudo), 12)}")


if __name__ == "__main__":
    main()
