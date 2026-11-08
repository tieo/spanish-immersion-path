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
import re
import shutil
import threading
import time

from anki.collection import Collection
from anki.errors import NetworkError, SyncError, SyncErrorKind
from anki.sync import SyncAuth
from anki.sync_pb2 import SyncCollectionResponse

ROOT = "Spanish Immersion Path"
Required = SyncCollectionResponse.ChangesRequired
PRESET = "Spanish Immersion Path"
NOTE_TYPE = "Spanish Immersion Word"
# Probability of recalling a card's word by the card's state (Anki.recall).
RECALL = {"review": 0.9, "lapsed": 0.5, "learning": 0.5, "new": 0.2}


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

    def _try_sync(self):
        """Sync for the running app. AnkiWeb serves one sync per account at a time, so a
        device syncing at this moment refuses this one, and it can be out of reach: the
        app goes on with the copy it has and a later sync carries the changes both ways.
        A rejected login stays an error, since no later sync would succeed."""
        try:
            self._sync()
        except NetworkError as e:
            print("AnkiWeb out of reach, going on with the local copy:", e, flush=True)
        except SyncError as e:
            if e.kind == SyncErrorKind.AUTH:
                raise
            print("AnkiWeb refused this sync, going on with the local copy:", e, flush=True)

    def sync(self):
        with self.lock:
            self._try_sync()

    def update_cards(self):
        """Bring the word cards up to how they should look and behave: the note type's
        template from pipeline/card_template.py, and the deck preset's audio playing only
        on tap. Neither changes the fields, so this is a normal sync. Returns what changed."""
        from pipeline.card_template import BACK, CSS, FRONT, TEMPLATE_NAME
        changed = []
        with self.lock:
            self._try_sync()
            model = self.col.models.by_name(NOTE_TYPE)
            template = next((t for t in model["tmpls"] if t["name"] == TEMPLATE_NAME), None) if model else None
            if template and (template["qfmt"], template["afmt"], model["css"]) != (FRONT, BACK, CSS):
                template["qfmt"], template["afmt"], model["css"] = FRONT, BACK, CSS
                self.col.models.update_dict(model)
                changed.append("template")
            conf = next((c for c in self.col.decks.all_config() if c["name"] == PRESET), None)
            if conf and conf.get("autoplay", True):
                conf["autoplay"] = False
                self.col.decks.update_config(conf)
                changed.append("no autoplay")
            if changed:
                self._try_sync()
        return changed

    def sync_media(self):
        """Bring the cards' recordings in the copy's media folder and on AnkiWeb up to
        date with each other: it fetches what the learner's devices added and sends what
        add_notes added."""
        self.col.sync_media(self.auth)

    def media_dir(self):
        return self.col.media.dir()

    def words(self, keys):
        """Word, meaning, IPA and the Spain recording of these notes, by note key."""
        with self.lock:
            model = self.col.models.by_name(NOTE_TYPE)
            if not model or not keys:
                return {}
            index = {f["name"]: f["ord"] for f in model["flds"]}
            wanted = set(keys)
            out = {}
            for flds, in self.col.db.all("select flds from notes where mid = ?", model["id"]):
                f = flds.split("\x1f")
                if f[index["Key"]] not in wanted:
                    continue
                sound = re.search(r"\[sound:([^\]]+)\]", f[index["AudioSpain"]])
                out[f[index["Key"]]] = {
                    "word": f[index["Word"]],
                    "meaning": f[index["Meaning"]],
                    "ipa": re.sub(r"<[^>]+>", "", f[index["IPA"]]),
                    "audio": sound.group(1) if sound else None,
                }
            return out

    def recall(self):
        """How likely the learner recalls each card's word, by note key, from the card's
        state in the local copy (synced with the Anki unit and the next-unit request):
        a review card RECALL["review"] unless its last answer was Again, a card in
        (re)learning RECALL["learning"], an introduced card not studied yet
        RECALL["new"]. Cards not introduced are left out."""
        with self.lock:
            model = self.col.models.by_name(NOTE_TYPE)
            if not model:
                return {}
            key = next(f["ord"] for f in model["flds"] if f["name"] == "Key")
            rows = self.col.db.all(
                "select n.flds, c.type, (select r.ease from revlog r where r.cid = c.id "
                "order by r.id desc limit 1) from cards c join notes n on n.id = c.nid "
                "where c.did = ? and c.queue != -1", self._deck())
        out = {}
        for flds, ctype, last in rows:
            state = ("lapsed" if last == 1 else "review") if ctype == 2 else \
                "learning" if ctype in (1, 3) else "new"
            out[flds.split("\x1f")[key]] = RECALL[state]
        return out

    def update_notes(self, fields):
        """Set fields of notes by note key, {key: {field: value}}; only notes whose
        values differ are written. Field contents are no schema change, so this is a
        normal sync."""
        with self.lock:
            self._sync()
            changed = []
            for nid in self.col.find_notes(f'"note:{NOTE_TYPE}"'):
                note = self.col.get_note(nid)
                want = fields.get(note["Key"])
                if want and any(note[k] != v for k, v in want.items()):
                    for k, v in want.items():
                        note[k] = v
                    changed.append(note)
            if changed:
                self.col.update_notes(changed)
                self._sync()
            return len(changed)

    def add_notes(self, fields, media):
        """Add the notes of these keys that the collection lacks, {key: {field: value}}
        (pipeline/deck.py), to the one deck with their cards suspended, so the app
        introduces them like every other word; their recordings are copied from the
        media folder into the collection's and sent to AnkiWeb. Adding notes is no
        schema change, so this is a normal sync. Returns the number added."""
        with self.lock:
            self._sync()
            model = self.col.models.by_name(NOTE_TYPE)
            key = next(f["ord"] for f in model["flds"] if f["name"] == "Key")
            have = {flds.split("\x1f")[key] for flds, in
                    self.col.db.all("select flds from notes where mid = ?", model["id"])}
            root, added = self._deck(), []
            for k, values in fields.items():
                if k in have:
                    continue
                note = self.col.new_note(model)
                for name, value in values.items():
                    note[name] = value
                self.col.add_note(note, root)
                added.append(note)
                for name in re.findall(r"\[sound:([^\]]+)\]", values.get("AudioSpain", "") +
                                       values.get("AudioLatinAmerica", "")):
                    target = os.path.join(self.col.media.dir(), name)
                    if not os.path.exists(target):
                        shutil.copyfile(os.path.join(media, name), target)
            if added:
                self.col.sched.suspend_cards([c.id for n in added for c in n.cards()])
                self._sync()
        if added:
            self.col.sync_media(self.auth)
        return len(added)

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
            self._try_sync()
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
            self._try_sync()
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


    def session(self, since):
        """What the learner did in Anki since a time (seconds since the epoch), as far
        as AnkiDroid has synced it: answers and time spent, and what still waits.
        `synced` says whether any device synced changes to AnkiWeb since then: a sync
        that carries changes sets the collection's modified time on both sides to the
        time it finished, and this server changes nothing during an Anki unit, so an
        older modified time means AnkiDroid has not synced the session yet."""
        with self.lock:
            self._try_sync()
            synced = self.col.mod >= since * 1000
            root = self._deck()
            reviews, ms = self.col.db.first(
                "select count(), coalesce(sum(min(r.time, 60000)), 0) from revlog r "
                "join cards c on c.id = r.cid where c.did = ? and r.id >= ? and r.type < 4",
                root, int(since * 1000))
        return {"reviews": reviews, "seconds": round(ms / 1000), "synced": synced, **self.status()}

    def stats(self, days, sync=True):
        """Card counts, recall and per-day reviews over the last `days` days, by local date."""
        with self.lock:
            if sync:
                self._try_sync()
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

    def session(self, since):
        return {"reviews": 0, "seconds": 0, "synced": True, **self.status()}

    def update_cards(self):
        return []

    def sync_media(self):
        pass

    def media_dir(self):
        return None

    def words(self, keys):
        return {}

    def recall(self):
        return {}


def connect(state_dir):
    hkey = os.environ.get("ANKIWEB_HKEY")
    if not hkey and os.environ.get("ANKIWEB_HKEY_FILE"):
        hkey = open(os.environ["ANKIWEB_HKEY_FILE"]).read().strip()
    if not hkey:
        return NoAnki()
    anki = Anki(os.path.join(state_dir, "collection.anki2"), hkey)
    anki.sync()
    changed = anki.update_cards()
    if changed:
        print("word cards updated in the collection:", ", ".join(changed), flush=True)
    return anki


if __name__ == "__main__":
    # python -m server.collection single-deck <state dir>: the one-time move from the
    # per-video sub-decks to the single deck, with ANKIWEB_HKEY set.
    import sys
    if sys.argv[1] == "single-deck":
        print(connect(sys.argv[2]).single_deck())
    # python -m server.collection update-notes <state dir> <fields.json>: card content
    # rebuilt by the pipeline ({key: {field: value}}, pipeline/deck.py) into the notes.
    elif sys.argv[1] == "update-notes":
        import json
        print(connect(sys.argv[2]).update_notes(json.load(open(sys.argv[3], encoding="utf-8"))), "notes updated")
    # python -m server.collection add-notes <state dir> <fields.json> <media dir>: notes of
    # the card pool the collection lacks, added suspended (Anki.add_notes).
    elif sys.argv[1] == "add-notes":
        import json
        fields = json.load(open(sys.argv[3], encoding="utf-8"))
        print(connect(sys.argv[2]).add_notes(fields, sys.argv[4]), "notes added")
