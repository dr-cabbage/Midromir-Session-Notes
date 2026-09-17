"""Commits the updated campaign data and pushes it to GitHub Pages.

Each function returns (ok, message) and also prints the message.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from .config import ROOT


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=ROOT, text=True, capture_output=True)


def _say(ok: bool, msg: str) -> tuple[bool, str]:
    print(msg)
    return ok, msg


def is_repo() -> bool:
    return (ROOT / ".git").exists()


def pull() -> tuple[bool, str]:
    """Grab friends' edits first so pushes don't collide."""
    if not is_repo():
        return True, ""
    res = _git("pull", "--rebase", "--autostash")
    if res.returncode != 0:
        return _say(False, "Couldn't pull latest changes: " + (res.stderr or res.stdout).strip())
    return True, ""


def commit(message: str, paths: list[Path]) -> tuple[bool, str]:
    if not is_repo():
        return _say(False, "This folder isn't a git repo yet, so nothing was committed. See README > Setup.")
    rel = [str(p.relative_to(ROOT)) for p in paths if p.exists()]
    res = _git("add", *rel)
    if res.returncode != 0:
        return _say(False, "git add failed: " + (res.stderr or res.stdout).strip())
    if _git("diff", "--cached", "--quiet").returncode == 0:
        return _say(True, "Nothing new to commit.")
    res = _git("commit", "-m", message)
    if res.returncode != 0:
        return _say(False, "Commit failed: " + (res.stderr or res.stdout).strip())
    return _say(True, f"Committed: {message}")


def push() -> tuple[bool, str]:
    if not is_repo():
        return _say(False, "Not a git repo.")
    res = _git("push")
    if res.returncode == 0:
        return _say(True, "Pushed! GitHub Pages usually updates within a minute or two.")
    return _say(False, "Push failed: " + (res.stderr or res.stdout).strip())


def publish(message: str, paths: list[Path], push_after: bool = True) -> tuple[bool, str]:
    ok, msg = commit(message, paths)
    if not ok or not push_after:
        return ok, msg
    ok2, msg2 = push()
    return ok2, f"{msg}\n{msg2}"
