"""List the channels' videos and download their Spanish captions.

  list    add every video of the channels in data/channels.json to data/videos.json (id,
          title, duration, channel); videos already listed keep their entry. A channel's
          "latest" keeps only that many of its newest videos (news channels upload
          thousands of clips)
  fetch [k/n]  download the Spanish caption tracks of the immersion videos that have none
               yet, the liked topics first, waiting out YouTube's blocks; with k/n, only
               shard k of n

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

from config import CAPTIONS, DATA, FIREFOX_PROFILE, YTDLP_COOKIES

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
            "Video unavailable. This video", "Private video")
# YouTube blocks an address for up to an hour once it asks too much.
BLOCKED = "rate-limited"
BLOCK_PAUSE = 3600
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


def fetch_once(ids):
    """One yt-dlp run over ids; True when YouTube blocked it before the end."""
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
        f.write("".join(f"https://www.youtube.com/watch?v={i}\n" for i in ids))
    browser = YTDLP_COOKIES or (f"firefox:{FIREFOX_PROFILE}::none" if FIREFOX_PROFILE else None)
    cookies = ["--cookies-from-browser", browser] if browser else []
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
                current, done = line.strip()[-11:], done + 1
            elif BLOCKED in line:
                proc.kill()
                print(f"blocked after {done} videos", flush=True)
                return True
            elif current and any(t in line for t in NO_TRACK):
                none.write(current + "\n")
                none.flush()
    proc.wait()
    return False


def fetch(shard="0/1"):
    """Download until every immersion video has captions or is known to have none,
    pausing BLOCK_PAUSE whenever YouTube blocks; shard k/n takes every n-th video from the
    k-th, so n processes can share the work; SLEEP_REQUESTS and SLEEP_SUBTITLES set
    yt-dlp's pauses in seconds."""
    CAPTIONS.mkdir(parents=True, exist_ok=True)
    k, n = map(int, shard.split("/"))
    while True:
        ids = missing()[k::n]
        print(f"{len(ids)} videos without captions", flush=True)
        if not ids or not fetch_once(ids):
            return
        time.sleep(BLOCK_PAUSE)


if __name__ == "__main__":
    {"list": list_videos, "fetch": fetch}[sys.argv[1]](*sys.argv[2:])
