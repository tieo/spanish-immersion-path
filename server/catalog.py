"""The units to choose from, read from the catalog pipeline/units.py builds."""

import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np


CEFR = ["A1", "A2", "B1", "B2", "C1", "C2"]
BAND_START = -0.5


def cefr(score):
    """The score on the CEFR scale with Instituto Cervantes' half-level steps (A1.1, A1.2):
    scores 0 to 5 are the middle of A1 to C2, where the median DELE listening recording of
    each level sits (pipeline/levels.py). The same mapping is in static/index.html."""
    if score < BAND_START:
        return "Pre-A1"
    x = score - BAND_START
    band = int(x)
    if band >= 5:
        return "C2"
    return f"{CEFR[band]}.{1 if x - band < 0.5 else 2}"


def score_of(code):
    """The middle of a CEFR level on the score scale: "B1.2", "B1", "Pre-A1", "C2"."""
    m = re.fullmatch(r"\s*(pre-?a1|[abc][12])(?:\.([12]))?\s*", code or "", re.I)
    if not m:
        return None
    name = m.group(1).upper()
    if name.startswith("PRE"):
        return BAND_START - 0.25
    band = CEFR.index(name)
    if name == "C2":
        return BAND_START + band + 0.25
    half = m.group(2)
    return BAND_START + band + (0.25 if half == "1" else 0.75 if half == "2" else 0.5)


@dataclass
class Unit:
    id: str
    kind: str
    title: str
    channel: str
    series: str
    duration: int
    level: float
    audio: bool
    words: int
    row: int = field(repr=False)
    topic: str = None

    def public(self):
        return {k: getattr(self, k) for k in
                ("id", "kind", "title", "channel", "series", "duration", "level", "audio", "topic")}


class Catalog:
    """The units of build/catalog.npz (pipeline/units.py), read again whenever the file
    changes, so a newly published catalog takes effect without a restart."""

    def __init__(self, path):
        self.path = Path(path)
        self.mtime = None
        self.refresh()

    def refresh(self):
        mtime = self.path.stat().st_mtime_ns
        if mtime == self.mtime:
            return
        with np.load(self.path) as z:
            meta = json.loads(z["meta"].tobytes())
            # 32-bit indices and counts: the catalog holds tens of millions of
            # (lemma, count) entries, and a newly published one is read while the old
            # one still serves.
            offsets = z["offsets"]
            lemma = z["lemma"].astype(np.int32, copy=False)
            count = z["count"].astype(np.float32, copy=False)
        lemmas = meta.pop("lemmas")
        units = [Unit(row=k, **{f: u[f] for f in Unit.__dataclass_fields__ if f in u})
                 for k, u in enumerate(meta["units"])]
        note = [l["note"] for l in lemmas]
        zipf = np.array([l["zipf"] for l in lemmas], dtype=np.float32)
        # Fixed expressions have spaces; their words are counted already.
        single = np.array([" " not in l["lemma"] for l in lemmas])
        del lemmas
        self.__dict__.update(
            mtime=mtime, note=note, single=single, units=units, by_id={u.id: u for u in units},
            # The easiest unit's level: where the scale starts below A1, for showing how
            # far a learner below A1 has come.
            floor=min(u.level for u in units),
            note_lemma={n: i for i, n in enumerate(note) if n},
            zipf=zipf,
            has_note=np.array([n is not None for n in note]),
            offsets=offsets, lemma=lemma, count=count,
            # The unit each (lemma, count) entry belongs to, for sums per unit.
            unit_of=np.repeat(np.arange(len(units), dtype=np.int32), np.diff(offsets)),
            words=np.array([max(u.words, 1) for u in units], dtype=np.float64))

    def coverages(self, known):
        """Expected share of each unit's spoken words the learner knows, by unit row,
        given the probability of knowing each lemma (an array by lemma index)."""
        return np.bincount(self.unit_of, weights=self.count * known[self.lemma] * self.single[self.lemma],
                           minlength=len(self.units)) / self.words

    def coverage(self, unit, known):
        a, b = self.offsets[unit.row], self.offsets[unit.row + 1]
        ids = self.lemma[a:b]
        return float(self.count[a:b] @ (known[ids] * self.single[ids])) / max(unit.words, 1)

    def new_counts(self, known, taken):
        """How many words worth a card (see new_words) each unit holds, by unit row."""
        open_note = self.has_note & (known < 0.5)
        for n in taken:
            if n in self.note_lemma:
                open_note[self.note_lemma[n]] = False
        return np.bincount(self.unit_of, weights=open_note[self.lemma], minlength=len(self.units))

    def new_words(self, unit, known, taken, limit):
        """Words of the unit worth a card: they have a note, the learner probably does
        not know them and no earlier unit introduced them. Most useful first: frequent
        in Spanish, then frequent in this unit, where the card's word is heard most."""
        a, b = self.offsets[unit.row], self.offsets[unit.row + 1]
        found = [(float(self.zipf[i]) + math.log(n), self.note[i])
                 for i, n in zip(self.lemma[a:b].tolist(), self.count[a:b].tolist())
                 if self.note[i] and self.note[i] not in taken and known[i] < 0.5]
        return [note for _, note in sorted(found, reverse=True)[:limit]]
