"""Asks Claude to turn a transcript into structured session notes."""
from __future__ import annotations

import json
import os

TOOL_NAME = "record_session_notes"

_note = {"type": "string", "description": "What happened with them this session (1-3 sentences)."}

NOTES_SCHEMA = {
    "type": "object",
    "properties": {
        "session": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Short, punchy episode title (3-7 words)."},
                "summary": {"type": "string", "description": "One or two sentence teaser for the session list."},
                "recap": {
                    "type": "array", "items": {"type": "string"},
                    "description": "The full recap as paragraphs, in story order. Canon only. Aim for 5-12 paragraphs.",
                },
                "highlights": {
                    "type": "array", "items": {"type": "string"},
                    "description": "Best moments: big rolls, jokes, clutch saves, bad ideas.",
                },
                "decisions": {
                    "type": "array", "items": {"type": "string"},
                    "description": "Important choices the party made that could matter later.",
                },
                "cliffhanger": {"type": "string", "description": "Where things stand at the end of the session."},
                "in_game_days": {"type": "string", "description": "In-world time that passed, if clear."},
                "table_talk": {
                    "type": "array", "items": {"type": "string"},
                    "description": "Funniest out-of-character tangents and bits that did NOT happen in-game. Label who said it.",
                },
                "uncertain": {
                    "type": "array", "items": {"type": "string"},
                    "description": "Short questions about things you couldn't confirm happened in-game (left out of the recap).",
                },
            },
            "required": ["title", "summary", "recap", "highlights", "cliffhanger"],
        },
        "party_updates": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Character name, exactly as in the known party list."},
                    "level": {"type": "integer", "description": "Only if they levelled up this session."},
                    "status": {"type": "string", "description": "Only if changed: e.g. active, dead, missing, cursed."},
                    "note": _note,
                },
                "required": ["name", "note"],
            },
        },
        "npcs": {
            "type": "array",
            "description": "Every named non-player character who appeared or was discussed.",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Reuse the exact known name if they already exist."},
                    "role": {"type": "string", "description": "e.g. innkeeper, cult leader, talking cat."},
                    "disposition": {"type": "string", "enum": ["ally", "friendly", "neutral", "suspicious", "hostile", "unknown"]},
                    "status": {"type": "string", "description": "alive, dead, missing, unknown..."},
                    "description": {"type": "string", "description": "Who they are, for someone who forgot. Only for new NPCs or if it changed."},
                    "location": {"type": "string"},
                    "note": _note,
                },
                "required": ["name", "note"],
            },
        },
        "locations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "note": _note,
                },
                "required": ["name", "note"],
            },
        },
        "quests": {
            "type": "array",
            "description": "Goals and jobs the party is pursuing.",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Reuse the exact known title if it exists."},
                    "action": {"type": "string", "enum": ["start", "update", "complete", "fail"]},
                    "description": {"type": "string"},
                    "giver": {"type": "string"},
                    "note": _note,
                },
                "required": ["title", "action", "note"],
            },
        },
        "mysteries": {
            "type": "array",
            "description": "Unanswered questions, secrets and plot threads.",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Phrase as a question. Reuse known titles."},
                    "action": {"type": "string", "enum": ["open", "clue", "resolve"]},
                    "description": {"type": "string"},
                    "clue": {"type": "string", "description": "New information learned."},
                    "resolution": {"type": "string", "description": "The answer, if resolved."},
                },
                "required": ["title", "action"],
            },
        },
        "loot": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "item": {"type": "string"},
                    "holder": {"type": "string", "description": "Who has it (character name or 'party')."},
                    "description": {"type": "string"},
                },
                "required": ["item"],
            },
        },
        "kills": {
            "type": "array",
            "description": "Enemies killed or knocked out, credited to whoever landed the final blow if known.",
            "items": {
                "type": "object",
                "properties": {
                    "character": {"type": "string", "description": "Party character name, or 'party' if unclear."},
                    "creature": {"type": "string"},
                    "count": {"type": "integer"},
                },
                "required": ["character", "creature", "count"],
            },
        },
        "quotes": {
            "type": "array",
            "description": "2-6 of the funniest or most memorable lines, lightly cleaned up.",
            "items": {
                "type": "object",
                "properties": {
                    "speaker": {"type": "string", "description": "Character name if in character, else player name."},
                    "text": {"type": "string"},
                },
                "required": ["speaker", "text"],
            },
        },
    },
    "required": ["session", "party_updates", "npcs", "quests", "mysteries", "loot", "kills", "quotes"],
}


def build_context(campaign: dict, session_number: int) -> str:
    """Everything Claude should know about the campaign so far."""
    party = [
        {k: p.get(k) for k in ("name", "player", "race", "class", "level", "status") if p.get(k) is not None}
        for p in campaign.get("party", [])
    ]
    npcs = [f"{n['name']} ({n.get('role', '?')}, {n.get('status', 'unknown')})" for n in campaign.get("npcs", [])]
    places = [l["name"] for l in campaign.get("locations", [])]
    quests = [f"{q['name']} [{q.get('status')}]" for q in campaign.get("quests", [])]
    mysteries = [f"{m['title']} [{m.get('status')}]" for m in campaign.get("mysteries", [])]
    earlier = [s for s in campaign.get("sessions", []) if s.get("number", 0) < session_number]
    earlier.sort(key=lambda s: s["number"])
    recent = [
        {"number": s["number"], "title": s.get("title"), "summary": s.get("summary"),
         "cliffhanger": s.get("cliffhanger")}
        for s in earlier[-3:]
    ]
    ctx = {
        "campaign": campaign.get("campaign", {}),
        "party": party,
        "known_npcs": npcs,
        "known_locations": places,
        "known_quests": quests,
        "known_mysteries": mysteries,
        "recent_sessions": recent,
    }
    return json.dumps(ctx, indent=2, ensure_ascii=False)


CANON_RULES = """How to tell what really happened (this table goes on a LOT of tangents):
- CANON = things the DM narrates or confirms, actions a player declares that the DM then resolves
  (rolls, "you do X", NPC reactions), and consequences that stick in later scenes.
- NOT CANON = hypotheticals ("what if we just...", "imagine if"), jokes about doing something that the
  DM never resolved, plans the party talked about but abandoned, retcons ("wait, no, I don't do that"),
  movie/TV/meme references, real-life chat, rules arguments, and anything the DM shoots down.
- When a player says something outrageous, check whether the DM picked it up. If the DM rolled with it,
  it's canon (and probably a highlight). If everyone laughed and moved on, it's table talk.
- Funny non-canon moments are still valuable: put them in session.table_talk, never in the recap.
- If you genuinely can't tell whether something happened in-game, leave it out of the recap and add
  a short question to session.uncertain so the reviewer can confirm it.
- Later statements beat earlier ones: if the DM corrects something, use the correction."""


def build_prompt(campaign: dict, transcript: str, session_number: int, cfg: dict) -> tuple[str, str]:
    system = (
        "You are the party's chronicler for a Dungeons & Dragons campaign played over Discord. "
        "You turn raw, messy session transcripts into session notes that are accurate AND fun to read: "
        "someone who missed the session should understand exactly what happened, and laugh.\n\n"
        "Rules:\n"
        "- Speech-to-text makes mistakes, especially with fantasy names. When a garbled word is "
        "clearly a known name from the campaign context, use the known spelling.\n"
        "- Transcript lines are labelled by speaker when available. Speakers are players or the DM; "
        "map players to their characters using the party list. The DM voices every NPC. "
        "A speaker labelled 'Table' is several people mixed on one track; work out who is talking from context.\n"
        "- Never invent events, dialogue or outcomes. Comedy comes from what actually happened, "
        "told with good timing, not from made-up jokes.\n"
        "- Reuse exact names/titles from the campaign context for existing NPCs, places, quests and mysteries "
        "so they merge correctly.\n"
        "- The recap is the informative part: clear story order, who did what, why it matters. "
        "Keep it punchy; a wry aside per paragraph is plenty.\n"
        f"- Writing style: {cfg.get('notes_style')}\n\n"
        f"{CANON_RULES}\n"
    )
    if cfg.get("dm_context"):
        system += f"\nExtra context from the group:\n{cfg['dm_context']}\n"
    user = (
        f"<campaign_context>\n{build_context(campaign, session_number)}\n</campaign_context>\n\n"
        f"<transcript session=\"{session_number}\">\n{transcript}\n</transcript>"
    )
    return system, user


def build_revision(revision: dict | None, session_number: int) -> str:
    """Instructions that follow the (cached) transcript block."""
    if not revision:
        return f"Write the notes for session {session_number} by calling {TOOL_NAME}."
    parts = [
        f"You already drafted notes for session {session_number}. A player who was at the table reviewed them. "
        "Their feedback is ground truth: it overrides your reading of the transcript.",
    ]
    if revision.get("draft"):
        parts.append(
            "<reviewed_draft>\n" + json.dumps(revision["draft"], indent=1, ensure_ascii=False) +
            "\n</reviewed_draft>\nThe reviewer may have hand-edited this draft. Keep their edits unless the "
            "feedback says otherwise."
        )
    removed = revision.get("removed") or []
    if removed:
        parts.append(
            "<removed_by_reviewer>\n" + "\n".join(f"- {r}" for r in removed) +
            "\n</removed_by_reviewer>\nThese did NOT happen in-game or aren't wanted. Leave them (and anything that "
            "depends on them) out of every part of the notes."
        )
    notes = [n for n in (revision.get("notes") or []) if n.strip()]
    if notes:
        parts.append("<reviewer_corrections>\n" + "\n".join(f"- {n}" for n in notes) + "\n</reviewer_corrections>")
    parts.append(f"Rewrite the full notes with this feedback applied by calling {TOOL_NAME}.")
    return "\n\n".join(parts)


class NotesError(RuntimeError):
    pass


LIST_KEYS = ("party_updates", "npcs", "locations", "quests", "mysteries", "loot", "kills", "quotes")


def repair_notes(notes) -> dict:
    """Fix drafts where the model packed fields into JSON strings.

    Seen in the wild: {"session": "{...session...}, \"party_updates\": [...], ...}"}
    i.e. the rest of the object leaked into the session string.
    """
    if isinstance(notes, str):
        notes = _loads_lenient("notes", notes) or {}
    if not isinstance(notes, dict):
        return {}
    out = {}
    for key, val in notes.items():
        if isinstance(val, str) and val.lstrip()[:1] in "{[":
            parsed = _loads_lenient(key, val)
            if parsed is not None:
                if isinstance(parsed, dict) and key in parsed and len(parsed) > 1:
                    out.update(parsed)          # leaked siblings came along
                else:
                    out[key] = parsed
                continue
        out.setdefault(key, val)
    sess = out.get("session")
    if isinstance(sess, dict):
        for k in ("recap", "highlights", "decisions", "table_talk", "uncertain"):
            v = sess.get(k)
            if isinstance(v, str) and v.lstrip()[:1] == "[":
                try:
                    sess[k] = json.loads(v)
                except json.JSONDecodeError:
                    pass
    for k in LIST_KEYS:
        v = out.get(k)
        if isinstance(v, str) and v.lstrip()[:1] == "[":
            try:
                out[k] = json.loads(v)
            except json.JSONDecodeError:
                pass
    return out


def _loads_lenient(key: str, text: str):
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    try:  # '{...}, "other_key": [...] }'  ->  wrap it back into the parent object
        return json.loads('{"%s": %s' % (key, text))
    except json.JSONDecodeError:
        return None


def notes_problems(notes: dict) -> list[str]:
    problems = []
    sess = notes.get("session")
    if not isinstance(sess, dict):
        return ["the session section is missing or malformed"]
    if not sess.get("title"):
        problems.append("no title")
    if not isinstance(sess.get("recap"), list) or not sess.get("recap"):
        problems.append("no recap paragraphs")
    for k in LIST_KEYS:
        if k in notes and not isinstance(notes[k], list):
            problems.append(f"{k} is not a list")
    return problems


def write_notes(campaign: dict, transcript: str, session_number: int, cfg: dict,
                revision: dict | None = None) -> dict:
    try:
        import anthropic
    except ImportError as exc:  # pragma: no cover
        raise NotesError("Note writing needs the Anthropic SDK: pip install anthropic") from exc

    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise NotesError("ANTHROPIC_API_KEY is not set. Put it in the .env file (see README).")

    system, user = build_prompt(campaign, transcript, session_number, cfg)
    client = anthropic.Anthropic()
    model = cfg.get("claude_model", "claude-sonnet-5")
    verb = "rewrite" if revision else "write"
    print(f"Asking {model} to {verb} the notes ({len(transcript):,} characters of transcript) ...")

    instructions = build_revision(revision, session_number) + (
        "\n\nFill every field of the tool input as real JSON objects and arrays. "
        "Never put JSON inside a string."
    )
    last_problems: list[str] = []
    for attempt in (1, 2):
        extra = ""
        if last_problems:
            extra = ("\n\nYour previous attempt was unusable (" + "; ".join(last_problems) +
                     "). Call the tool again with every field filled in as proper JSON, not strings.")
        try:
            with client.messages.stream(
                model=model,
                max_tokens=32000,
                system=system,
                tools=[{
                    "name": TOOL_NAME,
                    "description": "Save the structured notes for one D&D session.",
                    "input_schema": NOTES_SCHEMA,
                }],
                tool_choice={"type": "tool", "name": TOOL_NAME},
                messages=[{"role": "user", "content": [
                    # the transcript is cached, so regenerating after review is cheap
                    {"type": "text", "text": user, "cache_control": {"type": "ephemeral"}},
                    {"type": "text", "text": instructions + extra},
                ]}],
            ) as stream:
                message = stream.get_final_message()
        except Exception as exc:
            raise NotesError(f"Claude request failed: {exc}") from exc

        usage = message.usage
        print(f"  done ({usage.input_tokens:,} tokens in, {usage.output_tokens:,} out, stop: {message.stop_reason})")
        if message.stop_reason == "max_tokens":
            print("  Warning: the notes hit the length limit and may be cut short.")
        raw = next((b.input for b in message.content
                    if b.type == "tool_use" and b.name == TOOL_NAME), None)
        if raw is None:
            last_problems = ["no notes were returned"]
        else:
            notes = repair_notes(raw)
            last_problems = notes_problems(notes)
            if not last_problems:
                return notes
        print(f"  The notes came back unusable ({'; '.join(last_problems)})."
              + (" Retrying once..." if attempt == 1 else ""))
    raise NotesError("Claude's notes came back unusable twice (" + "; ".join(last_problems) + "). Try again.")
