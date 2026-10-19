"""The learner's Anki collection, synced with AnkiWeb.

The server keeps its own copy of the collection and syncs it incrementally with AnkiWeb
around every change, so changes made on the learner's devices and here merge. It never
uploads a whole collection: when AnkiWeb asks for a full sync, the server takes the
AnkiWeb copy, so its own unsynced changes are the only thing a conflict can lose.

All notes of the path live in one deck, their cards suspended until a unit introduces
them: after the learner finishes a video, its new words are unsuspended and queued in
order, and the next Anki session teaches them. Words never introduced (because the
placement test says the learner knows them, or no unit reached them yet) stay suspended.
"""

import os
import threading

from anki.collection import Collection
from anki.sync import SyncAuth
from anki.sync_pb2 import SyncCollectionResponse

ROOT = "Spanish Immersion Path"
Required = SyncCollectionResponse.ChangesRequired
PRESET = "Spanish Immersion Path"


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


class NoAnki:
    """Stand-in when no AnkiWeb key is configured (local development)."""

    def sync(self):
        pass

    def introduce(self, keys):
        return len(keys)

    def status(self):
        return {"due": 0, "new": 0, "learned": 0}


def connect(state_dir):
    hkey = os.environ.get("ANKIWEB_HKEY")
    if not hkey and os.environ.get("ANKIWEB_HKEY_FILE"):
        hkey = open(os.environ["ANKIWEB_HKEY_FILE"]).read().strip()
    if not hkey:
        return NoAnki()
    anki = Anki(os.path.join(state_dir, "collection.anki2"), hkey)
    anki.sync()
    return anki
