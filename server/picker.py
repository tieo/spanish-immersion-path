"""Which unit comes next, for the learner's level, what they have done and the mode they
are in right now.

Modes:
- best: whatever teaches most now. An Anki session when enough cards wait, else a video
  just above the learner's level with many words worth learning.
- audio: listening only (driving, walking): videos that work without the picture.
- relax: entertainment, a little below the level and preferably long.
- read: reading units (none in the catalog yet).
- talk: a conversation in Spanish with Claude.

A video close to the learner's level ranks first. Staying in the series of the last
videos ranks higher, since its episodes reuse their words (narrow viewing, Rodgers &
Webb 2011), and a series the learner called boring ranks lower. The picker offers the
best and up to two alternatives from other series, because choosing keeps learners
going (Patall, Cooper & Robinson 2008).
"""

MODES = ("best", "audio", "relax", "read", "talk")
# Modes the catalog and the server can serve so far.
AVAILABLE = ("best", "audio", "relax", "talk")
ANKI_MIN = 10
TARGET = {"best": 0.15, "audio": 0.0, "relax": -0.4}
WINDOW = 0.5
SAME_SERIES = 0.6
BORING = 1.5
LONG = 900
CHOICES = 3
NEW_WORDS = 20


def pick(mode, catalog, store, anki_status):
    level = store.level
    options = []
    if mode == "best" and anki_status["due"] + anki_status["new"] >= ANKI_MIN:
        options.append({"kind": "anki", "title": "Anki session",
                        "due": anki_status["due"], "new": anki_status["new"]})
    if mode == "talk":
        options.append({"kind": "talk", "title": "Talk with Claude", "level": level})
    if mode in ("best", "audio", "relax"):
        options += [video_option(u, catalog, store) for u in videos(mode, level, catalog, store)]
    return {"level": level, "options": options[:CHOICES]}


def videos(mode, level, catalog, store):
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
    known = store.known(catalog)
    taken = store.introduced()

    def rank(u):
        score = -4 * abs(u.level - target)
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


def video_option(unit, catalog, store):
    known = store.known(catalog)
    return {**unit.public(),
            "coverage": round(catalog.coverage(unit, known), 3),
            "new_words": len(catalog.new_words(unit, known, store.introduced(), NEW_WORDS))}
