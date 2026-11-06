"""Run a model task over batch files with Claude Code's `claude -p`.

  python claude_batches.py <task.md> <batches dir> <out dir> <model> [jobs] [limit]

Every batch (a JSON array whose items carry a "key") goes to the model with the task
file (TRANSLATE.md, SENTENCES.md, PRONOMINAL.md); the reply must be a JSON array with
one object per item, the same keys in the same order, and is written to the out dir
under the batch's name. A batch whose output is already there and valid is skipped, so
a rerun picks up only what failed or is new. The merge step of the pipeline file that
wrote the batches folds the outputs in.

`claude -p` uses the account of the Claude Code configuration it runs with
(CLAUDE_CONFIG_DIR), without tools, in a scratch directory.
"""

import concurrent.futures
import json
import pathlib
import subprocess
import sys
import tempfile

PROMPT = """{task}

Reply with the JSON array itself, nothing before or after it; there is no file to write.

The batch:
{batch}"""


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
        with tempfile.TemporaryDirectory() as scratch:
            r = subprocess.run(["claude", "-p", "--model", model, "--output-format", "json", "--tools", ""],
                               input=prompt, capture_output=True, text=True, cwd=scratch, timeout=1800)
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
