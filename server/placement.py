"""The placement test: which words the learner recognises, and how hard speech they can follow.

Vocabulary: the learner says which of WORDS real words and PSEUDOWORDS made-up ones they
know. The probability of knowing a word is logistic in its Zipf frequency around a
threshold; a "yes" to a word they do not know is a guess at the rate the made-up words
show, so P(yes) = p + (1 - p) * guess. The threshold that makes the answers most likely
is the result (Meara & Buxton 1987; Huibregtse, Admiraal & Meara 2002 for the guessing
correction). More than MAX_GUESS "yes" to made-up words makes the result unreliable.

Listening: the learner hears a clip from a video and types what they understood, CLIPS
times. Each answer scores the share of the clip's words they got, in order. A score of
PASS or more moves the next clip up the level scale by the step, less moves it down, and
the step halves at every change of direction (a staircase). The level is the cut that
best separates the levels passed from the levels failed.
"""

import json
import math
import random
import re
import unicodedata

CLIPS = 8
PASS = 0.6
START_LEVEL = 1.0
START_STEP = 0.75
MIN_STEP = 0.25
MAX_GUESS = 0.3
SLOPE = 2.0


def normal_words(text):
    text = unicodedata.normalize("NFD", text.lower())
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return re.findall(r"[a-zñ]+|\d+", text)


def lcs(a, b):
    prev = [0] * (len(b) + 1)
    for x in a:
        cur = [0]
        for j, y in enumerate(b):
            cur.append(prev[j] + 1 if x == y else max(prev[j + 1], cur[j]))
        prev = cur
    return prev[-1]


class Placement:
    def __init__(self, path):
        data = json.load(open(path))
        self.words = data["words"]
        self.pseudowords = data["pseudowords"]
        self.clips = {c["id"]: c for c in data["clips"]}

    def vocab_items(self):
        items = [{"id": f"w:{w['lemma']}", "text": w["lemma"]} for w in self.words]
        items += [{"id": f"p:{p}", "text": p} for p in self.pseudowords]
        random.shuffle(items)
        return items

    def score_vocab(self, answers):
        """answers: item id -> True when the learner says they know it."""
        zipf = {f"w:{w['lemma']}": w["zipf"] for w in self.words}
        fake = [answers.get(f"p:{p}", False) for p in self.pseudowords]
        guess = (sum(fake) + 0.5) / (len(fake) + 1)
        real = [(zipf[k], v) for k, v in answers.items() if k in zipf]

        def likelihood(threshold):
            total = 0.0
            for z, yes in real:
                p = 1 / (1 + math.exp(-SLOPE * (z - threshold)))
                p_yes = p + (1 - p) * guess
                total += math.log(p_yes if yes else 1 - p_yes)
            return total
        threshold = max((t / 20 for t in range(0, 161)), key=likelihood)
        return {"threshold": threshold, "guess": round(guess, 3), "reliable": guess <= MAX_GUESS}

    def next_clip(self, session):
        """The clip for the staircase's current level, or None when the test is done."""
        if len(session["trials"]) >= CLIPS:
            return None
        used = {t["clip"] for t in session["trials"]}
        clip = min((c for c in self.clips.values() if c["id"] not in used),
                   key=lambda c: abs(c["level"] - session["level"]))
        return {k: clip[k] for k in ("id", "video", "start", "end")}

    def answer(self, session, clip_id, typed):
        clip = self.clips[clip_id]
        ref = normal_words(clip["text"])
        score = lcs(ref, normal_words(typed)) / len(ref) if ref else 0
        passed = score >= PASS
        trials = session["trials"]
        if trials and trials[-1]["passed"] != passed:
            session["step"] = max(MIN_STEP, session["step"] / 2)
        trials.append({"clip": clip_id, "level": clip["level"], "score": round(score, 3), "passed": passed})
        session["level"] += session["step"] if passed else -session["step"]
        return {"score": round(score, 3), "text": clip["text"], "passed": passed}

    @staticmethod
    def new_session():
        return {"level": START_LEVEL, "step": START_STEP, "trials": []}

    @staticmethod
    def listening_level(session):
        """The cut on the level scale that best splits passed (below) from failed (above);
        the middle of the best interval."""
        trials = session["trials"]
        cuts = sorted({t["level"] for t in trials})
        candidates = [cuts[0] - 0.25] + [(a + b) / 2 for a, b in zip(cuts, cuts[1:])] + [cuts[-1] + 0.25]

        def errors(cut):
            return sum(1 for t in trials if t["passed"] != (t["level"] <= cut))
        best = min(errors(c) for c in candidates)
        good = [c for c in candidates if errors(c) == best]
        return round(sum(good) / len(good), 3)
