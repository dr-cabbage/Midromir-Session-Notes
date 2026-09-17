"""The steps shared by the command line and the review window."""
from __future__ import annotations

import json
from pathlib import Path

from . import merge
from .config import DATA_FILE, DRAFTS_DIR, TRANSCRIPTS_DIR


def transcript_path(n: int) -> Path:
    return TRANSCRIPTS_DIR / f"session-{n:02d}.txt"


def draft_path(n: int) -> Path:
    return DRAFTS_DIR / f"session-{n:02d}.json"


def feedback_path(n: int) -> Path:
    return DRAFTS_DIR / f"session-{n:02d}.feedback.json"


def meta_path(n: int) -> Path:
    return DRAFTS_DIR / f"session-{n:02d}.meta.json"


def _read_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


# --- drafts, feedback and per-session info -------------------------------- #
def load_draft(n: int) -> dict | None:
    from .notewriter import repair_notes
    draft = _read_json(draft_path(n), None)
    if draft is None:
        return None
    fixed = repair_notes(draft)
    if fixed != draft:
        save_draft(n, fixed)
    return fixed


def save_draft(n: int, draft: dict) -> None:
    _write_json(draft_path(n), draft)


def load_feedback(n: int) -> dict:
    """Everything the reviewer has told Claude so far (kept across regenerations)."""
    fb = _read_json(feedback_path(n), {})
    fb.setdefault("removed", [])
    fb.setdefault("notes", [])
    return fb


def save_feedback(n: int, fb: dict) -> None:
    _write_json(feedback_path(n), fb)


def load_meta(n: int) -> dict:
    return _read_json(meta_path(n), {})


def save_meta(n: int, **fields) -> None:
    meta = load_meta(n)
    meta.update({k: v for k, v in fields.items() if v})
    _write_json(meta_path(n), meta)


# --- steps ----------------------------------------------------------------- #
def generate(n: int, cfg: dict, revision: dict | None = None) -> dict:
    """Ask Claude for notes (fresh, or revised with reviewer feedback) and save the draft."""
    from .notewriter import write_notes

    tpath = transcript_path(n)
    if not tpath.exists():
        raise FileNotFoundError(f"No transcript at {tpath}. Run 'process' first.")
    campaign = merge.load_campaign(DATA_FILE)
    fb = load_feedback(n)
    if revision is None and (fb["removed"] or fb["notes"]):
        revision = {"removed": fb["removed"], "notes": fb["notes"]}  # remember earlier reviews
    notes = write_notes(campaign, tpath.read_text(encoding="utf-8"), n, cfg, revision=revision)
    save_draft(n, notes)
    return notes


def apply_draft(n: int, date: str | None = None, source: str | None = None) -> str:
    """Merge the saved draft into data/campaign.json (no git)."""
    notes = load_draft(n)
    if notes is None:
        raise FileNotFoundError(f"No readable draft at {draft_path(n)}.")
    meta = load_meta(n)
    campaign = merge.load_campaign(DATA_FILE)
    existing = next((s for s in campaign["sessions"] if s["number"] == n), None) or {}
    date = date or meta.get("date") or existing.get("date")
    source = source or meta.get("source") or existing.get("source")
    merge.apply_session(campaign, notes, n, date=date, source=source)
    merge.save_campaign(DATA_FILE, campaign)
    title = notes.get("session", {}).get("title", "")
    msg = f"Added session {n} (\"{title}\") to the campaign."
    print(msg)
    return title


def publish_paths(n: int, cfg: dict) -> list[Path]:
    paths = [DATA_FILE, draft_path(n), feedback_path(n), meta_path(n)]
    if cfg.get("keep_transcripts_in_git"):
        paths.append(transcript_path(n))
    return paths
