"""Material for the placement test: words to recognise and clips to write down.

Input: data/units.json (from units.py) and the videos' Spanish captions.
Output: build/placement.json, kept out of the repository because the clips carry caption
text; the server reads it from its state directory.

- "words": real Spanish lemmas in frequency bands of half a Zipf step from 7 (the most
  common words) down to 2.5, WORDS_PER_BAND each. Words spelled the same in English or
  German are left out, since recognising them says nothing about Spanish.
- "pseudowords": made-up words built from the letter sequences of real Spanish words,
  kept only when no word list (Spanish, English, German, French, Italian, Portuguese)
  knows them. Saying "yes" to one is a guess, which the scoring corrects for (Meara &
  Buxton 1987; Huibregtse, Admiraal & Meara 2002).
- "clips": stretches of speech of CLIP_SECONDS from videos across the level scale,
  CLIPS_PER_LEVEL per quarter level, each with its start, end and caption text. The test
  plays them embedded, so only videos whose owner allows embedding qualify. The
  learner types what they hear; how much of it they get right at which level places
  them on the path. Lines that recur across a channel's videos (greetings, promos) are
  left out.
"""

import json
from collections import Counter
import random
import re
import urllib.error
import urllib.request

from wordfreq import zipf_frequency

from captions import load_chunks
from config import BUILD, DATA

WORDS_PER_BAND = 5
PSEUDOWORDS = 16
CLIP_SECONDS = (8, 14)
CLIP_WORDS = (10, 40)
CLIPS_PER_LEVEL = 4
LEVEL_GRID = [x / 4 for x in range(-4, 17)]
SKIP_SECONDS = 45
STOCK_VIDEOS = 4
LANGS = ("es", "en", "de", "fr", "it", "pt")


def words(lemmas, rng):
    out = []
    for k in range(10):
        hi = 7 - k / 2
        band = [l["lemma"] for l in lemmas
                if hi - 0.5 < l["zipf"] <= hi and l["note"] and len(l["lemma"]) > 2
                and zipf_frequency(l["lemma"], "en") < 2 and zipf_frequency(l["lemma"], "de") < 2]
        out += [{"lemma": w, "zipf": round(zipf_frequency(w, "es"), 2)}
                for w in rng.sample(band, min(WORDS_PER_BAND, len(band)))]
    return out


def pseudowords(lemmas, rng):
    """Letter trigrams of common Spanish words, chained into new words of 5 to 9 letters."""
    source = [l["lemma"] for l in lemmas
              if l["zipf"] >= 3 and 5 <= len(l["lemma"]) <= 9 and l["lemma"].isalpha()]
    nxt = {}
    for w in source:
        w = f"^^{w}$"
        for i in range(len(w) - 2):
            nxt.setdefault(w[i:i + 2], []).append(w[i + 2])
    real = {l["lemma"] for l in lemmas}
    out = set()
    while len(out) < PSEUDOWORDS:
        w = "^^"
        while not w.endswith("$") and len(w) < 14:
            w += rng.choice(nxt[w[-2:]])
        w = w.strip("^$")
        if 5 <= len(w) <= 9 and w not in real and all(zipf_frequency(w, lang) == 0 for lang in LANGS):
            out.add(w)
    return sorted(out)


def five_grams(text):
    w = re.findall(r"\w+", text.lower())
    return {" ".join(w[i:i + 5]) for i in range(len(w) - 4)}


def clip(chunks, stock, rng):
    """A stretch of whole caption lines from the middle of the video, without the
    channel's recurring lines (greetings, promos)."""
    starts = [i for i, (t, _) in enumerate(chunks) if t > SKIP_SECONDS and t < chunks[-1][0] - SKIP_SECONDS]
    rng.shuffle(starts)
    for i in starts:
        for j in range(i + 1, len(chunks)):
            length = chunks[j][0] - chunks[i][0]
            if length > CLIP_SECONDS[1]:
                break
            text = " ".join(c for _, c in chunks[i:j])
            n = len(re.findall(r"\w+", text))
            if (length >= CLIP_SECONDS[0] and CLIP_WORDS[0] <= n <= CLIP_WORDS[1]
                    and not five_grams(text) & stock):
                return {"start": round(chunks[i][0], 2), "end": round(chunks[j][0], 2), "text": text}
    return None


def embeddable(video, cache):
    """Whether the owner lets the video play on other sites; Dreaming Spanish does not."""
    if video not in cache:
        url = f"https://www.youtube.com/oembed?format=json&url=https://www.youtube.com/watch?v={video}"
        try:
            urllib.request.urlopen(url, timeout=10)
            cache[video] = True
        except urllib.error.HTTPError:
            cache[video] = False
    return cache[video]


def main():
    rng = random.Random(7)
    catalog = json.load(open(DATA / "units.json"))
    lemmas, units = catalog["lemmas"], catalog["units"]
    chunks = {u["id"]: load_chunks(u["id"]) for u in units}
    seen = Counter(g for c in chunks.values() for g in five_grams(" ".join(t for _, t in c)))
    stock = {g for g, n in seen.items() if n >= STOCK_VIDEOS}
    cache_path = BUILD / "embeddable.json"
    cache = json.load(open(cache_path)) if cache_path.exists() else {}
    clips, used = [], set()
    for level in LEVEL_GRID:
        near = sorted((u for u in units if u["id"] not in used), key=lambda u: abs(u["level"] - level))
        found = 0
        for u in near[:CLIPS_PER_LEVEL * 6]:
            if not embeddable(u["id"], cache):
                continue
            c = clip(chunks[u["id"]], stock, rng)
            if c:
                used.add(u["id"])
                clips.append({"id": f"{u['id']}@{int(c['start'])}", "video": u["id"],
                              "level": u["level"], **c})
                found += 1
                if found == CLIPS_PER_LEVEL:
                    break
    json.dump(cache, open(cache_path, "w"))
    out = {"words": words(lemmas, rng), "pseudowords": pseudowords(lemmas, rng), "clips": clips}
    json.dump(out, open(BUILD / "placement.json", "w"), ensure_ascii=False, indent=1)
    print(f"{len(out['words'])} words, {len(out['pseudowords'])} pseudowords, {len(clips)} clips")


if __name__ == "__main__":
    main()
