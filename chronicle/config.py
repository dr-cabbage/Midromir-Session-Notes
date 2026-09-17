"""Loads config.yaml and .env (API keys) for the scribe."""
from __future__ import annotations

import os
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent          # repo root
DATA_FILE = ROOT / "data" / "campaign.json"
RECORDINGS_DIR = ROOT / "recordings"
TRANSCRIPTS_DIR = ROOT / "transcripts"
DRAFTS_DIR = ROOT / "drafts"

DEFAULTS = {
    "claude_model": "claude-sonnet-5",
    "notes_style": "Lively and a little funny, like a party member keeping a journal. Past tense.",
    "dm_context": "",
    "speakers": {},
    "whisper": {
        "model": "small.en",
        "device": "auto",
        "language": "en",
        "initial_prompt": "",
    },
    "recording": {
        "sample_rate": 16000,
        "my_name": "Me",
    },
    "review_before_publish": True,
    "auto_push": True,
    "keep_transcripts_in_git": False,
}


def _deep_merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_env() -> None:
    """Minimal .env loader: KEY=value lines, no overwriting real env vars."""
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        val = val.strip().strip('"').strip("'")
        os.environ.setdefault(key.strip(), val)


def load_config() -> dict:
    load_env()
    cfg_file = ROOT / "config.yaml"
    user = {}
    if cfg_file.exists():
        user = yaml.safe_load(cfg_file.read_text(encoding="utf-8")) or {}
    return _deep_merge(DEFAULTS, user)
