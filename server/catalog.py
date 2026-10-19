"""The units to choose from, read from data/units.json (pipeline/units.py)."""

import json
import math
from dataclasses import dataclass, field


CEFR = ["A1", "A2", "B1", "B2", "C1", "C2"]
BAND_START = -0.5


def cefr(score):
    """The score on the CEFR scale with Instituto Cervantes' half-level steps (A1.1, A1.2):
    the typical superbeginner, beginner, intermediate and advanced video (0, 1, 2, 3)
    sits in the middle of A1, A2, B1 and B2. The same mapping is in static/index.html."""
    if score < BAND_START:
        return "Pre-A1"
    x = score - BAND_START
    band = int(x)
    if band >= 5:
        return "C2"
    return f"{CEFR[band]}.{1 if x - band < 0.5 else 2}"


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
    lemmas: list = field(repr=False)

    def public(self):
        return {k: getattr(self, k) for k in
                ("id", "kind", "title", "channel", "series", "duration", "level", "audio")}


class Catalog:
    def __init__(self, path):
        data = json.load(open(path))
        self.lemmas = data["lemmas"]
        self.units = [Unit(**{k: u[k] for k in Unit.__dataclass_fields__}) for u in data["units"]]
        self.by_id = {u.id: u for u in self.units}
        self.note_lemma = {l["note"]: i for i, l in enumerate(self.lemmas) if l["note"]}

    def coverage(self, unit, known):
        """Expected share of the unit's spoken words the learner knows, given a
        probability of knowing each lemma."""
        return sum(n * known(i) for i, n in unit.lemmas) / unit.words

    def new_words(self, unit, known, taken, limit):
        """Words of the unit worth a card: they have a note, the learner probably does
        not know them and no earlier unit introduced them. Most useful first: frequent
        in Spanish, then frequent in this unit, where the card's word is heard most."""
        found = [(self.lemmas[i]["zipf"] + math.log(n), self.lemmas[i]["note"])
                 for i, n in unit.lemmas
                 if self.lemmas[i]["note"] and self.lemmas[i]["note"] not in taken and known(i) < 0.5]
        return [note for _, note in sorted(found, reverse=True)[:limit]]
