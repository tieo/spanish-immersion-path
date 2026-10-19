"""The learner's Anki progress per video, for the progress page.

  progress   download the AnkiWeb collection and write site/progress.json
  hostkey    log in with ANKIWEB_USER and ANKIWEB_PASS and print the sync key, which
             "progress" then uses from ANKIWEB_HKEY instead of the password

progress.json maps each video id to the state of its cards: still new, in learning, in
review, mature (interval of 21 days or more) and due today, plus the day its first card
was answered. Cards belong to the video their note was made from, read from the video
link on the note, so the mapping holds however the cards are spread over decks. The
download is read-only: nothing is synced back.
"""

import datetime
import json
import os
import re
import sys

from anki.collection import Collection
from anki.sync import SyncAuth
from anki.sync_pb2 import SyncCollectionResponse

from ankiweb import ROOT, WORK, login, sync
from config import DATA, ROOT as REPO

Required = SyncCollectionResponse.ChangesRequired
OUT = REPO / "site" / "progress.json"
MATURE_DAYS = 21


def fresh_collection():
    os.makedirs(WORK, exist_ok=True)
    path = os.path.join(WORK, "progress.anki2")
    for ext in ("", "-wal", "-shm"):
        if os.path.exists(path + ext):
            os.remove(path + ext)
    return Collection(path)


def download(col):
    if os.environ.get("ANKIWEB_HKEY"):
        auth = SyncAuth(hkey=os.environ["ANKIWEB_HKEY"], endpoint=None)
    else:
        auth = login(col)
    out = sync(col, auth)
    if out.required in (Required.FULL_SYNC, Required.FULL_DOWNLOAD):
        col.close_for_full_sync()
        col.full_upload_or_download(auth=auth, server_usn=out.server_media_usn, upload=False)
        col.reopen(after_full_sync=True)
    elif out.required != Required.NO_CHANGES:
        raise SystemExit(f"unexpected sync state {SyncCollectionResponse.ChangesRequired.Name(out.required)}")


def progress(col):
    """Cards grouped by the video their note was made from: the first link in a note's
    fields is its Source, the moment in the video its example sentence comes from."""
    known = {v["id"] for v in json.load(open(DATA / "order.json"))}
    today, cutoff = col.sched.today, col.sched.day_cutoff
    decks = [d.id for d in col.decks.all_names_and_ids() if d.name == ROOT or d.name.startswith(ROOT + "::")]
    marks = ",".join(map(str, decks)) or "0"
    # revlog types below 4 are answers; 4 and up are scheduling changes by hand.
    first_answer = dict(col.db.all("select cid, min(id) from revlog where type < 4 group by cid"))
    videos = {}
    for cid, ctype, queue, due, ivl, flds in col.db.all(
            f"select c.id, c.type, c.queue, c.due, c.ivl, n.flds from cards c join notes n on n.id = c.nid "
            f"where c.did in ({marks})"):
        m = re.search(r"watch\?v=([\w-]{11})", flds)
        if not m or m.group(1) not in known:
            continue
        v = videos.setdefault(m.group(1), {"cards": 0, "new": 0, "learning": 0, "review": 0,
                                           "mature": 0, "due": 0, "started": None})
        v["cards"] += 1
        v["new"] += ctype == 0
        v["learning"] += ctype in (1, 3)
        v["review"] += ctype == 2
        v["mature"] += ctype == 2 and ivl >= MATURE_DAYS
        # Review and interday learning cards are due by day number, intraday learning
        # cards by timestamp.
        v["due"] += (queue in (2, 3) and due <= today) or (queue == 1 and due < cutoff)
        if cid in first_answer:
            day = datetime.date.fromtimestamp(first_answer[cid] / 1000).isoformat()
            v["started"] = min(v["started"] or day, day)
    reviews_today = col.db.scalar(
        "select count() from revlog where id >= ? and type < 4", (cutoff - 86400) * 1000)
    return {"updated": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="minutes"),
            "reviews_today": reviews_today, "videos": videos}


def main():
    mode = sys.argv[1]
    col = fresh_collection()
    if mode == "hostkey":
        print(login(col).hkey)
    elif mode == "progress":
        download(col)
        data = progress(col)
        json.dump(data, open(OUT, "w"), separators=(",", ":"))
        started = sum(1 for v in data["videos"].values() if v["started"])
        print(f"{len(data['videos'])} videos with cards, {started} started, "
              f"{data['reviews_today']} reviews today -> {OUT}")
    col.close()


if __name__ == "__main__":
    main()
