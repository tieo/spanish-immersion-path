"""Put the deck into the learner's AnkiWeb collection without touching what is already there.

  probe   log in with a fresh empty collection and report what the server would require
  push    download the server collection, import build/deck.apkg into it, sync it back

push options:
  --remove-deck NAME    delete an earlier deck and its cards first; refused when any of
                        its cards has been reviewed

A brand-new local collection must never be uploaded over a non-empty server collection,
which would replace the learner's existing decks and history. "push" therefore always
takes the server copy first (full download) and only then adds the package and runs a
normal incremental sync. A full upload happens only when the server was empty, or when
the import changed a note type's fields (a schema change, which Anki can only sync one
way) right after this run downloaded the server copy, so the upload is that copy plus
the package.

Credentials come from the ANKIWEB_USER and ANKIWEB_PASS environment variables.
"""

import hashlib
import os
import sys
import time

from anki.collection import Collection, ImportAnkiPackageOptions, ImportAnkiPackageRequest
from anki.import_export_pb2 import ImportAnkiPackageUpdateCondition
from anki.sync_pb2 import SyncCollectionResponse

from config import BUILD

WORK = BUILD / "ankiweb"
Required = SyncCollectionResponse.ChangesRequired


def login(col):
    return col.sync_login(
        username=os.environ["ANKIWEB_USER"], password=os.environ["ANKIWEB_PASS"], endpoint=None
    )


def sync(col, auth):
    out = col.sync_collection(auth=auth, sync_media=False)
    if out.new_endpoint:
        auth.endpoint = out.new_endpoint
    return out


ROOT = "Spanish Immersion Path"


def deck_id(video):
    """The fixed id of a video's sub-deck, so its cards stay in it across rebuilds."""
    return 1_800_000_000 + int(hashlib.sha1(video.encode()).hexdigest()[:8], 16) % 100_000_000


def preset(col, name, new_per_day):
    for conf in col.decks.all_config():
        if conf["name"] == name:
            break
    else:
        conf = col.decks.get_config(col.decks.add_config_returning_id(name))
    conf["new"]["perDay"] = new_per_day
    col.decks.update_config(conf)
    return conf["id"]


def configure_decks(col):
    """Studying the parent deck shows only reviews; an episode's sub-deck hands out all
    of its new cards at once. With the v3 scheduler the limits of the deck that is
    clicked apply, so the parent's zero does not block a sub-deck opened directly."""
    reviews_only = preset(col, "Spanish Immersion Path: reviews only", 0)
    episode = preset(col, "Spanish Immersion Path: video", 9999)
    for d in col.decks.all_names_and_ids():
        if d.name == ROOT:
            col.decks.set_config_id_for_deck_dict(col.decks.get(d.id), reviews_only)
        elif d.name.startswith(ROOT + "::"):
            col.decks.set_config_id_for_deck_dict(col.decks.get(d.id), episode)


def remove_deck(col, name):
    """Delete an earlier deck tree with its notes, unless anything in it was studied."""
    ids = [d.id for d in col.decks.all_names_and_ids() if d.name == name or d.name.startswith(name + "::")]
    if not ids:
        return
    marks = ",".join(map(str, ids))
    cards = col.db.list(f"select id from cards where did in ({marks})")
    reviewed = col.db.scalar(
        f"select count() from revlog where cid in (select id from cards where did in ({marks}))")
    if reviewed:
        raise SystemExit(f"refusing to remove {name!r}: {reviewed} reviews in it")
    col.remove_notes_by_card(cards)
    col.decks.remove(ids)
    print(f"removed {name!r}: {len(ids)} decks, {len(cards)} cards")


def summary(col):
    names = [d.name for d in col.decks.all_names_and_ids()]
    return f"{col.card_count()} cards, {col.note_count()} notes, {len(names)} decks"


def main():
    mode = sys.argv[1]
    os.makedirs(WORK, exist_ok=True)
    path = os.path.join(WORK, f"{mode}.anki2")
    remove = sys.argv[sys.argv.index("--remove-deck") + 1] if "--remove-deck" in sys.argv else None
    for ext in ("", "-wal", "-shm"):
        if os.path.exists(path + ext):
            os.remove(path + ext)
    col = Collection(path)
    auth = login(col)
    out = sync(col, auth)
    print("server says:", Required.Name(out.required), "| server message:", out.server_message)

    if mode == "probe":
        col.close()
        return

    downloaded = False
    if out.required in (Required.FULL_SYNC, Required.FULL_DOWNLOAD):
        col.close_for_full_sync()
        col.full_upload_or_download(auth=auth, server_usn=out.server_media_usn, upload=False)
        col.reopen(after_full_sync=True)
        downloaded = True
        print("downloaded server collection:", summary(col))
    elif out.required == Required.FULL_UPLOAD:
        print("server collection is empty; the first sync uploads")
    else:
        print("no full sync needed")

    if remove:
        remove_deck(col, remove)
    req = ImportAnkiPackageRequest(
        package_path=str(BUILD / "deck.apkg"),
        # The package is the source of truth for card content, so its notes and note
        # type replace the server's even when Anki's timestamps call them older.
        # Scheduling is not imported, so review history stays as it is.
        options=ImportAnkiPackageOptions(
            merge_notetypes=True,
            update_notes=ImportAnkiPackageUpdateCondition.IMPORT_ANKI_PACKAGE_UPDATE_CONDITION_ALWAYS,
            update_notetypes=ImportAnkiPackageUpdateCondition.IMPORT_ANKI_PACKAGE_UPDATE_CONDITION_ALWAYS,
            with_scheduling=False,
            with_deck_configs=False,
        ),
    )
    col.import_anki_package(req)
    configure_decks(col)
    print("after import:", summary(col))

    out = sync(col, auth)
    if out.required == Required.FULL_UPLOAD or (
        out.required == Required.FULL_SYNC and downloaded
    ):
        col.close_for_full_sync()
        col.full_upload_or_download(auth=auth, server_usn=out.server_media_usn, upload=True)
        col.reopen(after_full_sync=True)
        print("full upload:", summary(col))
    elif out.required in (Required.FULL_SYNC, Required.FULL_DOWNLOAD):
        raise SystemExit(f"refusing: server still asks for {Required.Name(out.required)}")
    print("final sync:", Required.Name(out.required))
    out = sync(col, auth)
    print("check sync:", Required.Name(out.required))
    # The cards' recordings live in the media folder, which syncs separately and in
    # the background; wait until it has finished before closing.
    col.sync_media(auth)
    while True:
        time.sleep(2)
        status = col.media_sync_status()
        if not status.active:
            break
    print("media synced:", status.progress)
    col.close()


if __name__ == "__main__":
    main()
