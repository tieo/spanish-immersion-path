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

Fixed expressions get cards the same way, as entries with the part of speech EXPR: an
expression whose meaning its words do not give ("echar de menos", "to miss") would
otherwise only show up as a wrong sense on the card of one of its words. They come from
the multi-word Spanish entries of Wiktionary (the extract in KAIKKI_ES, as for
pronominal.py) and data/expressions_extra.json for common ones it lacks. Heard as a run
of the expression's words, a leading verb in any form, in at least MIN_VIDEOS videos
they get an entry, unless a card already has that headword; the translators drop what is
meant literally. build/expressions.json holds how often each video uses them, for the
catalog (units.py).

A new word quotes the cleanest sentence from the first FIRST_VIDEOS videos in watching
order that use it and links the next LINKS videos where it comes back. New words are
appended most widespread first, so the translation batches reach the useful ones first.
The videos read are added to build/pool_videos.json, so the progress page can tell a
video whose words all have cards from one the pool has not read yet. Captions are parsed
with spaCy in several processes; run it where the captions and build/order.json are,
after units.py.
"""

import collections
import gzip
import json
import os
import re
import sys

import spacy
from wordfreq import zipf_frequency

from captions import SKIP_POS, load_chunks, score, snippet
from config import BUILD, DATA, ORDER
from pronominal import KAIKKI
from translate import TRANSLATIONS, headword, load

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
EXPRESSION = re.compile(r"[a-záéíóúüñ]+( [a-záéíóúüñ]+){1,5}")
CLITICS = ("me", "te", "se", "nos", "os")
INFINITIVE = ("ar", "er", "ir", "ír")


def texts(order):
    for v in order:
        chunks = load_chunks(v["id"])
        bounds, text = [], ""
        for i, (_, chunk) in enumerate(chunks):
            bounds.append((len(text), len(text) + len(chunk), i))
            text += chunk + " "
        yield text, (v["id"], bounds)


def expressions():
    """Fixed expressions with their gloss, by dictionary form."""
    found = {}
    with gzip.open(KAIKKI, "rt", encoding="utf-8") as fh:
        for line in fh:
            entry = json.loads(line)
            word = entry.get("word", "")
            if " " not in word or entry.get("pos") in ("name", "num") or not EXPRESSION.fullmatch(word):
                continue
            glosses = [s["glosses"][-1] for s in entry.get("senses", [])
                       if s.get("glosses") and "form-of" not in s.get("tags", [])]
            if glosses:
                found.setdefault(word, glosses[0])
    for item in load(DATA / "expressions_extra.json", []):
        if EXPRESSION.fullmatch(item["expression"]):
            found.setdefault(item["expression"], item["gloss"])
    return found


def patterns(found):
    """Expressions by how their first word is heard: an infinitive in any form, by its
    lemma, everything else as spelled. So is every further word, which keeps "un poco"
    from counting as "unos pocos". A pattern is (expression, reflexive, further words); a
    reflexive expression starts with its verb without the -se, spoken apart in most forms."""
    by_first = collections.defaultdict(list)
    for expr in sorted(found):
        first, *rest = expr.split()
        reflexive = first.endswith("se") and first[:-2].endswith(INFINITIVE)
        pattern = (expr, reflexive, rest)
        by_first[("spelled", first)].append(pattern)
        if reflexive or first.endswith(INFINITIVE):
            by_first[("lemma", first[:-2] if reflexive else first)].append(pattern)
    return by_first


def matches(doc, i, by_first):
    """The expressions starting at token i, as (expression, first token, end token)."""
    tok = doc[i]
    seen = set()
    for key in (("lemma", tok.lemma_.lower()), ("spelled", tok.lower_)):
        for expr, reflexive, rest in by_first.get(key, ()):
            end = i + 1 + len(rest)
            if expr in seen or end > len(doc) or any(doc[i + 1 + k].lower_ != w for k, w in enumerate(rest)):
                continue
            start = i
            if reflexive:
                if i and doc[i - 1].lower_ in CLITICS:
                    start = i - 1
                elif not tok.lower_.endswith(CLITICS):
                    continue
            seen.add(expr)
            yield expr, start, end


def main(processes=1):
    order = json.load(open(ORDER))
    vocab = json.load(open(BUILD / "vocab.json", encoding="utf-8"))
    have = {e["lemma"] for e in vocab}
    known = set(json.load(open(BUILD / "stats.json", encoding="utf-8"))["known_cut_words"])
    nlp = spacy.load("es_core_news_md", disable=["ner"])
    nlp.max_length = 5_000_000
    glosses = expressions()
    by_first = patterns(glosses)
    taken = {head for t in load(TRANSLATIONS, {}).values() if (head := headword(t))}
    per_video = collections.defaultdict(collections.Counter)   # video -> expression -> times

    counts = collections.Counter()
    videos_of = collections.defaultdict(list)          # lemma -> video ids in order
    occ = collections.defaultdict(list)                # (lemma, vid) -> [(vid, chunk, surface)]
    forms = collections.defaultdict(collections.Counter)
    pos_votes = collections.defaultdict(collections.Counter)

    def heard(lemma, vid, chunk, surface):
        """Keeps this occurrence: every one in the first videos, to pick the cleanest
        example, and the first one in each later video, for its link."""
        if not videos_of[lemma] or videos_of[lemma][-1] != vid:
            videos_of[lemma].append(vid)
        n = len(videos_of[lemma])
        if n <= FIRST_VIDEOS or (n <= FIRST_VIDEOS + LINKS and not occ[(lemma, vid)]):
            occ[(lemma, vid)].append((vid, chunk, surface))

    for k, (doc, (vid, bounds)) in enumerate(nlp.pipe(texts(order), as_tuples=True, batch_size=4,
                                                      n_process=int(processes))):
        b = 0
        for tok in doc:
            while b < len(bounds) - 1 and tok.idx >= bounds[b][1]:
                b += 1
            for expr, start, end in matches(doc, tok.i, by_first):
                per_video[vid][expr] += 1
                counts[expr] += 1
                pos_votes[expr]["EXPR"] += 1
                last = doc[end - 1]
                # An example bolds the run inside one caption chunk.
                if doc[start].idx < bounds[b][0]:
                    start = tok.i
                if expr not in have and last.idx + len(last) <= bounds[b][1]:
                    surface = doc[start:end].text
                    forms[expr][surface.lower()] += 1
                    heard(expr, vid, bounds[b][2], surface)
            if not tok.is_alpha:
                continue
            lemma = tok.lemma_.lower()
            counts[lemma] += 1
            pos_votes[lemma][tok.pos_] += 1
            if lemma in have or tok.pos_ in SKIP_POS:
                continue
            forms[lemma][tok.text.lower()] += 1
            heard(lemma, vid, bounds[b][2], tok.text)
        print(f"\r{k + 1}/{len(order)} videos read", end="", file=sys.stderr, flush=True)
    print(file=sys.stderr)

    def candidate(lemma):
        if lemma in glosses:
            return len(videos_of[lemma]) >= MIN_VIDEOS and lemma not in taken
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
            **({"gloss": glosses[lemma]} if lemma in glosses else {}),
        })
    json.dump(vocab, open(BUILD / "vocab.json", "w"), ensure_ascii=False)
    carded = {e["lemma"] for e in vocab if e["pos"] == "EXPR"}
    json.dump({vid: [[e, n] for e, n in used.items() if e in carded] for vid, used in per_video.items()},
              open(BUILD / "expressions.json", "w"), ensure_ascii=False)
    read = BUILD / "pool_videos.json"
    done = set(json.load(open(read))) if read.exists() else set()
    json.dump(sorted(done | {v["id"] for v in order}), open(read, "w"))
    print(f"{len(new)} words added, {len(vocab)} in the pool")


if __name__ == "__main__":
    main(*sys.argv[1:])
