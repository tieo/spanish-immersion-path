"""List the channels' videos and download their Spanish captions.

  list    add every video of the channels in data/channels.json to data/videos.json (id,
          title, duration, channel); videos already listed keep their entry. A channel's
          "latest" keeps only that many of its newest videos (news channels upload
          thousands of clips)
  fetch [k/n]  download the Spanish caption tracks of the immersion videos that have none
               yet, the liked topics first, waiting out YouTube's blocks; with k/n, only
               shard k of n
  cookies <file>  write the browser's YouTube session (YTDLP_COOKIES) to a cookies.txt
                  file, for a fetch on another machine (YTDLP_COOKIE_FILE)

Captions come from yt-dlp: the human-made Spanish track where the channel uploaded one,
and YouTube's speech recognition of the video's own audio ("es-orig"), which exists only
when the video is spoken in Spanish. One yt-dlp run takes all videos with a pause between
requests: a separate process per video repeats YouTube's bot check every time and gets
the address blocked. The signed-in browser session (YTDLP_COOKIES, a yt-dlp
--cookies-from-browser spec such as chromium+kwallet6:<profile dir>, or FIREFOX_PROFILE)
keeps it trusted. Without that session YouTube shows no captions at all, and yt-dlp needs
a JavaScript runtime on PATH (deno) to solve YouTube's challenges.
"""

import json
import os
import subprocess
import sys
import tempfile
import time
import zlib

from config import CAPTIONS, DATA, FIREFOX_PROFILE, YTDLP_COOKIE_FILE, YTDLP_COOKIES

YT_DLP = ["yt-dlp", "--impersonate", "chrome"]


def list_videos():
    path = DATA / "videos.json"
    try:
        videos = json.load(open(path))
    except FileNotFoundError:
        videos = []
    known = {v["id"] for v in videos}
    for ch in json.load(open(DATA / "channels.json")):
        # A channel's /videos tab lists the newest first; "latest" keeps that many.
        cap = ["--playlist-end", str(ch["latest"])] if ch.get("latest") else []
        out = subprocess.run(YT_DLP + ["--flat-playlist", "-J"] + cap + [ch["url"]],
                             capture_output=True, text=True, check=True).stdout
        new = [e for e in json.loads(out)["entries"] if e["id"] not in known]
        videos += [{"id": e["id"], "title": e.get("title"), "duration": e.get("duration"),
                    "channel": ch["name"]} for e in new]
        known |= {e["id"] for e in new}
        print(f"{ch['name']}: {len(new)} new", flush=True)
        json.dump(videos, open(path, "w"), ensure_ascii=False, indent=1)


# Videos without a Spanish track, so later runs skip them: the channel uploaded none and
# YouTube made none (it was not spoken in Spanish), or the video is for members only.
NONE = CAPTIONS / "none.txt"
NO_TRACK = ("There are no subtitles for the requested languages", "members-only",
            "available to this channel's members",
            "Video unavailable. This video", "Private video", "This video has been removed")
# YouTube blocks an address for up to an hour once it asks too much.
BLOCKED = "rate-limited"
BLOCK_PAUSE = 3600
# The browser rotates its YouTube session cookies, and a yt-dlp run keeps the ones it
# read at its start, so after a while YouTube treats it as signed out and answers every
# video with its bot check. Each run therefore takes BATCH videos, and a run whose
# cookies went stale is restarted at once with the browser's current ones; when even
# fresh cookies get the bot check, the address is blocked.
STALE = ("cookies are no longer valid", "Sign in to confirm you")
BATCH = 100
# The order of fetching: topics the learner likes first (server/picker.py TOPICS).
PRIORITY = ["engineering", "repair", "tech", "dev", "science", "comedy", "history", "travel",
            "talk", "learner", "news"]


def missing():
    kinds = {c["id"]: c["kind"] for c in json.load(open(DATA / "classes.json"))}
    topics = {c["name"]: c.get("topic") for c in json.load(open(DATA / "channels.json"))}
    have = {p.name.split(".")[0] for p in CAPTIONS.glob("*.vtt")}
    none = set(NONE.read_text().split()) if NONE.exists() else set()
    videos = [v for v in json.load(open(DATA / "videos.json"))
              if kinds.get(v["id"]) == "immersion" and v["id"] not in have and v["id"] not in none]
    rank = {t: k for k, t in enumerate(PRIORITY)}
    return [v["id"] for v in sorted(videos, key=lambda v: rank.get(topics.get(v["channel"]), len(rank)))]


def fetch_once(ids, tried):
    """One yt-dlp run over ids, adding the videos it got through to tried: None when it
    got through all, "stale" when its cookies went stale after at least one video,
    "blocked" when YouTube blocked it."""
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
        f.write("".join(f"https://www.youtube.com/watch?v={i}\n" for i in ids))
    browser = YTDLP_COOKIES or (f"firefox:{FIREFOX_PROFILE}::none" if FIREFOX_PROFILE else None)
    cookies = ["--cookies-from-browser", browser] if browser else []
    if YTDLP_COOKIE_FILE:
        # yt-dlp writes the cookies back when it ends, so each run reads its own copy of
        # the file the browser's machine keeps replacing.
        with open(YTDLP_COOKIE_FILE) as src, tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as jar:
            jar.write(src.read())
        cookies = ["--cookies", jar.name]
    # The TV client answers with one player request and no web page or configs, about a
    # third of the requests of the default clients, and still lists the caption tracks.
    proc = subprocess.Popen(YT_DLP + cookies + [
        "--extractor-args", "youtube:player_client=tv;player_skip=webpage,configs",
        "--skip-download", "--write-sub", "--write-auto-sub", "--sub-lang", "es-orig,es",
        "--sub-format", "vtt", "--sleep-requests", os.environ.get("SLEEP_REQUESTS", "1"),
        "--sleep-subtitles", os.environ.get("SLEEP_SUBTITLES", "2"),
        "--retries", "5", "--extractor-retries", "3", "--ignore-errors",
        "-o", str(CAPTIONS / "%(id)s.%(ext)s"), "-a", f.name],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    current, done = None, 0
    with open(NONE, "a") as none:
        for line in proc.stdout:
            print(line, end="", flush=True)
            if "Extracting URL" in line:
                if current:
                    tried.add(current)
                current, done = line.strip()[-11:], done + 1
            elif BLOCKED in line or any(t in line for t in STALE):
                proc.kill()
                proc.wait()
                os.unlink(f.name)
                if YTDLP_COOKIE_FILE:
                    os.unlink(jar.name)
                result = "stale" if done > 1 and BLOCKED not in line else "blocked"
                print(f"{result} after {done} videos", flush=True)
                return result
            elif current and any(t in line for t in NO_TRACK):
                none.write(current + "\n")
                none.flush()
    proc.wait()
    os.unlink(f.name)
    if YTDLP_COOKIE_FILE:
        os.unlink(jar.name)
    if current:
        tried.add(current)
    return None


def fetch(shard="0/1"):
    """Try every immersion video without captions once, BATCH videos per yt-dlp run,
    pausing BLOCK_PAUSE whenever YouTube blocks; videos that fail for another reason are
    left for the next fetch. Shard k/n takes the videos whose id hashes to k of n, so n
    processes can share the work; SLEEP_REQUESTS and SLEEP_SUBTITLES set yt-dlp's pauses
    in seconds."""
    CAPTIONS.mkdir(parents=True, exist_ok=True)
    k, n = map(int, shard.split("/"))
    tried = set()
    while True:
        ids = [i for i in missing() if zlib.crc32(i.encode()) % n == k and i not in tried]
        print(f"{len(ids)} videos left", flush=True)
        if not ids:
            return
        if fetch_once(ids[:BATCH], tried) == "blocked":
            time.sleep(BLOCK_PAUSE)


def export_cookies(path):
    """Write the browser's YouTube and Google cookies (YTDLP_COOKIES) to path as a
    cookies.txt file, replacing it in one step so a reader never sees half of it."""
    from yt_dlp.cookies import YoutubeDLCookieJar, extract_cookies_from_browser
    name, _, rest = YTDLP_COOKIES.partition(":")
    browser, _, keyring = name.partition("+")
    jar = extract_cookies_from_browser(browser, rest or None, keyring=keyring.upper() or None)
    out = YoutubeDLCookieJar(path + ".new")
    for cookie in jar:
        if cookie.domain.endswith(("youtube.com", "google.com")):
            out.set_cookie(cookie)
    out.save(ignore_discard=True, ignore_expires=True)
    os.chmod(path + ".new", 0o600)
    os.replace(path + ".new", path)


if __name__ == "__main__":
    {"list": list_videos, "fetch": fetch, "cookies": export_cookies}[sys.argv[1]](*sys.argv[2:])
