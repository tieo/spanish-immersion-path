"""Run a model task over batch files with Claude Code's `claude -p`.

  python claude_batches.py <task.md> <batches dir> <out dir> <model> [jobs] [limit]

Every batch (a JSON array whose items carry a "key") goes to the model with the task
file (TRANSLATE.md, SENTENCES.md, PRONOMINAL.md); the reply must be a JSON array with
one object per item, the same keys in the same order, and is written to the out dir
under the batch's name. A batch whose output is already there and valid is skipped, so
a rerun picks up only what failed or is new. The merge step of the pipeline file that
wrote the batches folds the outputs in.

`claude -p` uses the account of the Claude Code configuration it runs with
(CLAUDE_CONFIG_DIR), without tools, MCP servers or the user's settings (BARE), in a
scratch directory. Paseo's agent-sync keeps part of each account's usage window for the
user and for keeping agents' caches warm, and publishes per account how many points its
fullest window has left before that part (ZONES, rewritten every minute). A request
starts only while that room covers it and every request already in flight at
PER_REQUEST points each, so fewer run at once as the room shrinks and the last ones
finish before the kept part; a state older than STALE counts as no room.
"""

import concurrent.futures
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import threading
import time

PROMPT = """{task}

Reply with the JSON array itself, nothing before or after it; there is no file to write.

The batch:
{batch}"""


ZONES = pathlib.Path.home() / ".paseo" / "claude-switch-state.json"
# Points of the account's window one request may take: a Haiku batch costs about $1,
# which is about 2 points of the work account's 5-hour window.
PER_REQUEST = 2.5
STALE = 180
POLL = 60
lock = threading.Lock()
in_flight = 0


def seat():
    config = os.environ.get("CLAUDE_CONFIG_DIR", "")
    return "personal" if os.path.realpath(config) == os.path.realpath(pathlib.Path.home() / ".claude-personal") else "work"


def room():
    """Points the account has left before agent-sync keeps it, 0 when unknown."""
    try:
        zone = json.load(open(ZONES, encoding="utf-8"))["zones"][seat()]
    except (OSError, ValueError, KeyError):
        return 0
    if zone.get("kept") or time.time() - zone.get("at", 0) / 1000 > STALE:
        return 0
    return zone.get("room", 0)


def start_request():
    """Wait until the account has room for one more request, and count it in flight."""
    global in_flight
    with lock:
        while (left := room()) < (in_flight + 1) * PER_REQUEST:
            print(f"{seat()} account: {left} points of room, {in_flight} in flight, waiting",
                  file=sys.stderr, flush=True)
            time.sleep(POLL)
        in_flight += 1


def end_request():
    global in_flight
    with lock:
        in_flight -= 1


# Without tools, MCP servers, skills, the user's settings and hooks: the task file and the
# batch are the whole prompt. Each MCP server's tool schemas otherwise ride along in every
# request (one reverse-engineering server's alone are some 300k tokens).
BARE = ["--tools", "", "--strict-mcp-config", "--disable-slash-commands", "--setting-sources", "project"]


class Stopped(Exception):
    """claude -p answered with an error instead of a reply, such as a usage limit."""


def valid(path, items):
    try:
        out = json.load(open(path, encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(out, list) and [o.get("key") for o in out] == [i["key"] for i in items]


def one(batch, task, out_dir, model):
    items = json.load(open(batch, encoding="utf-8"))
    out = out_dir / batch.name
    if valid(out, items):
        return batch.name, "done"
    prompt = PROMPT.format(task=task, batch=json.dumps(items, ensure_ascii=False, indent=1))
    error = ""
    for _ in range(3):
        start_request()
        try:
            with tempfile.TemporaryDirectory() as scratch:
                r = subprocess.run(["claude", "-p", "--model", model, "--output-format", "json", *BARE],
                                   input=prompt, capture_output=True, text=True, cwd=scratch, timeout=1800)
        finally:
            end_request()
        try:
            reply = json.loads(r.stdout)
            text = reply["result"]
            # The account's usage limit, or another refusal of the whole run: retrying or
            # going on with the next batch gets the same answer.
            if reply.get("is_error"):
                raise Stopped(text)
            out.write_text(text[text.index("["): text.rindex("]") + 1], encoding="utf-8")
            if valid(out, items):
                return batch.name, f"ok, {reply.get('total_cost_usd', 0):.2f} $ equivalent"
            error = "keys differ from the batch"
        except (ValueError, KeyError) as e:
            error = f"{e}: {r.stdout[:200]} {r.stderr[:200]}"
    out.unlink(missing_ok=True)
    return batch.name, f"FAILED {error}"


def main(task, batches, out_dir, model, jobs="4", limit=None):
    task = open(task, encoding="utf-8").read()
    out_dir = pathlib.Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    todo = sorted(pathlib.Path(batches).glob("batch_*.json"))[: int(limit) if limit else None]
    with concurrent.futures.ThreadPoolExecutor(int(jobs)) as pool:
        futures = [pool.submit(one, b, task, out_dir, model) for b in todo]
        for future in futures:
            try:
                name, status = future.result()
            except Stopped as e:
                for f in futures:
                    f.cancel()
                sys.exit(f"stopped: {e}")
            print(name, status, flush=True)


if __name__ == "__main__":
    main(*sys.argv[1:])
