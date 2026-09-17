#!/usr/bin/env python3
"""The Scribe: record a D&D session, write the notes, update the website.

  python scribe.py record                    record from your PC, then process it
  python scribe.py process <file|folder|zip> transcribe + write notes + publish
  python scribe.py notes --session 7         rewrite notes from a saved transcript
  python scribe.py apply --session 7         publish a draft you edited by hand
  python scribe.py devices                   list microphones / speakers
  python scribe.py serve                     preview the website locally

Run any command with -h for options.
"""
from __future__ import annotations

import argparse
import functools
import http.server
import json
import os
import sys
import webbrowser
from pathlib import Path

from chronicle.config import DATA_FILE, DRAFTS_DIR, ROOT, TRANSCRIPTS_DIR, load_config
from chronicle import merge


def transcript_path(n: int) -> Path:
    return TRANSCRIPTS_DIR / f"session-{n:02d}.txt"


def draft_path(n: int) -> Path:
    return DRAFTS_DIR / f"session-{n:02d}.json"


def pick_session_number(args) -> int:
    if getattr(args, "session", None):
        return args.session
    return merge.next_session_number(merge.load_campaign(DATA_FILE))


# --------------------------------------------------------------------------- #
def step_transcribe(source: Path, n: int, cfg: dict, force: bool) -> Path:
    from chronicle.transcriber import transcribe

    out = transcript_path(n)
    if out.exists() and not force:
        print(f"Transcript for session {n} already exists, reusing it (use --retranscribe to redo).")
        return out
    return transcribe(source, cfg, out)


def step_notes(n: int, cfg: dict) -> Path:
    from chronicle.notewriter import write_notes

    tpath = transcript_path(n)
    if not tpath.exists():
        sys.exit(f"No transcript at {tpath}. Run 'process' first.")
    campaign = merge.load_campaign(DATA_FILE)
    notes = write_notes(campaign, tpath.read_text(encoding="utf-8"), n, cfg)
    dpath = draft_path(n)
    dpath.parent.mkdir(parents=True, exist_ok=True)
    dpath.write_text(json.dumps(notes, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Draft notes saved: {dpath}")
    return dpath


def review(dpath: Path) -> bool:
    title = json.loads(dpath.read_text(encoding="utf-8")).get("session", {}).get("title", "")
    print(f"\nDraft ready: \"{title}\"")
    print(f"Open {dpath.relative_to(ROOT)} to read or fix anything (names, events).")
    if sys.platform.startswith("win"):
        try:
            os.startfile(dpath)  # opens in your default JSON/text editor
        except OSError:
            pass
    answer = input("Save your edits, then press Enter to publish (or type q to stop here): ")
    if answer.strip().lower().startswith("q"):
        print(f"Stopped. Publish later with: python scribe.py apply --session {dpath.stem.split('-')[-1]}")
        return False
    return True


def step_apply(n: int, cfg: dict, date: str | None, source: str | None) -> None:
    from chronicle.publisher import publish, pull

    dpath = draft_path(n)
    if not dpath.exists():
        sys.exit(f"No draft at {dpath}.")
    try:
        notes = json.loads(dpath.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        sys.exit(f"The draft has a JSON typo: {exc}. Fix it and run: python scribe.py apply --session {n}")

    pull()
    campaign = merge.load_campaign(DATA_FILE)
    existing = next((s for s in campaign["sessions"] if s["number"] == n), None)
    if existing and not date:
        date = existing.get("date")
    if existing and not source:
        source = existing.get("source")
    merge.apply_session(campaign, notes, n, date=date, source=source)
    merge.save_campaign(DATA_FILE, campaign)
    title = notes.get("session", {}).get("title", "")
    print(f"Updated {DATA_FILE.relative_to(ROOT)} with session {n}.")

    paths = [DATA_FILE, dpath]
    if cfg.get("keep_transcripts_in_git"):
        paths.append(transcript_path(n))
    publish(f"Session {n}: {title}", paths, push=cfg.get("auto_push", True))


# --------------------------------------------------------------------------- #
def cmd_process(args, cfg):
    source = Path(args.source).expanduser()
    if not source.exists():
        sys.exit(f"Can't find {source}")
    n = pick_session_number(args)
    print(f"== Session {n} ==")
    is_text = source.suffix.lower() in {".txt", ".vtt", ".srt", ".md"}
    step_transcribe(source, n, cfg, args.retranscribe or is_text)
    dpath = step_notes(n, cfg)
    if cfg.get("review_before_publish", True) and not args.no_review:
        if not review(dpath):
            return
    step_apply(n, cfg, args.date, source.name)


def cmd_record(args, cfg):
    from chronicle.recorder import record

    n = pick_session_number(args)
    folder = record(cfg, f"session-{n:02d}", args.mic, args.speaker)
    if args.no_process:
        print(f"Process later with: python scribe.py process \"{folder}\" --session {n}")
        return
    if input("Write the notes now? [Y/n] ").strip().lower().startswith("n"):
        print(f"Process later with: python scribe.py process \"{folder}\" --session {n}")
        return
    args.source, args.session = str(folder), n
    cmd_process(args, cfg)


def cmd_transcribe(args, cfg):
    n = pick_session_number(args)
    step_transcribe(Path(args.source).expanduser(), n, cfg, True)


def cmd_notes(args, cfg):
    dpath = step_notes(args.session, cfg)
    if cfg.get("review_before_publish", True) and not args.no_review:
        if not review(dpath):
            return
    step_apply(args.session, cfg, args.date, None)


def cmd_apply(args, cfg):
    step_apply(args.session, cfg, args.date, None)


def cmd_devices(args, cfg):
    from chronicle.recorder import list_devices
    list_devices()


def cmd_serve(args, cfg):
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(ROOT))
    url = f"http://localhost:{args.port}/"
    print(f"Previewing at {url}  (Ctrl+C to stop)")
    webbrowser.open(url)
    http.server.ThreadingHTTPServer(("127.0.0.1", args.port), handler).serve_forever()


def main():
    p = argparse.ArgumentParser(description="Record D&D sessions and publish the notes.")
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp, needs_session=False):
        sp.add_argument("--session", type=int, required=needs_session,
                        help="session number (default: next one)")
        sp.add_argument("--date", help="session date YYYY-MM-DD (default: today)")
        sp.add_argument("--no-review", action="store_true", help="publish without pausing to review")

    sp = sub.add_parser("process", help="transcribe a recording, write notes, publish")
    sp.add_argument("source", help="audio/video file, Craig .zip, folder of tracks, or a .txt transcript")
    sp.add_argument("--retranscribe", action="store_true", help="ignore a saved transcript")
    common(sp)
    sp.set_defaults(func=cmd_process)

    sp = sub.add_parser("record", help="record the Discord call from this PC")
    sp.add_argument("--mic", help="part of the microphone name (default: system default)")
    sp.add_argument("--speaker", help="part of the speaker/headset name (default: system default)")
    sp.add_argument("--no-process", action="store_true", help="just record")
    sp.add_argument("--retranscribe", action="store_true", help=argparse.SUPPRESS)
    common(sp)
    sp.set_defaults(func=cmd_record)

    sp = sub.add_parser("transcribe", help="only make the transcript")
    sp.add_argument("source")
    sp.add_argument("--session", type=int)
    sp.set_defaults(func=cmd_transcribe)

    sp = sub.add_parser("notes", help="rewrite notes from a saved transcript")
    common(sp, needs_session=True)
    sp.set_defaults(func=cmd_notes)

    sp = sub.add_parser("apply", help="publish a (hand-edited) draft")
    sp.add_argument("--session", type=int, required=True)
    sp.add_argument("--date")
    sp.set_defaults(func=cmd_apply)

    sp = sub.add_parser("devices", help="list audio devices")
    sp.set_defaults(func=cmd_devices)

    sp = sub.add_parser("serve", help="preview the site locally")
    sp.add_argument("--port", type=int, default=8000)
    sp.set_defaults(func=cmd_serve)

    args = p.parse_args()
    args.func(args, load_config())


if __name__ == "__main__":
    main()
