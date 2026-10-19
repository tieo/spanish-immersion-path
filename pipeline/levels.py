"""Score every immersion video on Dreaming Spanish's level scale and write the order, easy to hard.

Dreaming Spanish labels its videos superbeginner, beginner, intermediate or advanced.
Six measures from each video's Spanish captions are fitted to those labels (ridge
regression on standardised measures), and the fit scores every video, labelled or not,
on the same scale, where the median labelled video of each level scores 0 superbeginner,
1 beginner, 2 intermediate or 3 advanced. The measures:
- syllables per second over the span from first to last caption, so pauses count as
  slower speech;
- subordinators (que, porque, cuando ... as clause markers) per word;
- share of verbs in a past tense;
- share of words, by lemma, outside the 3,000 most common Spanish words;
- object clitics (lo, le, se ...) per word;
- distinct lemmas among the first 800 words.
Speed carries most of the weight. Gaps between captions predict the labels too but are
left out: they depend on whether the captions are human-made or speech recognition.

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
from wordfreq import top_n_list

from captions import load_chunks
from config import CAPTIONS, DATA

LEVELS = {"superbeginner": 0, "beginner": 1, "intermediate": 2, "advanced": 3}
MEASURES = ["sps", "subordinators", "past", "rare", "clitics", "variety"]
COMMON = 3000
VARIETY_WORDS = 800
RIDGE = 5.0
SHINGLE = 8
BOILERPLATE = 5
REPEAT_SHARE = 0.5
VOWELS = re.compile(r"[aeiouáéíóúü]+")


def measures(chunks, nlp, common):
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
        "rare": sum(1 for t in words if t.lemma_.lower() not in common) / n,
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


def fit(rows):
    """Scores on the label scale, and the rank correlation with the labels of a
    five-fold cross-validation, where each video is scored by a fit without it."""
    X = np.array([[r[k] for k in MEASURES] for r in rows])
    Z = (X - X.mean(0)) / X.std(0)
    y = np.array([r["label"] if r["label"] is not None else -1 for r in rows], dtype=float)
    labelled = list(np.where(y >= 0)[0])
    random.Random(1).shuffle(labelled)
    held_out = np.zeros(len(rows))
    for k in range(5):
        test = labelled[k::5]
        train = sorted(set(labelled) - set(test))
        held_out[test] = predict(Z[test], ridge(Z[train], y[train]))
    w = ridge(Z[labelled], y[labelled])
    raw = predict(Z, w)
    return calibrate(raw, y), rank_correlation(held_out[labelled], y[labelled]), dict(zip(MEASURES, w))


def calibrate(raw, y):
    """Regression pulls every score towards the mean; stretch the scale piecewise so the
    median video of each label lands on that label's level. Beyond the outer medians the
    scale runs on at the average slope across all levels, because superbeginner and
    beginner videos differ little in their captions and their steep piece would throw
    the easiest videos far below the scale."""
    anchors = [float(np.median(raw[y == k])) for k in range(len(LEVELS))]
    top = len(LEVELS) - 1
    out = np.interp(raw, anchors, list(range(len(LEVELS))))
    slope = top / (anchors[-1] - anchors[0])
    out[raw < anchors[0]] = (raw[raw < anchors[0]] - anchors[0]) * slope
    out[raw > anchors[-1]] = top + (raw[raw > anchors[-1]] - anchors[-1]) * slope
    return out


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


def main():
    videos = json.load(open(DATA / "videos.json"))
    kinds = {c["id"]: c["kind"] for c in json.load(open(DATA / "classes.json"))}
    nlp = spacy.load("es_core_news_md", disable=["ner"])
    common = set(top_n_list("es", COMMON))
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
        row.update(measures(chunks, nlp, common))
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
    # Plain transcripts have no timestamps; they get the median speed.
    for key in ("wpm", "sps"):
        median = statistics.median(r[key] for r in rows if r[key])
        for r in rows:
            r[key] = r[key] or median
    scores, cv, weights = fit(rows)
    for r, s in zip(rows, scores):
        r["score"] = float(s)
    order = sorted(rows, key=lambda r: r["score"])
    for i, r in enumerate(order, 1):
        r["position"] = i
    json.dump(order, open(DATA / "order.json", "w"), ensure_ascii=False, indent=1)
    print(f"{len(order)} videos in order; skipped {skipped}")
    print(f"{sum(r['label'] is not None for r in rows)} labelled, cross-validated rank "
          f"correlation with the labels {cv:.3f}")
    print("weights:", {k: round(float(v), 2) for k, v in weights.items()})


if __name__ == "__main__":
    main()
