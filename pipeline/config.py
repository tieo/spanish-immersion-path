"""Where the pipeline keeps its files and finds the tools it borrows.

data/ holds what the repository publishes: the video list, the classification, the
playlist order with its scores. build/ (not committed) holds everything derived from the
videos' captions, which are the channels' text and stay out of the repository.

Paths to local resources come from environment variables:
  SIP_BUILD          build directory (default: <repo>/build)
  SIP_CAPTIONS       caption files (default: <build>/captions)
  FIREFOX_PROFILE    Firefox/Zen profile with a signed-in YouTube session
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
PHONETIX_ES_DICT = os.environ.get("PHONETIX_ES_DICT")
PIPER_VOICES = Path(os.environ.get("PIPER_VOICES", BUILD / "voices"))
