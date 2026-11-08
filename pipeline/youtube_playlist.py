"""Publish the watching order as a YouTube playlist on the learner's channel.

  python youtube_playlist.py sync <auth user> [<page id>]

Publishes build/order.json as one playlist per CEFR level (split in parts where a level
holds more than YouTube's 5,000 videos a playlist) and records them in data/playlist.json;
playlists recorded there before keep their ids and are refilled (see sync). Talks to YouTube's own web API (InnerTube) with the session cookies of a signed-in
browser (YTDLP_COOKIES, or a Firefox or Zen profile in FIREFOX_PROFILE); YouTube's web client signs each request with a
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

from config import DATA, FIREFOX_PROFILE, ORDER, YTDLP_COOKIES

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
    """youtube.com auth cookies of the signed-in browser: YTDLP_COOKIES (a yt-dlp
    --cookies-from-browser spec, browser[+keyring]:profile) or else the Firefox profile."""
    if YTDLP_COOKIES:
        from yt_dlp.cookies import extract_cookies_from_browser
        browser, _, profile = YTDLP_COOKIES.partition(":")
        browser, _, keyring = browser.partition("+")
        jar = extract_cookies_from_browser(browser, profile or None, keyring=keyring.upper() or None)
        return {c.name: c.value for c in jar
                if c.domain in (".youtube.com", "youtube.com", "www.youtube.com") and c.name in AUTH_COOKIES}
    return firefox_cookies(origin_attributes)


def firefox_cookies(origin_attributes=""):
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

    def edit(self, playlist_id, actions):
        # One edit request carries many actions; batches keep the request count low.
        for i in range(0, len(actions), CREATE_BATCH):
            self.call("browse/edit_playlist",
                      {"playlistId": playlist_id, "actions": actions[i:i + CREATE_BATCH]})

    def playlist_videos(self, playlist_id):
        """Video ids in a playlist, following its continuation pages."""
        res = self.call("browse", {"browseId": "VL" + playlist_id})
        ids = []
        while True:
            text = json.dumps(res)
            ids += re.findall(r'"playlistVideoRenderer": \{"videoId": "([\w-]{11})"', text)
            token = re.findall(r'"continuationCommand": \{"token": "([^"]+)"', text)
            if not token:
                return list(dict.fromkeys(ids))
            # The video list's own continuation comes first; later ones belong to other
            # parts of the page.
            res = self.call("browse", {"continuation": token[0]})

    def create_playlist(self, title, video_ids, privacy="UNLISTED"):
        first, rest = video_ids[:CREATE_BATCH], video_ids[CREATE_BATCH:]
        res = self.call(
            "playlist/create",
            {"title": title, "privacyStatus": privacy, "videoIds": first},
        )
        playlist_id = res.get("playlistId")
        if not playlist_id:
            raise SystemExit(f"create failed for {title!r}: {json.dumps(res)[:600]}")
        self.edit(playlist_id, [{"addedVideoId": v, "action": "ACTION_ADD_VIDEO"} for v in rest])
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


TITLE = "Spanish immersion {level}: easy to hard{part}"
DESCRIPTION = """{count} Spanish immersion videos ({hours} hours) at CEFR level {level}, ordered from the easiest to the hardest: native speakers talking about engineering, repair, tech, science, history and more, and conversations made for learners. No grammar lessons.

Every video is placed on the CEFR scale (A1 to C2) by a model fitted to recordings of known level: the official DELE exam listening tasks and teachers' talks recorded for each level. It measures speaking rate with pauses left out, how many words of each CEFR level a video uses, and sentence structure. One playlist per level, from Pre-A1 to C2:
{others}

Curve, progress tracking, an Anki deck with the words of every video and how it is made:
https://github.com/tieo/spanish-immersion-path"""
# YouTube holds at most 5,000 videos in a playlist; a level with more is split in parts.
LIMIT = 5000
LEVELS = ["A1", "A2", "B1", "B2", "C1", "C2"]


def level(score):
    """The CEFR level of a score: 0 to 5 are the middle of A1 to C2 (pipeline/levels.py)."""
    band = int((score + 0.5) // 1)
    return "Pre-A1" if band < 0 else LEVELS[min(band, 5)]


def groups(order):
    """The playlists to publish, in order: per level, in parts of at most LIMIT videos."""
    by_level = {}
    for v in order:
        by_level.setdefault(level(v["score"]), []).append(v)
    out = []
    for name in ["Pre-A1"] + LEVELS:
        videos = by_level.get(name, [])
        parts = [videos[i:i + LIMIT] for i in range(0, len(videos), LIMIT)]
        for k, part in enumerate(parts):
            out.append({"level": name, "videos": part,
                        "title": TITLE.format(level=name, part=f" ({k + 1}/{len(parts)})" if len(parts) > 1 else "")})
    return out


def sync(auth_user, page_id=None):
    """Make the recorded playlists hold the current order, one per level and part: the
    recorded ones keep their ids, so links to them stay valid, and get renamed, emptied and
    refilled; missing ones are created and surplus ones deleted."""
    order = json.load(open(ORDER))
    wanted = groups(order)
    try:
        recorded = json.load(open(DATA / "playlist.json"))
    except FileNotFoundError:
        recorded = {}
    ids = [p["id"] for p in recorded.get("playlists", [])] or ([recorded["id"]] if "id" in recorded else [])
    tube = Innertube(load_cookies(), auth_user, page_id)
    print("publishing as", tube.whoami())
    done = []
    for k, g in enumerate(wanted):
        videos = [v["id"] for v in g["videos"]]
        if k < len(ids):
            playlist = ids[k]
            # The rename goes first: an identity without rights fails here, before the emptying.
            tube.edit(playlist, [{"action": "ACTION_SET_PLAYLIST_NAME", "playlistName": g["title"]}])
            current = tube.playlist_videos(playlist)
            tube.edit(playlist, [{"removedVideoId": v, "action": "ACTION_REMOVE_VIDEO_BY_VIDEO_ID"} for v in current])
            tube.edit(playlist, [{"addedVideoId": v, "action": "ACTION_ADD_VIDEO"} for v in videos])
        else:
            playlist = tube.create_playlist(g["title"], videos, privacy="PUBLIC")
        done.append({"level": g["level"], "title": g["title"], "id": playlist, "videos": len(videos),
                     "hours": round(sum(v.get("duration") or 0 for v in g["videos"]) / 3600)})
        print(f"{g['title']}: {playlist}, {len(videos)} videos", flush=True)
    for playlist in ids[len(wanted):]:
        tube.delete_playlist(playlist)
    others = "\n".join(f"{p['title']}: https://www.youtube.com/playlist?list={p['id']}" for p in done)
    for p in done:
        tube.set_description(p["id"], DESCRIPTION.format(count=p["videos"], hours=p["hours"],
                                                         level=p["level"], others=others))
    json.dump({"playlists": done}, open(DATA / "playlist.json", "w"), indent=1)


if __name__ == "__main__":
    sync(sys.argv[2] if sys.argv[1] == "sync" else sys.argv[1], *sys.argv[3:4])
