"""The talk unit: a spoken conversation in Spanish with Claude, over MCP.

Claude calls start_conversation when the learner asks for Spanish practice, holds the
conversation by the instructions it returns, and calls end_conversation at the end with
the errors worth remembering. The learner's level, the words they are learning right
now and the topics of the videos they watched last shape the conversation; errors that
come back session after session are named so the next session can work on them.

Correction follows the evidence on feedback in conversation: errors that block
understanding are corrected on the spot, by prompting the learner to try again before
giving the form (prompts lead to more repair than recasts, Lyster & Ranta 1997; Lyster &
Saito 2010); small slips are collected for a short summary at the end, so the
conversation keeps flowing.
"""

import json
import time

from mcp.server.fastmcp import FastMCP

RECENT_WORDS = 30
RECENT_TOPICS = 5
RECURRING = 3
LEVEL_SPEECH = [
    "superbeginner: very short sentences, present tense, the most common words, speak slowly",
    "beginner: short sentences, present and simple past, common words, speak slowly and clearly",
    "intermediate: natural sentences at a moderate pace, all common tenses, explain rarer words in Spanish",
    "advanced: natural speech at normal pace, idioms welcome",
]

INSTRUCTIONS = """You are the learner's Spanish conversation partner in a spoken conversation.

- Speak only Spanish, matched to their level: {speech}.
- Leave them most of the talking: ask open questions, react to what they say, follow
  their interests. Draw on the topics of their recent videos when the talk needs one.
- Use some of the words they are learning right now, naturally, never as a drill.
- When they do not understand, say it again more simply in Spanish. Explain in English
  only when they still do not understand, or when they ask; keep it short, then go
  back to Spanish.
- Correct only grave errors: those that change or block the meaning, and errors from
  their recurring list. Prompt them to try again first ("¿Cómo se dice...?",
  "¿Ayer...?"), then give the right form if they cannot find it, and carry on.
- Let small slips pass during the conversation and note them. At the end, give a
  short summary in Spanish of up to three things to work on, each with the right form.
- When the learner ends the conversation, call end_conversation with the errors you
  noted.
"""


def make(store, catalog):
    mcp = FastMCP("spanish-immersion", stateless_http=True)

    @mcp.tool()
    def start_conversation() -> dict:
        """Start a Spanish conversation practice session with the learner. Call this when
        the learner wants to practise speaking Spanish, then follow the instructions it
        returns for the whole conversation."""
        level = store.level if store.level is not None else 0.0
        open_unit = store.open_unit()
        if open_unit:
            store.abandon(open_unit["id"])
        entry = store.start("talk", "talk", "talk")
        notes = [r["note"] for r in store.db.execute(
            "select note from introduced order by at desc limit ?", (RECENT_WORDS,))]
        topics = [catalog.by_id[r["unit"]].title for r in store.recent(20)
                  if r["unit"] in catalog.by_id][:RECENT_TOPICS]
        errors = store.get("talk_errors", [])
        counts = {}
        for e in errors:
            counts[e["kind"]] = counts.get(e["kind"], 0) + 1
        recurring = [k for k, n in sorted(counts.items(), key=lambda x: -x[1]) if n >= 2][:RECURRING]
        speech = LEVEL_SPEECH[max(0, min(3, round(level)))]
        return {
            "session": entry,
            "instructions": INSTRUCTIONS.format(speech=speech),
            "level": round(level, 2),
            "words_learning_now": [n.split("|")[0] for n in notes],
            "recent_video_topics": topics,
            "recurring_errors": recurring,
        }

    @mcp.tool()
    def end_conversation(session: int, minutes: int, errors: list[dict]) -> dict:
        """End the conversation practice session. errors: the errors worth remembering,
        each {"said": what the learner said, "correct": the right form, "kind": a short
        name for the kind of error, e.g. "ser/estar", "preterite vs imperfect",
        "gender agreement"}."""
        open_unit = store.open_unit()
        if not open_unit or open_unit["id"] != session:
            return {"recorded": False, "reason": "no conversation in progress with that session id"}
        store.finish(session, None, False, None, max(0, minutes) * 60, [])
        log = store.get("talk_errors", [])
        log += [{**e, "at": time.time()} for e in errors if isinstance(e, dict) and e.get("kind")]
        store.put("talk_errors", log[-200:])
        return {"recorded": True}

    return mcp
