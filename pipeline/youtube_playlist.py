"""Publish the watching order as a YouTube playlist on the learner's channel.

  python youtube_playlist.py publish <auth user> [<page id>]

Creates the playlist from data/order.json with its description, records its id in
data/playlist.json and deletes the playlist recorded there before, so a rebuild replaces
it. Talks to YouTube's own web API (InnerTube) with the session cookies of a signed-in
Firefox or Zen profile (FIREFOX_PROFILE); YouTube's web client signs each request with a
SAPISIDHASH derived from the SAPISID cookie, so no OAuth client is needed. A cookie jar
can hold several Google accounts (picked by auth user) and each can own brand channels
(picked by page id).
"""

import hashlib
import json
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import time
import urllib.request

from config import DATA, FIREFOX_PROFILE

PROFILE = FIREFOX_PROFILE
ORIGIN = "https://www.youtube.com"
INNERTUBE_KEY = "AIzaSyAO_FJ2SlqU8Q4STEHLGCilw_Y9_11qcW8"
CLIENT_VERSION = "2.20250101.00.00"

# InnerTube caps how many videos a single create call accepts; the rest are appended.
CREATE_BATCH = 50


# Only the cookies YouTube's own web client sends for auth. Taking every youtube.com
# cookie in the profile pushes the request header past the server's size limit (HTTP 413).
AUTH_COOKIES = {
    "SID", "HSID", "SSID", "APISID", "SAPISID",
    "__Secure-1PSID", "__Secure-3PSID",
    "__Secure-1PSIDTS", "__Secure-3PSIDTS",
    "SIDCC", "__Secure-1PSIDCC", "__Secure-3PSIDCC",
    "LOGIN_INFO", "PREF", "VISITOR_INFO1_LIVE", "YSC", "SOCS", "__Secure-YNID",
}


def load_cookies(origin_attributes=""):
    """Read one Firefox container's youtube.com auth cookies.

    Each container is an independent cookie jar; combining two yields Google auth
    cookies that do not belong together and the request is treated as signed out.
    """
    tmp = os.path.join(tempfile.gettempdir(), "sip_cookies.sqlite")
    for ext in ("", "-wal", "-shm"):
        src = os.path.join(PROFILE, "cookies.sqlite") + ext
        if os.path.exists(src):
            shutil.copy(src, tmp + ext)
    con = sqlite3.connect(tmp)
    rows = con.execute(
        "select name, value from moz_cookies where originAttributes = ? "
        "and host in ('.youtube.com', 'youtube.com', 'www.youtube.com')",
        (origin_attributes,),
    ).fetchall()
    con.close()
    for ext in ("", "-wal", "-shm"):
        if os.path.exists(tmp + ext):
            os.remove(tmp + ext)

    jar = {}
    for name, value in rows:
        if name in AUTH_COOKIES and name not in jar:
            jar[name] = value
    return jar


def sapisid_hash(sapisid):
    ts = int(time.time())
    digest = hashlib.sha1(f"{ts} {sapisid} {ORIGIN}".encode()).hexdigest()
    return f"SAPISIDHASH {ts}_{digest}"


class Innertube:
    """One YouTube identity.

    A signed-in cookie jar can carry several Google accounts (selected by auth_user)
    and each of those can own brand channels (selected by page_id), so an identity is
    the cookie jar plus that pair.
    """

    def __init__(self, cookies, auth_user="0", page_id=None):
        self.cookies = cookies
        sapisid = cookies.get("SAPISID") or cookies.get("__Secure-3PAPISID")
        if not sapisid:
            raise SystemExit("no SAPISID cookie: not signed in")
        self.sapisid = sapisid
        self.auth_user = auth_user
        self.page_id = page_id

    def call(self, endpoint, payload):
        body = dict(payload)
        body["context"] = {
            "client": {
                "clientName": "WEB",
                "clientVersion": CLIENT_VERSION,
                "hl": "en",
                "gl": "DE",
            }
        }
        if self.page_id:
            body["context"]["user"] = {"onBehalfOfUser": self.page_id}
        req = urllib.request.Request(
            f"{ORIGIN}/youtubei/v1/{endpoint}?key={INNERTUBE_KEY}&prettyPrint=false",
            data=json.dumps(body).encode(),
            method="POST",
        )
        req.add_header("Content-Type", "application/json")
        req.add_header("Authorization", sapisid_hash(self.sapisid))
        req.add_header("Origin", ORIGIN)
        req.add_header("X-Origin", ORIGIN)
        req.add_header("X-Goog-AuthUser", self.auth_user)
        if self.page_id:
            req.add_header("X-Goog-PageId", self.page_id)
        req.add_header("X-Youtube-Client-Name", "1")
        req.add_header("X-Youtube-Client-Version", CLIENT_VERSION)
        req.add_header(
            "User-Agent",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        )
        req.add_header("Cookie", "; ".join(f"{k}={v}" for k, v in self.cookies.items()))
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())

    def whoami(self):
        """Name and handle of the channel this identity currently acts as."""
        for item in walk_account_items(self.call("account/accounts_list", {})):
            if item.get("isSelected"):
                return {
                    "name": node_text(item.get("accountName")),
                    "handle": node_text(item.get("channelHandle")),
                }
        return {"name": None, "handle": None}

    def delete_playlist(self, playlist_id):
        return self.call("playlist/delete", {"playlistId": playlist_id})

    def set_description(self, playlist_id, text):
        """Playlist descriptions keep newlines and URLs, so a stage can link to the next."""
        return self.call(
            "browse/edit_playlist",
            {
                "playlistId": playlist_id,
                "actions": [
                    {"action": "ACTION_SET_PLAYLIST_DESCRIPTION", "playlistDescription": text}
                ],
            },
        )

    def create_playlist(self, title, video_ids, privacy="UNLISTED"):
        first, rest = video_ids[:CREATE_BATCH], video_ids[CREATE_BATCH:]
        res = self.call(
            "playlist/create",
            {"title": title, "privacyStatus": privacy, "videoIds": first},
        )
        playlist_id = res.get("playlistId")
        if not playlist_id:
            raise SystemExit(f"create failed for {title!r}: {json.dumps(res)[:600]}")
        for video_id in rest:
            self.call(
                "browse/edit_playlist",
                {
                    "playlistId": playlist_id,
                    "actions": [
                        {"addedVideoId": video_id, "action": "ACTION_ADD_VIDEO"}
                    ],
                },
            )
        return playlist_id


def node_text(node):
    """Flatten an InnerTube text node, which comes as either simpleText or runs."""
    if not isinstance(node, dict):
        return None
    if "simpleText" in node:
        return node["simpleText"]
    if "runs" in node:
        return "".join(run.get("text", "") for run in node["runs"])
    return None


def walk_account_items(tree):
    if isinstance(tree, dict):
        if "accountItem" in tree:
            yield tree["accountItem"]
        for value in tree.values():
            yield from walk_account_items(value)
    elif isinstance(tree, list):
        for value in tree:
            yield from walk_account_items(value)


TITLE = "Spanish immersion: easy to hard"
DESCRIPTION = """{count} Spanish immersion videos ({hours} hours) from Easy Spanish, Dreaming Spanish and Spanish After Hours, ordered from the easiest to the hardest: native speakers talking, no grammar lessons.

Every video is scored from its Spanish captions on speaking speed, rare vocabulary and grammar, and the playlist rises steadily in that score. Each video comes with its own Anki sub-deck of 20 to 40 new words, with pronunciation and the sentence from the video.

Curve, progress tracking and how it is made:
https://github.com/tieo/spanish-immersion-path"""


def publish(auth_user, page_id=None):
    order = json.load(open(DATA / "order.json"))
    ids = [v["id"] for v in order]
    hours = round(sum(v.get("duration") or 0 for v in order) / 3600)
    tube = Innertube(load_cookies(), auth_user, page_id)
    print("publishing as", tube.whoami())
    playlist = tube.create_playlist(TITLE, ids, privacy="PUBLIC")
    tube.set_description(playlist, DESCRIPTION.format(count=len(ids), hours=hours))
    try:
        old = json.load(open(DATA / "playlist.json"))["id"]
    except FileNotFoundError:
        old = None
    json.dump({"id": playlist, "videos": len(ids)}, open(DATA / "playlist.json", "w"), indent=1)
    if old and old != playlist:
        tube.delete_playlist(old)
    print(f"playlist {playlist}: {len(ids)} videos")


if __name__ == "__main__":
    if sys.argv[1] == "publish":
        publish(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)
