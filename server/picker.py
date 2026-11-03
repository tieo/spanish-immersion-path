"""Which unit comes next, for the learner's level, what they have done and the mode they
are in right now.

Modes:
- best: whatever teaches most now. The vocabulary check when none was done in the last
  few weeks, an Anki session when enough cards wait, else a video just above the
  learner's level with many words worth learning.
- audio: listening only (driving, walking): videos that work without the picture.
- relax: entertainment, a little below the level and preferably long.
- read: reading units (none in the catalog yet).
- talk: a spoken conversation in Spanish with a voice assistant.
- type: spelling, optional and never offered in the other modes: the learner hears words
  they are learning and types them.

A video close to the learner's level ranks first. Staying in the series of the last
videos ranks higher, since its episodes reuse their words (narrow viewing, Rodgers &
Webb 2011), and a series the learner called boring ranks lower. The picker offers the
best and up to two alternatives from other series, because choosing keeps learners
going (Patall, Cooper & Robinson 2008).
"""

import time

from . import vocab

MODES = ("best", "audio", "relax", "read", "talk", "type")
# Modes the catalog and the server can serve so far.
AVAILABLE = ("best", "audio", "relax", "talk", "type")
ANKI_MIN = 10
# Levels are CEFR levels (pipeline/levels.py): how far above or below the learner each
# mode aims, how far around that a unit still counts as near, and how much a level of
# distance costs a unit's rank.
TARGET = {"best": 0.2, "audio": 0.0, "relax": -0.5}
WINDOW = 0.6
DISTANCE = 3.1
# Rank gained per unit of known-word coverage: 10 points of coverage are worth what 0.2
# levels of distance cost.
COVERAGE = 6.2
COVERAGE_TARGET = 0.95
# What the learner likes to watch anyway, by the topic of a unit's channel
# (data/channels.json): from their YouTube likes and history, adjusted by them towards
# engineering, repair and tech and away from news. A unit of a liked topic ranks as if it
# were up to a quarter level closer.
TOPICS = {"engineering": 0.8, "repair": 0.7, "tech": 0.6, "dev": 0.5, "science": 0.4,
          "comedy": 0.3, "history": 0.2, "travel": 0.1, "talk": 0.1, "learner": 0.0, "news": -0.3}
SAME_SERIES = 0.6
BORING = 1.5
LONG = 900
CHOICES = 3
NEW_WORDS = 20
TYPE_WORDS = 10


def pick(mode, catalog, store, anki_status, recall=None):
    level = store.level
    options = []
    last = store.last_vocab_check()
    if mode == "best" and (last is None or time.time() - last > vocab.EVERY_DAYS * 86400):
        options.append({"kind": "vocab", "title": "Vocabulary"})
    if mode == "best" and anki_status["due"] + anki_status["new"] >= ANKI_MIN:
        options.append({"kind": "anki", "title": "Anki session",
                        "due": anki_status["due"], "new": anki_status["new"]})
    if mode == "talk":
        options.append({"kind": "talk", "title": "Hablar", "level": level})
    if mode == "type":
        notes = store.to_spell(TYPE_WORDS)
        if notes:
            options.append({"kind": "type", "title": "Escribir", "notes": notes})
    if mode in ("best", "audio", "relax"):
        known = store.known(catalog, recall)
        options += [video_option(u, catalog, store, known) for u in videos(mode, level, catalog, store, known)]
    return {"level": level, "options": options[:CHOICES]}


def videos(mode, level, catalog, store, known):
    done = store.done()
    target = level + TARGET[mode]
    pool = [u for u in catalog.units if u.kind == "video" and u.id not in done
            and (mode != "audio" or u.audio)]
    near = [u for u in pool if abs(u.level - target) <= WINDOW]
    if len(near) < CHOICES:
        near = sorted(pool, key=lambda u: abs(u.level - target))[:30]
    feedback = store.series_feedback()
    boring = {}
    for unit_id, flags in feedback.items():
        u = catalog.by_id.get(unit_id)
        if u:
            boring.setdefault(u.series, []).extend(flags)
    last = [catalog.by_id[r["unit"]].series for r in store.recent(2) if r["unit"] in catalog.by_id]
    taken = store.introduced()

    def rank(u):
        score = -DISTANCE * abs(u.level - target)
        # Known-word coverage counts up to COVERAGE_TARGET: listening is comfortable
        # from about 95% known words (van Zeeland & Schmitt 2013); beyond that the
        # level decides.
        score += COVERAGE * min(catalog.coverage(u, known), COVERAGE_TARGET)
        score += TOPICS.get(u.topic, 0.0)
        flags = boring.get(u.series, [])
        if flags:
            score -= BORING * sum(flags) / len(flags)
        if u.series in last and u.series != u.channel:
            score += SAME_SERIES
        if mode == "best":
            score += 0.5 * min(len(catalog.new_words(u, known, taken, NEW_WORDS)), NEW_WORDS) / NEW_WORDS
        if mode == "relax" and (u.duration or 0) >= LONG:
            score += 0.5
        return score
    chosen, series = [], set()
    for u in sorted(near, key=rank, reverse=True):
        if u.series in series and u.series != u.channel:
            continue
        chosen.append(u)
        series.add(u.series)
        if len(chosen) == CHOICES:
            break
    return chosen


def video_option(unit, catalog, store, known):
    return {**unit.public(),
            "coverage": round(catalog.coverage(unit, known), 3),
            "new_words": len(catalog.new_words(unit, known, store.introduced(), NEW_WORDS))}
