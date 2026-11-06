"""The card pool: every word of the path worth a card, for the app to hand out.

  python pool.py [processes]

The app introduces a video's words the learner probably does not know as they watch it
(server/picker.py), so a word needs a card before any video can introduce it. This adds
to build/vocab.json every word heard in the measured videos that has none yet; the
entries already there stay exactly as they are, since their translations, recordings and
the learner's notes and scheduling hang on them.

A word is worth a card when it is heard in at least MIN_VIDEOS videos (or is common
Spanish, Zipf >= SINGLE_VIDEO_ZIPF), is listed in Spanish frequency lists (Zipf >=
MIN_ZIPF) unless WIDESPREAD videos use it, is not tagged as a name, number or
interjection, is not among the core words every learner starts with (stats.json) and
reads more like Spanish than English. Speech recognition and the tagger still let
through some noise; the translators drop what is no real word (TRANSLATE.md).

A new word quotes the cleanest sentence from the first FIRST_VIDEOS videos in watching
order that use it and links the next LINKS videos where it comes back. New words are
appended most widespread first, so the translation batches reach the useful ones first.
Captions are parsed with spaCy in several processes; run it where the captions and
build/order.json are, after units.py.
"""

import collections
import json
import re
import sys

import spacy
from wordfreq import zipf_frequency

from captions import SKIP_POS, load_chunks, score, snippet
from config import BUILD, ORDER

MIN_VIDEOS = 3
SINGLE_VIDEO_ZIPF = 3.0
MIN_ZIPF = 1.0
WIDESPREAD = 20
FIRST_VIDEOS = 3
# Further examples per word. AnkiWeb syncs a collection of up to 250 MB without its
# recordings, and the further examples are most of a note's text.
LINKS = 10
# A 5-word run heard in this many videos is a channel's stock phrase (intro, outro).
STOCK_VIDEOS = 4


def texts(order):
    for v in order:
        chunks = load_chunks(v["id"])
        bounds, text = [], ""
        for i, (_, chunk) in enumerate(chunks):
            bounds.append((len(text), len(text) + len(chunk), i))
            text += chunk + " "
        yield text, (v["id"], bounds)


def main(processes=1):
    order = json.load(open(ORDER))
    vocab = json.load(open(BUILD / "vocab.json", encoding="utf-8"))
    have = {e["lemma"] for e in vocab}
    known = set(json.load(open(BUILD / "stats.json", encoding="utf-8"))["known_cut_words"])
    nlp = spacy.load("es_core_news_md", disable=["ner"])
    nlp.max_length = 5_000_000

    counts = collections.Counter()
    videos_of = collections.defaultdict(list)          # lemma -> video ids in order
    occ = collections.defaultdict(list)                # (lemma, vid) -> [(vid, chunk, surface)]
    forms = collections.defaultdict(collections.Counter)
    pos_votes = collections.defaultdict(collections.Counter)
    for k, (doc, (vid, bounds)) in enumerate(nlp.pipe(texts(order), as_tuples=True, batch_size=4,
                                                      n_process=int(processes))):
        b = 0
        for tok in doc:
            while b < len(bounds) - 1 and tok.idx >= bounds[b][1]:
                b += 1
            if not tok.is_alpha:
                continue
            lemma = tok.lemma_.lower()
            counts[lemma] += 1
            pos_votes[lemma][tok.pos_] += 1
            if lemma in have or tok.pos_ in SKIP_POS:
                continue
            forms[lemma][tok.text.lower()] += 1
            if not videos_of[lemma] or videos_of[lemma][-1] != vid:
                videos_of[lemma].append(vid)
            # Every occurrence in the first videos, to pick the cleanest example; the
            # first one in each later video, for its link.
            n = len(videos_of[lemma])
            if n <= FIRST_VIDEOS or (n <= FIRST_VIDEOS + LINKS and not occ[(lemma, vid)]):
                occ[(lemma, vid)].append((vid, bounds[b][2], tok.text))
        print(f"\r{k + 1}/{len(order)} videos read", end="", file=sys.stderr, flush=True)
    print(file=sys.stderr)

    def candidate(lemma):
        if lemma in known or not lemma.isalpha():
            return False
        n, zipf = len(videos_of[lemma]), zipf_frequency(lemma, "es")
        if n < MIN_VIDEOS and zipf < SINGLE_VIDEO_ZIPF:
            return False
        if zipf < MIN_ZIPF and n < WIDESPREAD:
            return False
        if pos_votes[lemma].most_common(1)[0][0] in SKIP_POS:
            return False
        # English fillers the speakers drop in read as Spanish to the tagger.
        return zipf_frequency(lemma, "en") <= zipf + 1.5

    position = {v["id"]: v["position"] for v in order}
    titles = {v["id"]: v["title"] for v in order}
    new = sorted((l for l in videos_of if candidate(l)),
                 key=lambda l: (-len(videos_of[l]), -zipf_frequency(l, "es")))
    cache, options = {}, {}
    for i, lemma in enumerate(new):
        options[lemma] = [snippet(o, cache) + (o[0],)
                          for vid in videos_of[lemma][:FIRST_VIDEOS] for o in occ[(lemma, vid)]]
        # Captions are loaded per example; keeping them all would hold every video.
        if len(cache) > 200:
            cache.clear()
        print(f"\r{i + 1}/{len(new)} words' examples cut", end="", file=sys.stderr, flush=True)
    print(file=sys.stderr)

    # A channel's stock phrases (intro, outro) make poor examples: a 5-word run of an
    # example heard in STOCK_VIDEOS videos is one. Only the runs of the examples are
    # counted, in one more read of the captions.
    def runs(text):
        w = re.sub(r"<[^>]+>", "", text).lower().split()
        return {" ".join(w[i:i + 5]) for i in range(len(w) - 4)}

    seen = collections.Counter({g: 0 for opts in options.values() for text, _, _ in opts for g in runs(text)})
    for v in order:
        for g in runs(" ".join(c for _, c in load_chunks(v["id"]))):
            if g in seen:
                seen[g] += 1

    def is_stock(text):
        return any(seen[g] >= STOCK_VIDEOS for g in runs(text))

    for lemma in new:
        example, start, vid = max(options[lemma], key=lambda c: score(c[0]) * (0.3 if is_stock(c[0]) else 1))
        more = []
        for w in [w for w in videos_of[lemma] if w != vid][:LINKS]:
            text, at = snippet(occ[(lemma, w)][0], cache)
            if len(cache) > 200:
                cache.clear()
            more.append({"example_es": text, "video": w, "start": at, "episode_title": titles[w],
                         "episode_number": position[w], "watch_position": position[w]})
        vocab.append({
            "lemma": lemma, "pos": pos_votes[lemma].most_common(1)[0][0],
            "count": counts[lemma], "episodes": len(videos_of[lemma]),
            "forms": [f for f, _ in forms[lemma].most_common(4)],
            "example_es": example, "video": vid, "start": start,
            "episode_title": titles[vid], "episode_number": position[vid],
            "watch_position": position[vid], "more": more,
            "all_positions": sorted(position[w] for w in videos_of[lemma]),
        })
    json.dump(vocab, open(BUILD / "vocab.json", "w"), ensure_ascii=False)
    print(f"{len(new)} words added, {len(vocab)} in the pool")


if __name__ == "__main__":
    main(*sys.argv[1:])
