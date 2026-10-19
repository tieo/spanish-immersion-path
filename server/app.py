"""The learner's app: next unit, ratings, Anki, over HTTP, and the MCP
endpoint (/mcp) Claude uses for the talk unit.

Environment:
  SIP_DATA      the repository's data/ directory (units.json)
  SIP_STATE     writable state directory: learner.db and the Anki collection copy
  ANKIWEB_HKEY  AnkiWeb sync key (pipeline/progress.py hostkey), or ANKIWEB_HKEY_FILE
                naming a file that holds it; without either Anki is left alone
  PORT          port on 127.0.0.1 (default 8097)
  SIP_OAUTH_... who may use /mcp, see oauth.py

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

from . import collection, oauth, picker, tutor
from .catalog import Catalog
from .state import Store

DATA = Path(os.environ.get("SIP_DATA", Path(__file__).resolve().parent.parent / "data"))
STATE = Path(os.environ.get("SIP_STATE", Path(__file__).resolve().parent.parent / "build" / "server"))
STATIC = Path(__file__).resolve().parent / "static"
STATE.mkdir(parents=True, exist_ok=True)

catalog = Catalog(DATA / "units.json")
store = Store(STATE / "learner.db")
anki = collection.connect(str(STATE))
# Words introduced while Anki was unreachable or not yet set up reach it now; cards
# already unsuspended are left as they are.
anki.introduce(store.introduced_in_order())


def ok(data):
    return JSONResponse(data)


def state(request):
    days, streak = activity(anki.stats(1, sync=False), store.finished())
    today = days.get(date(0), {"video": 0, "talk": 0, "anki": 0})
    open_unit = store.open_unit()
    if open_unit and open_unit["kind"] == "video" and open_unit["unit"] in catalog.by_id:
        open_unit = {**catalog.by_id[open_unit["unit"]].public(), **open_unit}
    return ok({
        "level": store.level,
        "open": open_unit,
        "seconds": store.seconds_done(),
        "units_done": len(store.done()),
        "units": len(catalog.units),
        "words_introduced": len(store.introduced()),
        "today_seconds": today["video"] + today["talk"] + today["anki"],
        "streak": streak,
        "learning_now": [n.split("|")[0] for n in store.introduced_in_order()[-12:]],
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
            store.log_level(unit.id, body["rating"])
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


STAT_DAYS = 28


def date(k):
    return time.strftime("%Y-%m-%d", time.localtime(time.time() - k * 86400))


def activity(anki_stats, finished):
    """Seconds per local date by kind (video, talk, anki) and Anki reviews, and the
    number of days in a row with any Spanish, counted back from today, or from
    yesterday while today is still empty."""
    days = {}
    for r in finished:
        day = time.strftime("%Y-%m-%d", time.localtime(r["finished"]))
        d = days.setdefault(day, {"video": 0, "talk": 0, "anki": 0, "reviews": 0})
        if r["kind"] in ("video", "talk"):
            d[r["kind"]] += r["seconds"] or 0
    for day, a in anki_stats["days"].items():
        d = days.setdefault(day, {"video": 0, "talk": 0, "anki": 0, "reviews": 0})
        d["anki"] += a["seconds"]
        d["reviews"] += a["reviews"]

    def active(k):
        d = days.get(date(k))
        return bool(d) and d["video"] + d["talk"] + d["anki"] > 0
    k = 0 if active(0) else 1
    streak = 0
    while active(k):
        streak, k = streak + 1, k + 1
    return days, streak


def stats(request):
    """Everything the stats view shows: level over time, time per day by kind, Anki,
    where the learner stands on the path, recent units and recurring talk errors."""
    anki_stats = anki.stats(STAT_DAYS)
    finished = store.finished()
    days, streak = activity(anki_stats, finished)
    done = store.done()
    level = store.level
    path = [[round(u.level, 2), u.duration or 0, u.id in done] for u in sorted(catalog.units, key=lambda u: u.level)]
    errors = {}
    for e in store.get("talk_errors", []):
        errors[e["kind"]] = errors.get(e["kind"], 0) + 1
    recent = []
    for r in reversed(finished[-15:]):
        u = catalog.by_id.get(r["unit"])
        recent.append({"kind": r["kind"], "title": u.title if u else None, "id": u.id if u else None,
                       "rating": r["rating"], "boring": bool(r["boring"]), "seconds": r["seconds"],
                       "finished": r["finished"]})
    return ok({
        "level": level,
        "level_history": store.level_history(),
        "days": [{"date": date(k), **days.get(date(k), {"video": 0, "talk": 0, "anki": 0, "reviews": 0})}
                 for k in range(STAT_DAYS - 1, -1, -1)],
        "totals": {
            "seconds": sum((r["seconds"] or 0) for r in finished if r["kind"] in ("video", "talk"))
                       + sum(a["seconds"] for a in anki_stats["days"].values()),
            "videos": sum(r["kind"] == "video" for r in finished),
            "talks": sum(r["kind"] == "talk" for r in finished),
            "streak": streak,
        },
        "anki": anki_stats["cards"],
        "path": path,
        "recent": recent,
        "errors": sorted(errors.items(), key=lambda x: -x[1])[:6],
    })


def index(request):
    return FileResponse(STATIC / "index.html")


# The MCP endpoint for the talk unit (/mcp) comes with the Starlette app FastMCP builds,
# whose lifespan runs the MCP sessions; the app's own routes join it.
app = tutor.make(store, catalog).streamable_http_app()
app.router.routes.extend([
    Route("/", index),
    Route("/api/state", state),
    Route("/api/next", next_unit),
    Route("/api/stats", stats),
    Route("/api/start", start, methods=["POST"]),
    Route("/api/finish", finish, methods=["POST"]),
    Route("/api/abandon", abandon, methods=["POST"]),
    Route(oauth.METADATA, oauth.metadata),
    Route(oauth.METADATA + "/mcp", oauth.metadata),
    Mount("/static", StaticFiles(directory=STATIC)),
])
app.add_middleware(oauth.GuardMcp)


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("PORT", 8097)))
