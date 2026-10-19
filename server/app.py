"""The learner's app: next unit, ratings, placement test, Anki, over HTTP, and the MCP
endpoint (/mcp) Claude uses for the talk unit.

Environment:
  SIP_DATA      the repository's data/ directory (units.json)
  SIP_STATE     writable state directory: learner.db, the Anki collection copy, and
                placement.json from pipeline/placement.py
  ANKIWEB_HKEY  AnkiWeb sync key (pipeline/progress.py hostkey), or ANKIWEB_HKEY_FILE
                naming a file that holds it; without either Anki is left alone
  PORT          port on 127.0.0.1 (default 8097)

Run: python -m server.app
"""

import os
import time
from pathlib import Path

import uvicorn
from starlette.concurrency import run_in_threadpool
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from . import collection, picker, tutor
from .catalog import Catalog
from .placement import Placement
from .state import Store

DATA = Path(os.environ.get("SIP_DATA", Path(__file__).resolve().parent.parent / "data"))
STATE = Path(os.environ.get("SIP_STATE", Path(__file__).resolve().parent.parent / "build" / "server"))
STATIC = Path(__file__).resolve().parent / "static"
STATE.mkdir(parents=True, exist_ok=True)

catalog = Catalog(DATA / "units.json")
store = Store(STATE / "learner.db")
placement = Placement(STATE / "placement.json")
anki = collection.connect(str(STATE))


def ok(data):
    return JSONResponse(data)


def state(request):
    open_unit = store.open_unit()
    if open_unit and open_unit["kind"] == "video" and open_unit["unit"] in catalog.by_id:
        open_unit = {**catalog.by_id[open_unit["unit"]].public(), **open_unit}
    return ok({
        "level": store.level,
        "vocab_threshold": store.get("vocab_threshold"),
        "placement": store.get("placement_result"),
        "open": open_unit,
        "seconds": store.seconds_done(),
        "units_done": len(store.done()),
        "units": len(catalog.units),
        "words_introduced": len(store.introduced()),
        "anki": anki.status(),
        "modes": {m: m in picker.AVAILABLE for m in picker.MODES},
    })


def next_unit(request):
    mode = request.query_params.get("mode", "best")
    if mode not in picker.MODES:
        return JSONResponse({"error": f"unknown mode {mode}"}, status_code=400)
    if mode == "best":
        anki.sync()
    return ok(picker.pick(mode, catalog, store, anki.status()))


async def start(request):
    body = await request.json()
    open_unit = store.open_unit()
    if open_unit:
        store.abandon(open_unit["id"])
    entry = store.start(body["unit"], body["kind"], body.get("mode"))
    return ok({"entry": entry})


async def finish(request):
    body = await request.json()
    open_unit = store.open_unit()
    if not open_unit or open_unit["id"] != body["entry"]:
        return JSONResponse({"error": "no such unit in progress"}, status_code=409)
    seconds = int(time.time() - open_unit["started"])
    words = []
    if open_unit["kind"] == "video":
        unit = catalog.by_id[open_unit["unit"]]
        seconds = min(seconds, unit.duration or seconds)
        if body.get("rating"):
            store.rate(unit.level, body["rating"])
        words = catalog.new_words(unit, store.known(catalog), store.introduced(), picker.NEW_WORDS)
        await run_in_threadpool(anki.introduce, words)
        store.introduce(words, unit.id)
    elif open_unit["kind"] == "anki":
        await run_in_threadpool(anki.sync)
    store.finish(open_unit["id"], body.get("rating"), body.get("boring", False), body.get("note"),
                 seconds, words)
    return ok({"words": words, "level": store.level})


async def abandon(request):
    body = await request.json()
    store.abandon(body["entry"])
    return ok({})


def vocab_items(request):
    return ok({"items": placement.vocab_items()})


async def vocab_answers(request):
    result = placement.score_vocab((await request.json())["answers"])
    store.put("vocab_threshold", result["threshold"])
    store.put("placement_vocab", result)
    session = placement.new_session()
    store.put("placement_session", session)
    return ok({**result, "clip": placement.next_clip(session)})


async def clip_answer(request):
    body = await request.json()
    session = store.get("placement_session")
    result = placement.answer(session, body["clip"], body["typed"])
    store.put("placement_session", session)
    nxt = placement.next_clip(session)
    if nxt is None:
        level = placement.listening_level(session)
        store.put("level", level)
        store.put("placement_result", {"level": level, "vocab": store.get("placement_vocab"),
                                       "trials": session["trials"], "at": time.time()})
        return ok({**result, "done": True, "level": level})
    return ok({**result, "done": False, "clip": nxt})


def index(request):
    return FileResponse(STATIC / "index.html")


# The MCP endpoint for the talk unit (/mcp) comes with the Starlette app FastMCP builds,
# whose lifespan runs the MCP sessions; the app's own routes join it.
app = tutor.make(store, catalog).streamable_http_app()
app.router.routes.extend([
    Route("/", index),
    Route("/api/state", state),
    Route("/api/next", next_unit),
    Route("/api/start", start, methods=["POST"]),
    Route("/api/finish", finish, methods=["POST"]),
    Route("/api/abandon", abandon, methods=["POST"]),
    Route("/api/placement/vocab", vocab_items),
    Route("/api/placement/vocab", vocab_answers, methods=["POST"]),
    Route("/api/placement/clip", clip_answer, methods=["POST"]),
    Mount("/static", StaticFiles(directory=STATIC)),
])


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("PORT", 8097)))
