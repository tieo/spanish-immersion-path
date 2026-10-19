"""The learner's state in SQLite: level, vocabulary estimate, units done, words introduced.

The level is on the scale of the units (0 superbeginner, 1 beginner, 2 intermediate,
3 advanced, from pipeline/levels.py). The placement test sets it; every finished unit
moves it by how the learner rated the unit against the unit's own level.

Vocabulary is a curve: the probability of knowing a lemma rises with its frequency,
logistic in its Zipf value around the learner's threshold. The placement test fits the
threshold; words introduced through Anki count as known on top of it.
"""

import json
import math
import sqlite3
import time

SCHEMA = """
create table if not exists kv (key text primary key, value text not null);
create table if not exists history (
  id integer primary key, unit text not null, kind text not null, mode text,
  started real not null, finished real, rating text, boring integer, note text,
  seconds integer, words text);
create table if not exists introduced (note text primary key, unit text, at real not null);
"""

# How far one rating moves the level, in levels.
EASY_STEP = 0.1
HARD_STEP = 0.1
FOLLOW = 0.3
VOCAB_SLOPE = 2.0
INTRODUCED_KNOWN = 0.9


class Store:
    def __init__(self, path):
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)

    def get(self, key, default=None):
        row = self.db.execute("select value from kv where key = ?", (key,)).fetchone()
        return json.loads(row["value"]) if row else default

    def put(self, key, value):
        self.db.execute("insert or replace into kv values (?, ?)", (key, json.dumps(value)))
        self.db.commit()

    @property
    def level(self):
        return self.get("level")

    def known(self, catalog):
        """Probability of knowing each lemma, by lemma index."""
        threshold = self.get("vocab_threshold", 5.0)
        introduced = {catalog.note_lemma[n] for n in self.introduced() if n in catalog.note_lemma}

        def known(i):
            if i in introduced:
                return INTRODUCED_KNOWN
            return 1 / (1 + math.exp(-VOCAB_SLOPE * (catalog.lemmas[i]["zipf"] - threshold)))
        return known

    def introduced(self):
        return {r["note"] for r in self.db.execute("select note from introduced")}

    def introduce(self, notes, unit):
        self.db.executemany("insert or ignore into introduced values (?, ?, ?)",
                            [(n, unit, time.time()) for n in notes])
        self.db.commit()

    def start(self, unit, kind, mode):
        cur = self.db.execute("insert into history (unit, kind, mode, started) values (?, ?, ?, ?)",
                              (unit, kind, mode, time.time()))
        self.db.commit()
        return cur.lastrowid

    def open_unit(self):
        row = self.db.execute("select * from history where finished is null order by id desc limit 1").fetchone()
        return dict(row) if row else None

    def finish(self, entry, rating, boring, note, seconds, words):
        self.db.execute(
            "update history set finished = ?, rating = ?, boring = ?, note = ?, seconds = ?, words = ? where id = ?",
            (time.time(), rating, int(boring), note, seconds, json.dumps(words), entry))
        self.db.commit()

    def abandon(self, entry):
        self.db.execute("delete from history where id = ? and finished is null", (entry,))
        self.db.commit()

    def done(self):
        return {r["unit"] for r in self.db.execute("select unit from history where finished is not null")}

    def recent(self, n=10):
        return [dict(r) for r in self.db.execute(
            "select * from history where finished is not null order by finished desc limit ?", (n,))]

    def series_feedback(self):
        """Per series: how many finished units, how many of them were called boring."""
        out = {}
        for r in self.db.execute("select unit, boring from history where finished is not null"):
            out.setdefault(r["unit"], []).append(r["boring"] or 0)
        return out

    def seconds_done(self):
        return self.db.execute("select coalesce(sum(seconds), 0) from history where finished is not null").fetchone()[0]

    def rate(self, unit_level, rating):
        """Move the level by a rating of a unit at unit_level."""
        level = self.level if self.level is not None else unit_level
        if rating == "easy":
            level = max(level, unit_level) + EASY_STEP
        elif rating == "hard":
            level = min(level, unit_level) - HARD_STEP
        else:
            level += FOLLOW * (unit_level - level)
        self.put("level", round(level, 3))
        return level
