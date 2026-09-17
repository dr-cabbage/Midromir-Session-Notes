"""Merges one session's notes into data/campaign.json.

Re-running a session replaces everything that session added before, so you can
regenerate or hand-edit a session's notes without creating duplicates.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path

EMPTY_CAMPAIGN = {
    "campaign": {"title": "Our Campaign", "subtitle": "", "setting": "", "dm": ""},
    "party": [],
    "npcs": [],
    "locations": [],
    "quests": [],
    "mysteries": [],
    "loot": [],
    "kills": [],
    "quotes": [],
    "sessions": [],
}


def load_campaign(path: Path) -> dict:
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
    else:
        data = {}
    for k, v in EMPTY_CAMPAIGN.items():
        data.setdefault(k, json.loads(json.dumps(v)))
    return data


def save_campaign(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data["updated"] = dt.datetime.now().isoformat(timespec="seconds")
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-") or "item"


def _norm(text: str) -> str:
    t = (text or "").lower().strip()
    t = re.sub(r"^(the|a|an)\s+", "", t)
    return re.sub(r"[^a-z0-9]+", "", t)


def _find(items: list, name: str, key: str = "name"):
    n = _norm(name)
    for it in items:
        names = [it.get(key, "")] + list(it.get("aliases", []))
        if any(_norm(x) == n for x in names):
            return it
    return None


def next_session_number(data: dict) -> int:
    nums = [s.get("number", 0) for s in data.get("sessions", [])]
    return max(nums, default=0) + 1


# --------------------------------------------------------------------------- #
# Undo a session (used before re-applying it)
# --------------------------------------------------------------------------- #
def remove_session(data: dict, n: int) -> None:
    data["sessions"] = [s for s in data["sessions"] if s.get("number") != n]
    for key in ("loot", "kills", "quotes"):
        data[key] = [x for x in data[key] if x.get("session") != n]

    for key in ("party", "npcs", "locations", "quests"):
        kept = []
        for it in data[key]:
            it["log"] = [e for e in it.get("log", []) if e.get("session") != n]
            added_here = it.get("first_seen") == n and not it.get("manual")
            if added_here and not it["log"] and key != "party":
                continue  # this entry only existed because of session n
            if it.get("first_seen") == n and it["log"]:
                it["first_seen"] = min(e["session"] for e in it["log"])
            if it.get("last_seen") == n:
                it["last_seen"] = max((e["session"] for e in it["log"]), default=it.get("first_seen"))
            kept.append(it)
        data[key] = kept

    kept = []
    for m in data["mysteries"]:
        m["clues"] = [c for c in m.get("clues", []) if c.get("session") != n]
        if m.get("resolved") == n:
            m["status"], m["resolved"], m["resolution"] = "open", None, ""
        if m.get("opened") == n and not m["clues"] and not m.get("manual"):
            continue
        kept.append(m)
    data["mysteries"] = kept

    for q in data["quests"]:
        if q.get("closed") == n:
            q["status"], q["closed"] = "active", None


# --------------------------------------------------------------------------- #
# Apply a session
# --------------------------------------------------------------------------- #
def _upsert(items: list, name: str, n: int, fields: dict, note: str | None) -> dict:
    it = _find(items, name)
    if it is None:
        it = {"id": slug(name), "name": name.strip(), "first_seen": n, "log": []}
        items.append(it)
    for k, v in fields.items():
        if v in (None, ""):
            continue
        if k == "description" and it.get("description") and it.get("manual"):
            continue  # don't overwrite descriptions you wrote by hand
        it[k] = v
    it["first_seen"] = min(it.get("first_seen") or n, n)
    it["last_seen"] = max(it.get("last_seen") or n, n)
    if note:
        it.setdefault("log", []).append({"session": n, "text": note.strip()})
        it["log"].sort(key=lambda e: e["session"])
    return it


def apply_session(data: dict, notes: dict, n: int, date: str | None = None,
                  source: str | None = None) -> dict:
    remove_session(data, n)
    s = notes.get("session", {})

    data["sessions"].append({
        "number": n,
        "date": date or dt.date.today().isoformat(),
        "title": s.get("title", f"Session {n}"),
        "summary": s.get("summary", ""),
        "recap": s.get("recap", []),
        "highlights": s.get("highlights", []),
        "decisions": s.get("decisions", []),
        "cliffhanger": s.get("cliffhanger", ""),
        "in_game_days": s.get("in_game_days", ""),
        "source": source or "",
    })
    data["sessions"].sort(key=lambda x: x["number"])

    for p in notes.get("party_updates", []):
        it = _find(data["party"], p.get("name", ""))
        if it is None:
            # unknown character: add them rather than lose the note
            it = _upsert(data["party"], p["name"], n, {"status": "active"}, None)
        for k in ("level", "status"):
            if p.get(k):
                it[k] = p[k]
        if p.get("note"):
            it.setdefault("log", []).append({"session": n, "text": p["note"]})
            it["log"].sort(key=lambda e: e["session"])

    for npc in notes.get("npcs", []):
        _upsert(data["npcs"], npc["name"], n,
                {k: npc.get(k) for k in ("role", "disposition", "status", "description", "location")},
                npc.get("note"))

    for loc in notes.get("locations", []):
        _upsert(data["locations"], loc["name"], n, {"description": loc.get("description")}, loc.get("note"))

    for q in notes.get("quests", []):
        it = _find(data["quests"], q["title"])
        if it is None:
            it = {"id": slug(q["title"]), "name": q["title"], "status": "active",
                  "first_seen": n, "log": []}
            data["quests"].append(it)
        for k in ("description", "giver"):
            if q.get(k):
                it[k] = q[k]
        action = q.get("action", "update")
        if action in ("complete", "fail"):
            it["status"] = "complete" if action == "complete" else "failed"
            it["closed"] = n
        it["last_seen"] = n
        if q.get("note"):
            it["log"].append({"session": n, "text": q["note"]})
            it["log"].sort(key=lambda e: e["session"])

    for m in notes.get("mysteries", []):
        it = _find(data["mysteries"], m["title"], key="title")
        if it is None:
            it = {"id": slug(m["title"]), "title": m["title"], "status": "open",
                  "opened": n, "clues": [], "resolution": "", "resolved": None}
            data["mysteries"].append(it)
        if m.get("description") and not it.get("description"):
            it["description"] = m["description"]
        if m.get("clue"):
            it["clues"].append({"session": n, "text": m["clue"]})
            it["clues"].sort(key=lambda e: e["session"])
        if m.get("action") == "resolve":
            it["status"], it["resolved"] = "resolved", n
            it["resolution"] = m.get("resolution", "")

    for x in notes.get("loot", []):
        data["loot"].append({"session": n, "item": x["item"], "holder": x.get("holder", "party"),
                             "description": x.get("description", "")})
    for k in notes.get("kills", []):
        try:
            count = max(1, int(k.get("count", 1)))
        except (TypeError, ValueError):
            count = 1
        data["kills"].append({"session": n, "character": k["character"],
                              "creature": k["creature"], "count": count})
    for q in notes.get("quotes", []):
        data["quotes"].append({"session": n, "speaker": q["speaker"], "text": q["text"]})

    return data
