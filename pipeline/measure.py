"""Measure every immersion video once, for levels.py and units.py.

  python measure.py [processes]

Each immersion video with Spanish captions (see levels.py for which count) is parsed with
spaCy once, and what both later steps need is kept in build/measured.jsonl, one line per
video: the text measures of the level fit, speaking rate and pauses, how often each
lemma is spoken (for the app's word coverage), and a sample of its 8-word runs (for
finding compilations). A rerun measures only the videos not in the file yet, so new
captions cost only their own parsing; the parsing runs in several processes.

Text measures and lemmas leave out the captions' bracketed sound tags ([música]), which
are not speech. A video whose captions hold fewer than MIN_CHUNKS chunks is kept as
skipped, so it is not parsed again.
"""

import hashlib
import json
import re
import statistics
import sys

import spacy

from captions import load_chunks, speech, word_times
from config import BUILD, CAPTIONS, DATA

CACHE = BUILD / "measured.jsonl"
MIN_CHUNKS = 10
SHINGLE = 8
# One in SAMPLE 8-word runs is kept, chosen by hash so every video keeps the same ones:
# enough to see that a compilation repeats other videos, at a quarter of the size.
SAMPLE = 4
VARIETY_WORDS = 800
VOWELS = re.compile(r"[aeiouáéíóúü]+")
UNLISTED = 5
LEVEL_NAMES = ["a1", "a2", "b1", "b2", "c1", "unlisted"]
PAUSE = 0.3
FLUENT_GAP = 1.5


def load():
    """The measured videos by id."""
    try:
        with open(CACHE, encoding="utf-8") as fh:
            return {r["id"]: r for r in map(json.loads, fh)}
    except FileNotFoundError:
        return {}


def syllable_count(word):
    return max(1, len(VOWELS.findall(word.lower())))


def speaking(timed):
    """Speaking rate (syllables per second of speech) and pause share from [(start, word)]
    and the end of the last word, or Nones without word timings."""
    if not timed or len(timed[0]) < 10:
        return {"speaking_sps": None, "pause_share": None}
    words, end = timed
    syllables = [syllable_count(w) for _, w in words]
    starts = [t for t, _ in words] + [end]
    gaps = [b - a for a, b in zip(starts, starts[1:])]
    fluent = [g / n for g, n in zip(gaps, syllables) if 0 < g < FLUENT_GAP]
    if not fluent:
        return {"speaking_sps": None, "pause_share": None}
    typical = statistics.median(fluent)
    speech_time = sum(min(max(g, 0), n * typical + PAUSE) for g, n in zip(gaps, syllables))
    span = starts[-1] - starts[0]
    return {"speaking_sps": sum(syllables) / speech_time if speech_time else None,
            "pause_share": 1 - speech_time / span if span > 0 else None}


def word_levels(levels):
    """The share of the words at each ELELex level from A2 up; A1 is the rest, and
    "unlisted" the words ELELex does not grade (rare words, names, misheard words)."""
    n = len(levels) or 1
    return {f"words_{name}": sum(1 for l in levels if l == k) / n
            for k, name in enumerate(LEVEL_NAMES) if k}


def measures(doc, span, graded):
    """The text measures of a parsed text spoken over span seconds; graded maps a lemma
    to its ELELex level (levels.elelex)."""
    words = [t for t in doc if t.is_alpha and t.pos_ != "PROPN"]
    n = len(words) or 1
    syllables = sum(len(VOWELS.findall(t.text.lower())) for t in words)
    verbs = [t.morph.to_dict() for t in doc if t.pos_ in ("VERB", "AUX")]
    return {
        "wpm": n / (span / 60) if span > 0 else None,
        "sps": syllables / span if span > 0 else None,
        "subordinators": sum(1 for t in doc if t.dep_ == "mark") / n,
        "past": sum(1 for m in verbs if m.get("Tense") == "Past") / (len(verbs) or 1),
        **word_levels([graded.get(t.lemma_.lower(), UNLISTED) for t in words]),
        "clitics": sum(1 for t in doc if t.pos_ == "PRON"
                       and t.morph.to_dict().get("Case") in ("Acc", "Dat")) / n,
        "variety": len({t.lemma_.lower() for t in words[:VARIETY_WORDS]}) / max(1, min(VARIETY_WORDS, n)),
    }


def lemma_counts(doc):
    counts = {}
    for t in doc:
        if t.is_alpha and t.pos_ != "PROPN":
            lemma = t.lemma_.lower()
            counts[lemma] = counts.get(lemma, 0) + 1
    return sorted(counts.items())


def shingles(text):
    words = re.findall(r"[a-záéíóúüñ]+", text.lower())
    out = set()
    for i in range(len(words) - SHINGLE + 1):
        h = int.from_bytes(hashlib.blake2b(" ".join(words[i:i + SHINGLE]).encode(), digest_size=8).digest(), "big")
        if h % SAMPLE == 0:
            out.add(h >> 11)  # 53 bits, exact as a JSON number
    return sorted(out)


def spoken(vid):
    return (CAPTIONS / f"{vid}.es-orig.vtt").exists() or (CAPTIONS / f"{vid}.txt").exists()


def main(processes=1):
    from levels import elelex
    graded = elelex()
    done = load()
    kinds = {c["id"]: c["kind"] for c in json.load(open(DATA / "classes.json"))}
    todo = [v["id"] for v in json.load(open(DATA / "videos.json"))
            if kinds.get(v["id"]) == "immersion" and v["id"] not in done and spoken(v["id"])]
    print(f"{len(todo)} videos to measure, {len(done)} measured before", file=sys.stderr)
    nlp = spacy.load("es_core_news_md", disable=["ner"])
    nlp.max_length = 5_000_000

    def texts():
        for vid in todo:
            chunks = load_chunks(vid)
            text = " ".join(speech(" ".join(c for _, c in chunks).split()))
            yield text, (vid, len(chunks), chunks[-1][0] - chunks[0][0] if chunks else 0)

    with open(CACHE, "a", encoding="utf-8") as out:
        for k, (doc, (vid, n, span)) in enumerate(nlp.pipe(texts(), as_tuples=True, batch_size=4,
                                                           n_process=int(processes))):
            if n < MIN_CHUNKS:
                row = {"id": vid, "skip": "no Spanish audio"}
            else:
                row = {"id": vid, **measures(doc, span, graded), **speaking(word_times(vid)),
                       "lemmas": lemma_counts(doc), "shingles": shingles(doc.text)}
            out.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
            if k % 100 == 0:
                out.flush()
            print(f"\r{k + 1}/{len(todo)} measured", end="", file=sys.stderr)
    print(file=sys.stderr)


if __name__ == "__main__":
    main(*sys.argv[1:])
