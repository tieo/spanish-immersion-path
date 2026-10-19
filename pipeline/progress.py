"""The learner's Anki progress per video, for the progress page.

  progress   download the AnkiWeb collection and write site/progress.json
  hostkey    log in with ANKIWEB_USER and ANKIWEB_PASS and print the sync key, which
             "progress" then uses from ANKIWEB_HKEY instead of the password

progress.json maps each video id to the state of its sub-deck: cards still new, in
learning, in review, mature (interval of 21 days or more) and due today, plus the day
its first card was studied. Sub-decks are matched to videos by the video link on their
cards, so the mapping holds when the order or the deck names change. The download is read-only: nothing is synced
back.
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


def deck_video(col, deck):
    """The video a sub-deck belongs to: the first link in a note's fields is its Source,
    the moment in the video the example sentence comes from."""
    if not deck.name.startswith(ROOT + "::"):
        return None
    fields = col.db.scalar(
        "select flds from notes where id = (select nid from cards where did = ? limit 1)", deck.id)
    m = re.search(r"watch\?v=([\w-]{11})", fields or "")
    return m.group(1) if m else None


def progress(col):
    known = {v["id"] for v in json.load(open(DATA / "order.json"))}
    today = col.sched.today
    day_start = col.sched.day_cutoff - 86400
    videos = {}
    for d in col.decks.all_names_and_ids():
        video = deck_video(col, d)
        if video not in known:
            continue
        row = col.db.first(
            """select count(), sum(type = 0), sum(type in (1, 3)), sum(type = 2),
                      sum(type = 2 and ivl >= ?),
                      sum((queue in (2, 3) and due <= ?) or (queue = 1 and due < ?))
               from cards where did = ?""",
            # Review and interday learning cards are due by day number, intraday
            # learning cards by timestamp.
            MATURE_DAYS, today, col.sched.day_cutoff, d.id)
        first = col.db.scalar(
            "select min(id) from revlog where cid in (select id from cards where did = ?)"
            " and type != 4", d.id)
        cards, new, learning, review, mature, due = (x or 0 for x in row)
        videos[video] = {
            "cards": cards, "new": new, "learning": learning, "review": review,
            "mature": mature, "due": due,
            "started": datetime.date.fromtimestamp(first / 1000).isoformat() if first else None,
        }
    reviews_today = col.db.scalar(
        "select count() from revlog where id >= ? and type != 4", day_start * 1000)
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
        print(f"{len(data['videos'])} video decks, {started} started, "
              f"{data['reviews_today']} reviews today -> {OUT}")
    col.close()


if __name__ == "__main__":
    main()
