"""The talk unit: a conversation in Spanish with an AI, and what it tells us.

Spoken conversations run in a voice assistant (Gemini Live, ChatGPT voice). The app hands
the learner a prompt to paste in first: how to talk with them, their level, the words
they are learning right now, the topics of their last videos and their recurring
errors. At the end the assistant writes a result block, which the learner pastes back:
its CEFR estimate of how much they understood and of their own Spanish, the minutes and
the kinds of errors. Written conversations run in Claude sessions with this MCP server:
start_conversation hands over the same instructions, end_conversation reports the same
judgement.

The comprehension estimate of a spoken conversation pulls the learner's level towards
it; errors are remembered so the next conversation can work on the recurring ones; the
production estimates show how speaking and writing follow the input.

Correction follows the evidence on feedback in conversation: errors that block
understanding are corrected on the spot, by prompting the learner to try again before
giving the form (prompts lead to more repair than recasts, Lyster & Ranta 1997; Lyster &
Saito 2010); small slips are collected for a short summary at the end, so the
conversation keeps flowing. Production is judged on the CEFR's qualitative aspects of
language use (range, accuracy, fluency, interaction, coherence).
"""

import re

from mcp.server.fastmcp import FastMCP

from .catalog import cefr, score_of

RECENT_WORDS = 30
RECENT_TOPICS = 5
RECURRING = 3
MAX_MINUTES = 120
LEVEL_SPEECH = [
    "very short sentences, present tense, the most common words, slowly",
    "short sentences, present and simple past, common words, slowly and clearly",
    "natural sentences at a moderate pace, all common tenses, rarer words explained in Spanish",
    "natural language at normal pace, idioms welcome",
]
MEDIUM = {
    "voice": ("a spoken conversation", "It is speech: keep every turn to one or two short "
              "sentences, no lists, no formatting."),
    "text": ("a written chat", "Keep every message short, like a chat between friends."),
}

INSTRUCTIONS = """You are my Spanish conversation partner in {medium}.

- {turns}
- Use only Spanish, matched to my level ({level}): {speech}.
- Leave me most of the talking: ask open questions, react to what I say, follow my
  interests. Use the topics of my recent videos when the talk needs one.
- Use some of the words I am learning right now, naturally, never as a drill.
- When I do not understand, say it again more simply in Spanish. Explain in English
  only when I still do not understand, or when I ask; keep it short, then go back to
  Spanish.
- Correct only grave errors: those that change or block the meaning, and my recurring
  ones. Prompt me to try again first ("¿Cómo se dice...?", "¿Ayer...?"), then give the
  right form if I cannot find it, and carry on.
- Let small slips pass and note them.

When I say "terminamos", stop and judge the conversation honestly, without kindness
inflating it, in CEFR half levels (Pre-A1, A1.1, A1.2, A2.1 ... C1.2, C2):
- comprehension: the level of the Spanish I followed without help, by how much of what
  you said I understood{speed};
- production: the level of my own Spanish, by range, accuracy, fluency, interaction and
  coherence;
- errors: the kinds of errors I made, as short names (ser/estar, gender agreement,
  preterite vs imperfect ...).
"""

RESULT_BLOCK = """Then write exactly this block, filled in, and nothing after it:

RESULT
comprehension: <level>
production: <level>
minutes: <minutes we talked>
errors: <kind>; <kind>; ...
"""

MCP_END = "When I say \"terminamos\", call end_conversation with your judgement."


def context(store, catalog):
    level = store.level
    notes = [r["note"] for r in store.db.execute(
        "select note from introduced order by at desc limit ?", (RECENT_WORDS,))]
    topics = [catalog.by_id[r["unit"]].title for r in store.recent(20) if r["unit"] in catalog.by_id][:RECENT_TOPICS]
    counts = {}
    for e in store.get("talk_errors", []):
        counts[e["kind"]] = counts.get(e["kind"], 0) + 1
    recurring = [k for k, n in sorted(counts.items(), key=lambda x: -x[1]) if n >= 2][:RECURRING]
    return {
        "level": cefr(level),
        "speech": LEVEL_SPEECH[max(0, min(3, round(level)))],
        "words": [n.split("|")[0] for n in notes],
        "topics": topics,
        "recurring": recurring,
    }


def instructions(c, medium):
    name, turns = MEDIUM[medium]
    return INSTRUCTIONS.format(medium=name, turns=turns, level=c["level"], speech=c["speech"],
                               speed=" and at what speed" if medium == "voice" else "")


def prompt(store, catalog):
    """The text the learner pastes into a voice assistant before talking."""
    c = context(store, catalog)
    parts = [instructions(c, "voice")]
    if c["words"]:
        parts.append("Words I am learning right now: " + ", ".join(c["words"]) + ".")
    if c["topics"]:
        parts.append("My recent videos: " + "; ".join(c["topics"]) + ".")
    if c["recurring"]:
        parts.append("My recurring errors: " + "; ".join(c["recurring"]) + ".")
    parts.append(RESULT_BLOCK)
    parts.append("Start now: greet me in Spanish and ask me something.")
    return "\n\n".join(parts)


LEVEL_CODE = re.compile(r"\b(pre-?a1|[abc][12](?:\.[12])?)\b", re.I)


def parse(text):
    """The result block, read leniently: English or Spanish keys, any case, the level
    anywhere on its line."""
    def field(*keys):
        m = re.search(r"^\W*(?:%s)\W*[:=]\s*(.+)$" % "|".join(keys), text or "", re.I | re.M)
        return m.group(1).strip() if m else None

    def level(*keys):
        m = LEVEL_CODE.search(field(*keys) or "")
        if not m:
            return None
        code = m.group(1).upper()
        return "Pre-A1" if code.startswith("PRE") else code
    minutes = re.search(r"\d+", field("minutes", "minutos") or "")
    errors = field("errors", "errores")
    return {
        "comprehension": level("comprehension", "comprensión", "comprension", "listening", "escucha"),
        "production": level("production", "producción", "produccion", "speaking", "habla"),
        "minutes": min(MAX_MINUTES, int(minutes.group())) if minutes else None,
        "errors": [e.strip(" .") for e in re.split(r"[;|]", errors) if e.strip(" .")] if errors else [],
    }


def record(store, source, medium, result, raw):
    store.assess(source, medium, result["comprehension"], result["production"], result["minutes"],
                 result["errors"], raw, score_of(result["comprehension"]))


def make(store, catalog):
    mcp = FastMCP("spanish-immersion", stateless_http=True)

    @mcp.tool()
    def start_conversation() -> dict:
        """Start a written Spanish conversation practice session with the learner. Call
        this when the learner wants to practise Spanish, then follow the instructions it
        returns for the whole conversation."""
        open_unit = store.open_unit()
        if open_unit:
            store.abandon(open_unit["id"])
        entry = store.start("talk", "talk", "text")
        c = context(store, catalog)
        return {
            "session": entry,
            "instructions": instructions(c, "text") + "\n" + MCP_END,
            "level": c["level"],
            "words_learning_now": c["words"],
            "recent_video_topics": c["topics"],
            "recurring_errors": c["recurring"],
        }

    @mcp.tool()
    def end_conversation(session: int, minutes: int, comprehension: str, production: str,
                         errors: list[str]) -> dict:
        """End the conversation practice session with your judgement. comprehension and
        production: CEFR half levels such as "A2.1"; errors: short names of the kinds of
        errors the learner made, e.g. "ser/estar", "gender agreement"."""
        open_unit = store.open_unit()
        if not open_unit or open_unit["id"] != session:
            return {"recorded": False, "reason": "no conversation in progress with that session id"}
        minutes = max(0, min(MAX_MINUTES, minutes))
        store.finish(session, None, False, None, minutes * 60, [])
        result = {"comprehension": comprehension, "production": production, "minutes": minutes,
                  "errors": [e for e in errors if isinstance(e, str)]}
        record(store, "claude", "text", result, None)
        return {"recorded": True, "level_now": cefr(store.level)}

    return mcp
