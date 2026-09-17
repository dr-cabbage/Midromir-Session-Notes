#!/usr/bin/env python3
"""The Scribe: record a D&D session, write the notes, update the website.

  python scribe.py process <file|folder|zip> transcribe, write notes, open the review window
  python scribe.py review --session 7        reopen the review window for a session
  python scribe.py record                    record from your PC, then process it
  python scribe.py notes --session 7         write fresh notes from a saved transcript
  python scribe.py apply --session 7         post a draft without the review window
  python scribe.py devices                   list microphones / speakers
  python scribe.py serve                     preview the website locally

Run any command with -h for options.
"""
from __future__ import annotations

import argparse
import functools
import http.server
import sys
import webbrowser
from pathlib import Path

from chronicle import merge, pipeline
from chronicle.config import DATA_FILE, load_config

TEXT_EXTS = {".txt", ".vtt", ".srt", ".md"}


def pick_session_number(args) -> int:
    if getattr(args, "session", None):
        return args.session
    return merge.next_session_number(merge.load_campaign(DATA_FILE))


def step_transcribe(source: Path, n: int, cfg: dict, force: bool) -> None:
    from chronicle.transcriber import transcribe

    out = pipeline.transcript_path(n)
    if out.exists() and not force:
        print(f"Transcript for session {n} already exists, reusing it (use --retranscribe to redo).")
        return
    transcribe(source, cfg, out)


def step_generate(n: int, cfg: dict) -> None:
    from chronicle.notewriter import NotesError
    try:
        pipeline.generate(n, cfg)
    except (NotesError, FileNotFoundError) as exc:
        sys.exit(str(exc))
    print(f"Draft notes saved: {pipeline.draft_path(n)}")


def step_review(n: int, cfg: dict, args) -> None:
    """Open the browser review window, or publish straight away with --no-review."""
    date = getattr(args, "date", None)
    source = getattr(args, "source_name", None)
    if cfg.get("review_before_publish", True) and not getattr(args, "no_review", False):
        from chronicle.reviewer import run
        run(n, cfg, date=date, source=source)
    else:
        post_now(n, cfg, date, source)


def post_now(n: int, cfg: dict, date: str | None, source: str | None) -> None:
    from chronicle import publisher
    pipeline.save_meta(n, date=date, source=source)
    publisher.pull()
    try:
        title = pipeline.apply_draft(n, date=date, source=source)
    except FileNotFoundError as exc:
        sys.exit(str(exc))
    publisher.publish(f"Session {n}: {title}", pipeline.publish_paths(n, cfg),
                      push_after=cfg.get("auto_push", True))


# --------------------------------------------------------------------------- #
def cmd_process(args, cfg):
    source = Path(args.source).expanduser()
    if not source.exists():
        sys.exit(f"Can't find {source}")
    n = pick_session_number(args)
    print(f"== Session {n} ==")
    step_transcribe(source, n, cfg, args.retranscribe or source.suffix.lower() in TEXT_EXTS)
    if pipeline.load_draft(n) and not args.fresh:
        print("A draft for this session already exists; opening it (use --fresh to write new notes).")
    else:
        step_generate(n, cfg)
    args.source_name = source.name
    step_review(n, cfg, args)


def cmd_record(args, cfg):
    from chronicle.recorder import record

    n = pick_session_number(args)
    folder = record(cfg, f"session-{n:02d}", args.mic, args.speaker)
    later = f'Process later with: python scribe.py process "{folder}" --session {n}'
    if args.no_process or input("Write the notes now? [Y/n] ").strip().lower().startswith("n"):
        print(later)
        return
    args.source, args.session = str(folder), n
    cmd_process(args, cfg)


def cmd_review(args, cfg):
    step_review(args.session, cfg, args)


def cmd_transcribe(args, cfg):
    n = pick_session_number(args)
    step_transcribe(Path(args.source).expanduser(), n, cfg, True)


def cmd_notes(args, cfg):
    step_generate(args.session, cfg)
    step_review(args.session, cfg, args)


def cmd_apply(args, cfg):
    post_now(args.session, cfg, args.date, None)


def cmd_devices(args, cfg):
    from chronicle.recorder import list_devices
    list_devices()


def cmd_serve(args, cfg):
    from chronicle.config import ROOT
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
        sp.add_argument("--no-review", action="store_true", help="skip the review window and publish right away")

    sp = sub.add_parser("process", help="transcribe a recording, write notes, review, publish")
    sp.add_argument("source", help="audio/video file, Craig .zip, folder of tracks, or a .txt transcript")
    sp.add_argument("--retranscribe", action="store_true", help="ignore a saved transcript")
    sp.add_argument("--fresh", action="store_true", help="ignore an existing draft and write new notes")
    common(sp)
    sp.set_defaults(func=cmd_process)

    sp = sub.add_parser("record", help="record the Discord call from this PC")
    sp.add_argument("--mic", help="part of the microphone name (default: system default)")
    sp.add_argument("--speaker", help="part of the speaker/headset name (default: system default)")
    sp.add_argument("--no-process", action="store_true", help="just record")
    common(sp)
    sp.set_defaults(func=cmd_record, retranscribe=False, fresh=False)

    sp = sub.add_parser("review", help="open the review window for a session")
    common(sp, needs_session=True)
    sp.set_defaults(func=cmd_review)

    sp = sub.add_parser("transcribe", help="only make the transcript")
    sp.add_argument("source")
    sp.add_argument("--session", type=int)
    sp.set_defaults(func=cmd_transcribe)

    sp = sub.add_parser("notes", help="write fresh notes from a saved transcript, then review")
    common(sp, needs_session=True)
    sp.set_defaults(func=cmd_notes)

    sp = sub.add_parser("apply", help="post a draft without the review window")
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
