"""The learner's Anki collection, synced with AnkiWeb.

The server keeps its own copy of the collection and syncs it incrementally with AnkiWeb
around every change, so changes made on the learner's devices and here merge. It never
uploads a whole collection: when AnkiWeb asks for a full sync, the server takes the
AnkiWeb copy, so its own unsynced changes are the only thing a conflict can lose.

All notes of the path live in one deck, their cards suspended until a unit introduces
them: after the learner finishes a video, its new words are unsuspended and queued in
order, and the next Anki session teaches them. Words never introduced (because the
learner probably knows them, or no unit reached them yet) stay suspended.
"""

import os
import threading
import time

from anki.collection import Collection
from anki.sync import SyncAuth
from anki.sync_pb2 import SyncCollectionResponse

ROOT = "Spanish Immersion Path"
Required = SyncCollectionResponse.ChangesRequired
PRESET = "Spanish Immersion Path"
NOTE_TYPE = "Spanish Immersion Word"


class Anki:
    def __init__(self, path, hkey):
        self.lock = threading.Lock()
        self.auth = SyncAuth(hkey=hkey, endpoint=None)
        self.col = Collection(path)

    def _sync(self):
        out = self.col.sync_collection(auth=self.auth, sync_media=False)
        if out.new_endpoint:
            self.auth = SyncAuth(hkey=self.auth.hkey, endpoint=out.new_endpoint)
        if out.required in (Required.FULL_SYNC, Required.FULL_DOWNLOAD):
            self.col.close_for_full_sync()
            self.col.full_upload_or_download(auth=self.auth, server_usn=out.server_media_usn, upload=False)
            self.col.reopen(after_full_sync=True)
        elif out.required == Required.FULL_UPLOAD:
            raise RuntimeError("AnkiWeb has no collection; refusing to upload this copy over it")

    def sync(self):
        with self.lock:
            self._sync()

    def update_template(self):
        """Bring the word cards' note type up to pipeline/card_template.py. Only the
        template text and styling change, not the fields, so this is a normal sync."""
        from pipeline.card_template import BACK, CSS, FRONT, TEMPLATE_NAME
        with self.lock:
            self._sync()
            model = self.col.models.by_name(NOTE_TYPE)
            if not model:
                return False
            template = next(t for t in model["tmpls"] if t["name"] == TEMPLATE_NAME)
            if (template["qfmt"], template["afmt"], model["css"]) == (FRONT, BACK, CSS):
                return False
            template["qfmt"], template["afmt"], model["css"] = FRONT, BACK, CSS
            self.col.models.update_dict(model)
            self._sync()
            return True

    def _deck(self):
        return self.col.decks.id_for_name(ROOT)

    def _tree(self):
        return [d.id for d in self.col.decks.all_names_and_ids()
                if d.name == ROOT or d.name.startswith(ROOT + "::")]

    def single_deck(self):
        """Move the cards of the per-video sub-decks into the one deck, suspend every new
        card and remove the sub-decks. Cards already in review keep their schedule."""
        with self.lock:
            self._sync()
            root = self._deck()
            subs = [i for i in self._tree() if i != root]
            marks = ",".join(map(str, subs)) or "0"
            cards = self.col.db.list(f"select id from cards where did in ({marks})")
            if cards:
                self.col.set_deck(cards, root)
            new = self.col.db.list(f"select id from cards where did = ? and type = 0 and queue != -1", root)
            if new:
                self.col.sched.suspend_cards(new)
            if subs:
                self.col.decks.remove(subs)
            conf = next((c for c in self.col.decks.all_config() if c["name"] == PRESET), None)
            if conf is None:
                conf = self.col.decks.get_config(self.col.decks.add_config_returning_id(PRESET))
            # Only introduced cards are unsuspended, so the deck may hand all of them out.
            conf["new"]["perDay"] = 9999
            self.col.decks.update_config(conf)
            self.col.decks.set_config_id_for_deck_dict(self.col.decks.get(root), conf["id"])
            self._sync()
            return {"moved": len(cards), "suspended": len(new), "removed_decks": len(subs)}

    def introduce(self, keys):
        """Unsuspend the cards of these notes and queue them after the new cards already
        waiting, in the given order."""
        if not keys:
            return 0
        with self.lock:
            self._sync()
            order = {k: i for i, k in enumerate(keys)}
            root = self._deck()
            rows = self.col.db.all(
                "select c.id, n.flds from cards c join notes n on n.id = c.nid "
                "where c.did = ? and c.type = 0 and c.queue = -1", root)
            cards = sorted((order[f.split("\x1f", 1)[0]], cid) for cid, f in rows
                           if f.split("\x1f", 1)[0] in order)
            ids = [cid for _, cid in cards]
            if ids:
                self.col.sched.unsuspend_cards(ids)
                top = self.col.db.scalar(
                    "select coalesce(max(due), 0) from cards where did = ? and type = 0 and queue = 0", root)
                self.col.sched.reposition_new_cards(ids, starting_from=top + 1, step_size=1,
                                                    randomize=False, shift_existing=False)
            self._sync()
            return len(ids)

    def status(self):
        """Cards due today and introduced new cards still waiting."""
        with self.lock:
            root = self._deck()
            today, cutoff = self.col.sched.today, self.col.sched.day_cutoff
            due = self.col.db.scalar(
                "select count() from cards where did = ? and "
                "((queue in (2, 3) and due <= ?) or (queue = 1 and due < ?))", root, today, cutoff)
            waiting = self.col.db.scalar("select count() from cards where did = ? and queue = 0", root)
            learned = self.col.db.scalar("select count() from cards where did = ? and type = 2", root)
            return {"due": due, "new": waiting, "learned": learned}


    def stats(self, days, sync=True):
        """Card counts, recall and per-day reviews over the last `days` days, by local date."""
        with self.lock:
            if sync:
                self._sync()
            root = self._deck()
            today, cutoff = self.col.sched.today, self.col.sched.day_cutoff
            q = lambda sql, *a: self.col.db.scalar(sql, root, *a)
            counts = {
                "introduced": q("select count() from cards where did = ? and queue != -1"),
                "waiting": q("select count() from cards where did = ? and queue = 0"),
                "learning": q("select count() from cards where did = ? and type in (1, 3)"),
                "review": q("select count() from cards where did = ? and type = 2"),
                "mature": q("select count() from cards where did = ? and type = 2 and ivl >= 21"),
                "due": q("select count() from cards where did = ? and "
                         "((queue in (2, 3) and due <= ?) or (queue = 1 and due < ?))", today, cutoff),
            }
            since = (cutoff - days * 86400) * 1000
            rows = self.col.db.all(
                "select r.id, r.type, r.ease, r.time from revlog r join cards c on c.id = r.cid "
                "where c.did = ? and r.id >= ? and r.type < 4", root, since)
            per_day = {}
            for rid, rtype, ease, ms in rows:
                day = time.strftime("%Y-%m-%d", time.localtime(rid / 1000))
                d = per_day.setdefault(day, {"reviews": 0, "seconds": 0})
                d["reviews"] += 1
                d["seconds"] += min(ms, 60000) / 1000
            # Recall: share of answers to cards in review that were not "again".
            answers = [ease for _, rtype, ease, _ in rows if rtype == 1]
            counts["recall"] = round(sum(e > 1 for e in answers) / len(answers), 3) if answers else None
            return {"cards": counts, "days": per_day}


class NoAnki:
    """Stand-in when no AnkiWeb key is configured (local development)."""

    def sync(self):
        pass

    def introduce(self, keys):
        return len(keys)

    def status(self):
        return {"due": 0, "new": 0, "learned": 0}

    def stats(self, days, sync=True):
        return {"cards": {}, "days": {}}

    def update_template(self):
        return False


def connect(state_dir):
    hkey = os.environ.get("ANKIWEB_HKEY")
    if not hkey and os.environ.get("ANKIWEB_HKEY_FILE"):
        hkey = open(os.environ["ANKIWEB_HKEY_FILE"]).read().strip()
    if not hkey:
        return NoAnki()
    anki = Anki(os.path.join(state_dir, "collection.anki2"), hkey)
    anki.sync()
    if anki.update_template():
        print("word card template updated in the collection", flush=True)
    return anki


if __name__ == "__main__":
    # python -m server.collection single-deck <state dir>: the one-time move from the
    # per-video sub-decks to the single deck, with ANKIWEB_HKEY set.
    import sys
    if sys.argv[1] == "single-deck":
        print(connect(sys.argv[2]).single_deck())
