"""Score every immersion video on the CEFR scale and write the order, easy to hard.

The scale is fitted to recordings whose CEFR level is known (graded.py): the official
DELE exam listening tasks and teachers' talks tagged with the level they are meant for.
Nine measures of each recording's speech are fitted to its level (ridge regression on
standardised measures), and the fit scores every video on the same scale; it is then
stretched piecewise so the median recording of each level from A1 to B2 lands on 0
(A1), 1 (A2), 2 (B1) and 3 (B2), the middle of that level on the scale the app shows.
C1 and C2 recordings are too few to anchor, and the scale runs on beyond B2 and below
A1 at the average slope. The measures:
- speaking rate: syllables per second of speech, pauses left out;
- the share of words at each level from A2 to C1, and of words not graded at all, by
  the level at which ELELex, a lexicon of the words in graded textbooks and readers
  per CEFR level (CENTAL, UCLouvain, CC BY-NC-SA 4.0, in build/ELELex.tsv from
  cental.uclouvain.be/cefrlex/elelex), first grades their lemma; one share per level
  rather than one cutoff, so a B2 word weighs more than an A2 one;
- subordinators (que, porque, cuando ... as clause markers) per word;
- share of verbs in a past tense;
- object clitics (lo, le, se ...) per word.
Each is a rate, so a short recording and an hour-long video compare. Pauses are measured
too (pause share, below) but left out of the fit, because a DELE recording's silences are
time left for answers. Dreaming Spanish's own labels (superbeginner to advanced) are not
used for the fit; how well the scale orders them is printed as an outside check.

Speaking rate and pauses are two measures because they are two things for a listener: a
story told fast with long pauses for pictures gives time between sentences, a steady slow
talk without pauses gives none. Both come from the word timings of YouTube's speech
recognition track; a word lasts until the next one starts, but at most its syllables at
the video's own median syllable length plus PAUSE seconds, and the rest of the gap is a
pause. Videos with only a plain transcript get the median of both.

Videos come from data/videos.json, kept when data/classes.json calls them immersion and
they are spoken in Spanish: YouTube's speech-recognition track of the video's own audio
("es-orig") exists only for Spanish audio, while a human Spanish subtitle track alone can
be the translation of an English video. Compilations of other videos are left out.

Output: data/order.json, one row per video in order of score, with its measures.
"""

import json
import random
import re
import statistics
import sys
from collections import defaultdict

import numpy as np
import spacy

import graded
from captions import load_chunks, word_times
from config import BUILD, CAPTIONS, DATA

LEVELS = {"superbeginner": 0, "beginner": 1, "intermediate": 2, "advanced": 3}
MEASURES = ["speaking_sps", "words_a2", "words_b1", "words_b2", "words_c1", "words_unlisted",
            "subordinators", "past", "clitics"]
VARIETY_WORDS = 800
RIDGE = 5.0
ELELEX = BUILD / "ELELex.tsv"
ELELEX_DOCS = 2
UNLISTED = 5
LEVEL_NAMES = ["a1", "a2", "b1", "b2", "c1", "unlisted"]
# Levels whose median recording sets the scale, A1 to B2; C1 and C2 have too few
# recordings to anchor.
ANCHORED = 4
ROWS = BUILD / "level_rows.json"
SHINGLE = 8
BOILERPLATE = 5
REPEAT_SHARE = 0.5
VOWELS = re.compile(r"[aeiouáéíóúü]+")
PAUSE = 0.3
FLUENT_GAP = 1.5


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
    typical = statistics.median(g / n for g, n in zip(gaps, syllables) if 0 < g < FLUENT_GAP)
    speech = sum(min(max(g, 0), n * typical + PAUSE) for g, n in zip(gaps, syllables))
    span = starts[-1] - starts[0]
    return {"speaking_sps": sum(syllables) / speech if speech else None,
            "pause_share": 1 - speech / span if span > 0 else None}


def elelex():
    """The CEFR level of each lemma in ELELex, 0 (A1) to 4 (C1): the lowest level at which
    it occurs in at least ELELEX_DOCS of the graded textbooks and readers, so a word
    a single text happens to use early does not count as early. A lemma under several
    tags takes its lowest level."""
    levels = {}
    with open(ELELEX, encoding="utf-8") as fh:
        head = [h.strip('"') for h in fh.readline().rstrip("\n").split("\t")]
        docs = [head.index(f"nb_doc@{l}") for l in ("a1", "a2", "b1", "b2", "c1")]
        for line in fh:
            cells = [c.strip('"') for c in line.rstrip("\n").split("\t")]
            word = cells[0].lower()
            if "_" in word:
                continue
            level = next((k for k, i in enumerate(docs) if float(cells[i]) >= ELELEX_DOCS), None)
            if level is not None and level < levels.get(word, 5):
                levels[word] = level
    return levels


def word_levels(levels):
    """The share of the words at each ELELex level from A2 up; A1 is the rest, and
    "unlisted" the words ELELex does not grade (rare words, names, misheard words)."""
    n = len(levels) or 1
    return {f"words_{name}": sum(1 for l in levels if l == k) / n
            for k, name in enumerate(LEVEL_NAMES) if k}


def measures(chunks, nlp, graded):
    text = " ".join(c for _, c in chunks)
    doc = nlp(text)
    words = [t for t in doc if t.is_alpha and t.pos_ != "PROPN"]
    n = len(words) or 1
    span = chunks[-1][0] - chunks[0][0]
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


def label(row):
    if row["channel"] != "Dreaming Spanish":
        return None
    m = re.search("|".join(LEVELS), row["title"], re.I)
    return LEVELS[m.group(0).lower()] if m else None


def ridge(X, y):
    A = np.c_[X, np.ones(len(X))]
    penalty = RIDGE * np.eye(A.shape[1])
    penalty[-1, -1] = 0
    return np.linalg.solve(A.T @ A + penalty, A.T @ y)


def predict(X, w):
    return np.c_[X, np.ones(len(X))] @ w


def rank_correlation(a, b):
    return float(np.corrcoef(np.argsort(np.argsort(a)), np.argsort(np.argsort(b)))[0, 1])


def fit(recordings):
    """A function scoring rows on the recordings' level scale (raw, before calibrate), the
    rank correlation between each recording's level and its score from a fit without
    it (leave-one-out), and the weights."""
    X = np.array([[r[k] for k in MEASURES] for r in recordings])
    mean, std = X.mean(0), X.std(0)
    Z = (X - mean) / std
    y = np.array([r["cefr"] for r in recordings], dtype=float)
    held_out = np.array([predict(Z[[i]], ridge(np.delete(Z, i, 0), np.delete(y, i)))[0]
                         for i in range(len(y))])
    w = ridge(Z, y)
    score = lambda rows: predict((np.array([[r[k] for k in MEASURES] for r in rows]) - mean) / std, w)
    return score, rank_correlation(held_out, y), dict(zip(MEASURES, w))


def calibrate(raw, anchors):
    """Regression pulls every score towards the mean; stretch the scale piecewise so
    each anchor (the median raw score of a CEFR level's graded recordings) lands on its
    level, 0 for A1 to 5 for C2. Beyond the outer anchors the scale runs on at the
    average slope across all levels."""
    top = len(anchors) - 1
    out = np.interp(raw, anchors, list(range(len(anchors))))
    slope = top / (anchors[-1] - anchors[0])
    out[raw < anchors[0]] = (raw[raw < anchors[0]] - anchors[0]) * slope
    out[raw > anchors[-1]] = top + (raw[raw > anchors[-1]] - anchors[-1]) * slope
    return out


def recording_rows(nlp, graded_words):
    """The graded recordings measured like the videos."""
    rows = []
    for name, level in graded.recordings().items():
        words, end = graded.load(name)
        rows.append({"name": name, "cefr": level, **speaking((words, end)),
                     **measures([(0, " ".join(w for _, w in words))], nlp, graded_words)})
    return rows


def ngrams(chunks):
    words = re.findall(r"[a-záéíóúüñ]+", " ".join(c for _, c in chunks).lower())
    return {" ".join(words[i:i + SHINGLE]) for i in range(len(words) - SHINGLE + 1)}


def repeats(texts, durations):
    """Videos made of other videos, such as hour-long compilations. Longest first, a video
    goes when most of its distinctive 8-word runs occur in videos still kept; runs that
    many videos share (channel intros and outros) do not count."""
    owners = defaultdict(set)
    for vid, grams in texts.items():
        for g in grams:
            owners[g].add(vid)
    dropped = set()
    for vid in sorted(texts, key=lambda v: -durations[v]):
        own = [g for g in texts[vid] if len(owners[g]) <= BOILERPLATE]
        shared = sum(1 for g in own if len(owners[g] - dropped - {vid}) > 0)
        if own and shared / len(own) > REPEAT_SHARE:
            dropped.add(vid)
    return dropped


def video_rows(nlp, words):
    """Every immersion video spoken in Spanish, measured, without compilations, and what
    was skipped."""
    videos = json.load(open(DATA / "videos.json"))
    kinds = {c["id"]: c["kind"] for c in json.load(open(DATA / "classes.json"))}
    rows, texts, skipped = [], {}, {"lesson": 0, "no Spanish audio": 0, "repeat of other videos": 0}
    for v in videos:
        if kinds.get(v["id"]) != "immersion":
            skipped["lesson"] += 1
            continue
        spoken = (CAPTIONS / f"{v['id']}.es-orig.vtt").exists() or (CAPTIONS / f"{v['id']}.txt").exists()
        chunks = load_chunks(v["id"]) if spoken else []
        if len(chunks) < 10:
            skipped["no Spanish audio"] += 1
            continue
        row = {k: v.get(k) for k in ("id", "title", "channel", "duration")}
        row.update(measures(chunks, nlp, words))
        row.update(speaking(word_times(v["id"])))
        row["label"] = label(row)
        rows.append(row)
        texts[v["id"]] = ngrams(chunks)
        print(f"\r{len(rows)} measured", end="", file=sys.stderr)
    print(file=sys.stderr)
    dropped = repeats(texts, {r["id"]: r["duration"] or 0 for r in rows})
    for r in rows:
        if r["id"] in dropped:
            print("repeat of other videos:", r["title"], file=sys.stderr)
    skipped["repeat of other videos"] = len(dropped)
    rows = [r for r in rows if r["id"] not in dropped]
    # Plain transcripts have no timestamps; they get the median speed and pauses.
    for key in ("wpm", "sps", "speaking_sps", "pause_share"):
        median = statistics.median(r[key] for r in rows if r[key])
        for r in rows:
            r[key] = median if r[key] is None else r[key]
    return rows, skipped


def main():
    """With --cached, the video measures of the last run (build/level_rows.json) are
    reused, for refitting without measuring every video again."""
    nlp = spacy.load("es_core_news_md", disable=["ner"])
    words = elelex()
    if "--cached" in sys.argv:
        rows, skipped = json.load(open(ROWS, encoding="utf-8"))
    else:
        rows, skipped = video_rows(nlp, words)
        json.dump([rows, skipped], open(ROWS, "w"), ensure_ascii=False)
    recordings = recording_rows(nlp, words)
    score, cv, weights = fit(recordings)
    by_level = defaultdict(list)
    for r, v in zip(recordings, score(recordings)):
        by_level[r["cefr"]].append(float(v))
    if any(k not in by_level for k in range(ANCHORED)):
        sys.exit("graded recordings missing for some levels: run graded.py transcribe")
    anchors = [float(np.median(by_level[k])) for k in range(ANCHORED)]
    if anchors != sorted(anchors):
        sys.exit(f"graded levels out of order on the fitted scale: {anchors}")
    scores = calibrate(score(rows), anchors)
    for r, v in zip(rows, scores):
        r["score"] = float(v)
    order = sorted(rows, key=lambda r: r["score"])
    for i, r in enumerate(order, 1):
        r["position"] = i
    json.dump(order, open(DATA / "order.json", "w"), ensure_ascii=False, indent=1)
    print(f"{len(order)} videos in order; skipped {skipped}")
    print(f"{len(recordings)} graded recordings, leave-one-out rank correlation with their "
          f"levels {cv:.3f}")
    print("weights:", {k: round(float(v), 2) for k, v in weights.items()})
    print("recordings per level on the CEFR scale:",
          {graded.LEVELS[k]: [round(float(v), 2) for v in sorted(calibrate(np.array(by_level[k]), anchors))]
           for k in sorted(by_level)})
    labels = np.array([r["label"] if r["label"] is not None else -1 for r in rows])
    known = labels >= 0
    print("outside check, Dreaming Spanish's labels: rank correlation "
          f"{rank_correlation(scores[known], labels[known]):.3f}; median per label",
          {name: round(float(np.median(scores[labels == k])), 2) for name, k in LEVELS.items()})

if __name__ == "__main__":
    main()
