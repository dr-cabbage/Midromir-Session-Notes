"""Offline tests: python tests/test_scribe.py  (no API key or audio needed)."""
import copy
import json
import sys
import tempfile
import types
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from chronicle import merge, notewriter, transcriber  # noqa: E402

S1 = {
    "session": {
        "title": "Kidnapped by Goblins",
        "summary": "The party wakes up in a goblin cart and immediately makes it worse.",
        "recap": ["Thorn woke up tied to Grimbold.", "They escaped into the Mirewood."],
        "highlights": ["Grimbold rolled a nat 20 to headbutt the cart open."],
        "decisions": ["Spared the goblin Snik in exchange for directions."],
        "cliffhanger": "A lantern is moving through the swamp toward them.",
    },
    "party_updates": [{"name": "Thorn", "note": "Lost his bow to the goblins."}],
    "npcs": [
        {"name": "Snik", "role": "goblin scout", "disposition": "friendly", "status": "alive",
         "description": "A nervous goblin who knows the swamp.", "note": "Traded directions for his life."},
        {"name": "Boss Gruk", "role": "goblin chief", "disposition": "hostile", "note": "Ordered the kidnapping."},
    ],
    "locations": [{"name": "The Mirewood", "description": "A foggy swamp.", "note": "Where the party escaped to."}],
    "quests": [{"title": "Get Thorn's bow back", "action": "start", "giver": "Thorn", "note": "Gruk has it."}],
    "mysteries": [{"title": "Who paid the goblins?", "action": "open",
                   "description": "Gruk mentioned a client.", "clue": "The coins were stamped with a raven."}],
    "loot": [{"item": "Raven-stamped coins", "holder": "Grimbold", "description": "12 gold"}],
    "kills": [{"character": "Grimbold", "creature": "goblin", "count": 2},
              {"character": "Thorn", "creature": "goblin", "count": 1}],
    "quotes": [{"speaker": "Grimbold", "text": "I solve problems with my head. Literally."}],
}

S2 = {
    "session": {
        "title": "The Lantern Witch",
        "summary": "The lantern belongs to a witch with opinions.",
        "recap": ["Agatha the swamp witch offered tea.", "Thorn got his bow back from Gruk's camp."],
        "highlights": ["Thorn tried to seduce a frog."],
        "cliffhanger": "Agatha says the raven coins come from the capital.",
    },
    "party_updates": [{"name": "Thorn", "level": 2, "note": "Reached level 2 and got his bow back."},
                      {"name": "Grimbold", "note": "Drank the witch's tea. Now glows faintly."}],
    "npcs": [
        {"name": "the Snik", "note": "Guided the party to Gruk's camp."},  # alias-ish match
        {"name": "Agatha", "role": "swamp witch", "disposition": "neutral", "note": "Knows about the raven coins."},
        {"name": "Boss Gruk", "status": "dead", "note": "Killed by Thorn."},
    ],
    "locations": [{"name": "Mirewood", "note": "Gruk's camp is in the middle."}],
    "quests": [{"title": "Get Thorn's bow back", "action": "complete", "note": "Recovered from the camp."}],
    "mysteries": [{"title": "Who paid the goblins?", "action": "clue", "clue": "The coins come from the capital."},
                  {"title": "Why does Grimbold glow?", "action": "open", "description": "Tea side effect?"}],
    "loot": [{"item": "Thorn's bow", "holder": "Thorn"}],
    "kills": [{"character": "Thorn", "creature": "goblin chief", "count": 1}],
    "quotes": [{"speaker": "Agatha", "text": "The tea is fine. Mostly."}],
}


def base():
    return {
        "campaign": {"title": "The Raven Coin", "subtitle": "A sample campaign.", "setting": "The Mirewood", "dm": "Sam"},
        "party": [
            {"id": "thorn", "name": "Thorn", "player": "Kale", "race": "Half-elf", "class": "Ranger",
             "level": 1, "status": "active", "manual": True, "log": []},
            {"id": "grimbold", "name": "Grimbold", "player": "Dave", "race": "Dwarf", "class": "Barbarian",
             "level": 1, "status": "active", "manual": True, "log": []},
        ],
    }


def test_merge_and_rerun():
    data = merge.load_campaign(Path("/nonexistent"))
    data.update(base())
    merge.apply_session(data, S1, 1, date="2026-09-01")
    merge.apply_session(data, S2, 2, date="2026-09-08")

    names = sorted(n["name"] for n in data["npcs"])
    assert names == ["Agatha", "Boss Gruk", "Snik"], names
    snik = merge._find(data["npcs"], "Snik")
    assert len(snik["log"]) == 2 and snik["first_seen"] == 1 and snik["last_seen"] == 2
    assert merge._find(data["npcs"], "Boss Gruk")["status"] == "dead"
    assert len(data["locations"]) == 1, "Mirewood / The Mirewood should merge"
    thorn = merge._find(data["party"], "Thorn")
    assert thorn["level"] == 2 and len(thorn["log"]) == 2
    q = data["quests"][0]
    assert q["status"] == "complete" and q["closed"] == 2
    m = merge._find(data["mysteries"], "Who paid the goblins?", key="title")
    assert len(m["clues"]) == 2 and m["status"] == "open"
    assert sum(k["count"] for k in data["kills"]) == 4

    snapshot = json.dumps(data, sort_keys=True)
    # re-running session 2 must not duplicate anything
    merge.apply_session(data, copy.deepcopy(S2), 2, date="2026-09-08")
    assert json.dumps(data, sort_keys=True) == snapshot, "re-applying a session changed the data"

    # re-running session 2 with different notes must drop what it added before
    s2b = copy.deepcopy(S2)
    s2b["npcs"] = [n for n in s2b["npcs"] if n["name"] != "Agatha"]
    s2b["quests"] = []
    s2b["mysteries"] = []
    merge.apply_session(data, s2b, 2)
    assert merge._find(data["npcs"], "Agatha") is None
    assert data["quests"][0]["status"] == "active"
    assert len(merge._find(data["mysteries"], "Who paid the goblins?", key="title")["clues"]) == 1
    assert merge._find(data["mysteries"], "Why does Grimbold glow?", key="title") is None
    assert merge._find(data["party"], "Grimbold") is not None, "manual party members are never removed"
    assert merge.next_session_number(data) == 3
    print("merge: ok")


def test_transcriber_helpers():
    P = Path
    assert transcriber.speaker_from_filename(P("1-kingkale.flac")) == "kingkale"
    assert transcriber.speaker_from_filename(P("3-Big_Dave_0.flac")) == "Big_Dave"
    assert transcriber.speaker_from_filename(P("2-Table.wav")) == "Table"
    assert transcriber.map_speaker("KingKale", {"kingkale": "Kale (Thorn)"}) == "Kale (Thorn)"
    assert transcriber.map_speaker("stranger", {}) == "stranger"

    S = transcriber.Segment
    segs = [S(5, 7, "Sam (DM)", "You see a door."), S(0, 2, "Kale", "Hi"), S(2.5, 4, "Kale", "all."),
            S(8, 9, "Kale", " I open it. ")]
    out = transcriber.render_transcript(transcriber.merge_segments(segs))
    assert out.splitlines() == [
        "[00:00:00] Kale: Hi all.",
        "[00:00:05] Sam (DM): You see a door.",
        "[00:00:08] Kale: I open it.",
    ], out
    assert transcriber.fmt_ts(3725) == "01:02:05"

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        z = tmp / "craig.zip"
        with zipfile.ZipFile(z, "w") as zf:
            zf.writestr("craig_abc/1-kingkale.flac", b"x")
            zf.writestr("craig_abc/2-samthedm.flac", b"x")
            zf.writestr("craig_abc/info.txt", "hi")
        work = tmp / "work"
        work.mkdir()
        tracks = transcriber.collect_tracks(z, work)
        assert [t.name for t in tracks] == ["1-kingkale.flac", "2-samthedm.flac"]

        # text transcripts pass straight through
        src = tmp / "t.txt"
        src.write_text("[00:00:01] Sam: hello", encoding="utf-8")
        dst = tmp / "out" / "session-01.txt"
        transcriber.transcribe(src, {"whisper": {}}, dst)
        assert dst.read_text(encoding="utf-8").startswith("[00:00:01]")
    print("transcriber helpers: ok")


def test_notewriter_with_fake_client():
    data = merge.load_campaign(Path("/nonexistent"))
    data.update(base())
    merge.apply_session(data, S1, 1)

    system, user = notewriter.build_prompt(data, "[00:00:01] Sam (DM): hello", 2, {"notes_style": "Funny."})
    assert "Snik" in user and "Kidnapped by Goblins" in user and "Funny." in system
    json.dumps(notewriter.NOTES_SCHEMA)  # serialisable

    captured = {}

    class FakeStream:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def get_final_message(self):
            block = types.SimpleNamespace(type="tool_use", name=notewriter.TOOL_NAME, input=S2)
            return types.SimpleNamespace(content=[block], stop_reason="tool_use",
                                         usage=types.SimpleNamespace(input_tokens=1000, output_tokens=500))

    class FakeClient:
        def __init__(self):
            self.messages = types.SimpleNamespace(stream=self._stream)
        def _stream(self, **kw):
            captured.update(kw)
            return FakeStream()

    sys.modules["anthropic"] = types.SimpleNamespace(Anthropic=FakeClient)
    import os
    os.environ.setdefault("ANTHROPIC_API_KEY", "test")
    notes = notewriter.write_notes(data, "transcript", 2, {"claude_model": "claude-sonnet-5"})
    assert notes is S2
    assert captured["tool_choice"]["name"] == notewriter.TOOL_NAME
    assert captured["model"] == "claude-sonnet-5"
    print("notewriter: ok")


def build_sample():
    """Writes data/sample-campaign.json for previewing the site."""
    data = merge.load_campaign(Path("/nonexistent"))
    data.update(base())
    merge.apply_session(data, S1, 1, date="2026-09-01", source="craig-session1.zip")
    merge.apply_session(data, S2, 2, date="2026-09-08", source="craig-session2.zip")
    merge.save_campaign(ROOT / "data" / "sample-campaign.json", data)
    print("wrote data/sample-campaign.json")


if __name__ == "__main__":
    test_merge_and_rerun()
    test_transcriber_helpers()
    test_notewriter_with_fake_client()
    build_sample()
    print("all tests passed")
