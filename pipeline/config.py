"""Where the pipeline keeps its files and finds the tools it borrows.

data/ holds what the repository publishes: the channel and video lists, the
classification, the playlists. build/ (not committed) holds everything derived from the
videos' captions, which are the channels' text and stay out of the repository.

Paths to local resources come from environment variables:
  SIP_BUILD          build directory (default: <repo>/build)
  SIP_CAPTIONS       caption files (default: <build>/captions)
  FIREFOX_PROFILE    Firefox/Zen profile with a signed-in YouTube session
  YTDLP_COOKIES      the signed-in browser for yt-dlp as a --cookies-from-browser spec
                     (any browser yt-dlp reads), used instead of FIREFOX_PROFILE
  YTDLP_COOKIE_FILE  the same session as a cookies.txt file that `fetch_captions.py
                     cookies` keeps fresh from the browser on another machine; used
                     before either of the above
  PHONETIX_ES_DICT   Spanish IPA dictionary from phonetix (es.json.gz)
  PIPER_VOICES       directory with the Piper voice models
"""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
BUILD = Path(os.environ.get("SIP_BUILD", ROOT / "build"))
CAPTIONS = Path(os.environ.get("SIP_CAPTIONS", BUILD / "captions"))
FIREFOX_PROFILE = os.environ.get("FIREFOX_PROFILE")
YTDLP_COOKIES = os.environ.get("YTDLP_COOKIES")
YTDLP_COOKIE_FILE = os.environ.get("YTDLP_COOKIE_FILE")
PHONETIX_ES_DICT = os.environ.get("PHONETIX_ES_DICT")
# The watching order (levels.py) and the app's catalog (units.py): generated, and too
# large for the repository once the channels hold tens of thousands of videos.
ORDER = BUILD / "order.json"
CATALOG = BUILD / "catalog.npz"
PIPER_VOICES = Path(os.environ.get("PIPER_VOICES", BUILD / "voices"))
