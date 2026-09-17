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
                    "description": "The full recap as paragraphs, in story order. Aim for 5-12 paragraphs.",
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


def build_prompt(campaign: dict, transcript: str, session_number: int, cfg: dict) -> tuple[str, str]:
    system = (
        "You are the party's chronicler for a Dungeons & Dragons campaign played over Discord. "
        "You turn raw, messy session transcripts into accurate, readable session notes.\n\n"
        "Rules:\n"
        "- Speech-to-text makes mistakes, especially with fantasy names. When a garbled word is "
        "clearly a known name from the campaign context, use the known spelling.\n"
        "- Transcript lines are labelled by speaker when available. Speakers are players or the DM; "
        "map players to their characters using the party list. The DM voices every NPC. A speaker labelled 'Table' is several people mixed on one track; work out who is talking from context.\n"
        "- Separate in-game events from out-of-character table talk. Leave out rules lookups, "
        "snack breaks and scheduling chatter unless they are funny enough for highlights or quotes.\n"
        "- Never invent events. If something is unclear, say so briefly rather than guessing.\n"
        "- Reuse exact names/titles from the campaign context for existing NPCs, places, quests and mysteries "
        "so they merge correctly.\n"
        f"- Writing style for the recap: {cfg.get('notes_style')}\n"
    )
    if cfg.get("dm_context"):
        system += f"\nExtra context from the group:\n{cfg['dm_context']}\n"

    user = (
        f"<campaign_context>\n{build_context(campaign, session_number)}\n</campaign_context>\n\n"
        f"<transcript session=\"{session_number}\">\n{transcript}\n</transcript>\n\n"
        f"Write the notes for session {session_number} by calling {TOOL_NAME}."
    )
    return system, user


def write_notes(campaign: dict, transcript: str, session_number: int, cfg: dict) -> dict:
    try:
        import anthropic
    except ImportError as exc:  # pragma: no cover
        raise SystemExit("Note writing needs the Anthropic SDK: pip install anthropic") from exc

    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise SystemExit("ANTHROPIC_API_KEY is not set. Put it in the .env file (see README).")

    system, user = build_prompt(campaign, transcript, session_number, cfg)
    client = anthropic.Anthropic()
    model = cfg.get("claude_model", "claude-sonnet-5")
    print(f"Asking {model} to write the notes ({len(transcript):,} characters of transcript) ...")

    with client.messages.stream(
        model=model,
        max_tokens=16000,
        system=system,
        tools=[{
            "name": TOOL_NAME,
            "description": "Save the structured notes for one D&D session.",
            "input_schema": NOTES_SCHEMA,
        }],
        tool_choice={"type": "tool", "name": TOOL_NAME},
        messages=[{"role": "user", "content": user}],
    ) as stream:
        message = stream.get_final_message()

    if message.stop_reason == "max_tokens":
        print("Warning: the notes hit the length limit and may be cut short.")
    for block in message.content:
        if block.type == "tool_use" and block.name == TOOL_NAME:
            usage = message.usage
            print(f"  done ({usage.input_tokens:,} tokens in, {usage.output_tokens:,} out)")
            return block.input
    raise SystemExit("Claude didn't return notes. Try running the command again.")
