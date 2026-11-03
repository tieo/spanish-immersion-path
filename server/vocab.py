"""The vocabulary check: which Spanish words the learner knows, by frequency band.

A check shows PER_BAND real words from each band of data/vocab_check.json and PSEUDO
made-up ones, shuffled; the learner says "know" or "don't know" to each. The share of
"know" on made-up words (false alarms) shows how much they over-claim, and each band's
share of "know" on real words is corrected for it the usual way for yes/no tests,
(hits - false alarms) / (1 - false alarms) (Meara & Buxton 1987; Huibregtse, Admiraal &
Meara 2002). A logistic curve in a word's Zipf frequency is fitted to the answers word by
word, with the false alarm rate in it, and it is what the app takes as the probability
of knowing any word (state.Store.known).
A check with half or more of the made-up words claimed tells nothing and changes
nothing.
"""

import json
import math
import random

PER_BAND = 15
PSEUDO = 30
# A check is offered again after this many days, so the estimate keeps up.
EVERY_DAYS = 28
UNRELIABLE = 0.5


class Check:
    def __init__(self, path):
        data = json.load(open(path, encoding="utf-8"))
        self.bands = data["bands"]
        self.pseudo = data["pseudo"]

    def draw(self, rng=random):
        items = [{"word": w, "zipf": z, "band": k} for k, b in enumerate(self.bands)
                 for w, z in rng.sample(b["words"], PER_BAND)]
        items += [{"word": w, "band": None} for w in rng.sample(self.pseudo, PSEUDO)]
        rng.shuffle(items)
        return items

    def score(self, answers):
        """The result of a check from [{word, zipf, band, known}], band None for made-up
        words: corrected known share per band, false alarm rate, the fitted curve and an
        estimate of how many words the learner knows from it, both None when the check is
        unreliable."""
        fake = [a["known"] for a in answers if a["band"] is None]
        false_alarm = sum(fake) / len(fake) if fake else 0.0
        bands = []
        for k, b in enumerate(self.bands):
            said = [a["known"] for a in answers if a["band"] == k]
            if not said:
                continue
            hit = sum(said) / len(said)
            known = max(0.0, (hit - false_alarm) / (1 - false_alarm)) if false_alarm < 1 else 0.0
            bands.append({"label": b["label"], "zipf": b["zipf"], "known": round(known, 3),
                          "size": b["to"] - b["from"]})
        real = [(a["zipf"], a["known"]) for a in answers if a["band"] is not None]
        curve = fit(real, false_alarm) if false_alarm < UNRELIABLE and real else None
        # Words known among the 16,000 most frequent: each band's size times the curve's
        # mean over all the band's listed words, steadier than fifteen answers a band.
        words = round(sum((b["to"] - b["from"]) * sum(chance(z, curve) for _, z in b["words"]) / len(b["words"])
                          for b in self.bands)) if curve else None
        return {"bands": bands, "false_alarm": round(false_alarm, 3),
                "pseudo": len(fake), "pseudo_known": sum(fake), "words": words, "curve": curve}


def chance(zipf, curve):
    return 1 / (1 + math.exp(-curve["slope"] * (zipf - curve["threshold"])))


def fit(answers, false_alarm):
    """Threshold and slope of the logistic curve in Zipf frequency that makes the
    answers most likely (maximum likelihood over a grid). A learner says "know" to a
    word they know, and to one they do not at the false alarm rate:
    P(know) = p + (1 - p) * false_alarm, p the curve at the word's frequency. The slope
    stays within what learners' curves show, so fifteen words a band cannot make it a step."""
    best = None
    for t in range(150, 751, 5):
        threshold = t / 100
        for s in range(5, 41):
            slope = s / 10
            ll = 0.0
            for zipf, known in answers:
                p = 1 / (1 + math.exp(-slope * (zipf - threshold)))
                say = min(1 - 1e-6, max(1e-6, p + (1 - p) * false_alarm))
                ll += math.log(say if known else 1 - say)
            if best is None or ll > best[0]:
                best = (ll, threshold, slope)
    return {"threshold": best[1], "slope": best[2]}
