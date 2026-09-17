"""A small review window (runs in your browser) for checking notes before they go live.

Edit or cut anything, tell Claude what was wrong, regenerate, then Post and Commit & push.
Everything runs on your own PC at http://127.0.0.1.
"""
from __future__ import annotations

import datetime as dt
import json
import secrets
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import merge, pipeline, publisher
from .config import DATA_FILE

HTML_FILE = Path(__file__).with_name("review.html")


class ReviewApp:
    def __init__(self, n: int, cfg: dict, date: str | None = None, source: str | None = None):
        self.n = n
        self.cfg = cfg
        self.lock = threading.Lock()
        self.busy = False
        self.done = threading.Event()
        self.token = secrets.token_urlsafe(16)  # stops other web pages from poking the server
        pipeline.save_meta(n, date=date, source=source)

    # ---- data for the page ----
    def state(self) -> dict:
        tpath = pipeline.transcript_path(self.n)
        campaign = merge.load_campaign(DATA_FILE)
        meta = pipeline.load_meta(self.n)
        posted = any(s["number"] == self.n for s in campaign["sessions"])
        return {
            "session": self.n,
            "campaign": campaign.get("campaign", {}).get("title", ""),
            "party": [p.get("name") for p in campaign.get("party", [])],
            "draft": pipeline.load_draft(self.n),
            "feedback": pipeline.load_feedback(self.n),
            "transcript": tpath.read_text(encoding="utf-8") if tpath.exists() else "",
            "date": meta.get("date") or dt.date.today().isoformat(),
            "posted": posted,
            "is_repo": publisher.is_repo(),
            "auto_push": bool(self.cfg.get("auto_push", True)),
            "model": self.cfg.get("claude_model"),
        }

    # ---- actions ----
    def save(self, body: dict) -> dict:
        if body.get("draft") is not None:
            pipeline.save_draft(self.n, body["draft"])
        if body.get("date"):
            pipeline.save_meta(self.n, date=body["date"])
        return {"ok": True}

    def regenerate(self, body: dict) -> dict:
        with self.lock:
            if self.busy:
                return {"ok": False, "error": "Already regenerating."}
            self.busy = True
        try:
            fb = pipeline.load_feedback(self.n)
            for r in body.get("removed", []):
                if r and r not in fb["removed"]:
                    fb["removed"].append(r)
            note = (body.get("note") or "").strip()
            if note:
                fb["notes"].append(note)
            pipeline.save_feedback(self.n, fb)
            draft = body.get("draft")
            if draft is not None:
                pipeline.save_draft(self.n, draft)
            revision = {"draft": draft, "removed": fb["removed"], "notes": fb["notes"]}
            new = pipeline.generate(self.n, self.cfg, revision=revision)
            return {"ok": True, "draft": new, "feedback": fb}
        except Exception as exc:  # show the problem in the page instead of crashing
            return {"ok": False, "error": str(exc)}
        finally:
            self.busy = False

    def forget(self, body: dict) -> dict:
        fb = pipeline.load_feedback(self.n)
        kind, idx = body.get("kind"), body.get("index")
        if kind in ("removed", "notes") and isinstance(idx, int) and 0 <= idx < len(fb[kind]):
            fb[kind].pop(idx)
            pipeline.save_feedback(self.n, fb)
        return {"ok": True, "feedback": fb}

    def post(self, body: dict) -> dict:
        try:
            if body.get("draft") is not None:
                pipeline.save_draft(self.n, body["draft"])
            date = body.get("date")
            pipeline.save_meta(self.n, date=date)
            ok, msg = publisher.pull()
            log = [msg] if msg else []
            title = pipeline.apply_draft(self.n, date=date)
            log.append(f"Session {self.n} (\"{title}\") added to the campaign data.")
            if body.get("commit"):
                ok, msg = publisher.publish(f"Session {self.n}: {title}",
                                            pipeline.publish_paths(self.n, self.cfg),
                                            push_after=body.get("push", True))
                log.append(msg)
                return {"ok": ok, "log": log}
            return {"ok": True, "log": log}
        except Exception as exc:
            return {"ok": False, "log": [f"Error: {exc}"]}

    def commit_push(self, body: dict) -> dict:
        draft = pipeline.load_draft(self.n) or {}
        title = draft.get("session", {}).get("title", "")
        ok, msg = publisher.publish(f"Session {self.n}: {title}",
                                    pipeline.publish_paths(self.n, self.cfg),
                                    push_after=body.get("push", True))
        return {"ok": ok, "log": [msg]}


def _handler(app: ReviewApp):
    routes = {
        "/api/save": app.save,
        "/api/regenerate": app.regenerate,
        "/api/forget": app.forget,
        "/api/post": app.post,
        "/api/commit": app.commit_push,
    }

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # keep the terminal quiet
            pass

        def _send(self, code: int, body: bytes, ctype: str):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, data, code=200):
            self._send(code, json.dumps(data, ensure_ascii=False).encode("utf-8"), "application/json")

        def do_GET(self):
            if self.path.split("?")[0] == "/":
                html = HTML_FILE.read_text(encoding="utf-8").replace("__TOKEN__", app.token)
                self._send(200, html.encode("utf-8"), "text/html; charset=utf-8")
            elif self.path.startswith("/api/state"):
                if self.headers.get("X-Token") != app.token:
                    return self._json({"error": "bad token"}, 403)
                self._json(app.state())
            else:
                self._send(404, b"not found", "text/plain")

        def do_POST(self):
            if self.headers.get("X-Token") != app.token:
                return self._json({"error": "bad token"}, 403)
            length = int(self.headers.get("Content-Length") or 0)
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError:
                return self._json({"error": "bad json"}, 400)
            if self.path == "/api/quit":
                self._json({"ok": True})
                app.done.set()
                return
            fn = routes.get(self.path)
            if not fn:
                return self._json({"error": "not found"}, 404)
            self._json(fn(body))

    return Handler


def run(n: int, cfg: dict, date: str | None = None, source: str | None = None,
        port: int = 0, open_browser: bool = True) -> None:
    app = ReviewApp(n, cfg, date=date, source=source)
    server = ThreadingHTTPServer(("127.0.0.1", port), _handler(app))
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print(f"\nReview window: {url}")
    print("(If it didn't open, paste that link into your browser. Press Ctrl+C here to quit.)")
    if open_browser:
        webbrowser.open(url)
    try:
        while not app.done.wait(0.5):
            pass
        print("Review window closed.")
    except KeyboardInterrupt:
        print("\nStopped. Your draft is saved; reopen it with: python scribe.py review --session", n)
    finally:
        server.shutdown()
