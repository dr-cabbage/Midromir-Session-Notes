"""Commits the updated campaign data and pushes it to GitHub Pages."""
from __future__ import annotations

import subprocess
from pathlib import Path

from .config import ROOT


def _git(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=ROOT, text=True, capture_output=True, check=check)


def pull() -> None:
    """Grab friends' edits first so pushes don't collide."""
    if not (ROOT / ".git").exists():
        return
    res = _git("pull", "--rebase", "--autostash", check=False)
    if res.returncode != 0:
        print("Heads up: couldn't pull latest changes:\n" + (res.stderr or res.stdout).strip())


def publish(message: str, paths: list[Path], push: bool = True) -> None:
    if not (ROOT / ".git").exists():
        print("This folder isn't a git repo yet, so nothing was published. See README > Setup.")
        return
    rel = [str(p.relative_to(ROOT)) for p in paths if p.exists()]
    _git("add", *rel)
    if _git("diff", "--cached", "--quiet", check=False).returncode == 0:
        print("No changes to publish.")
        return
    _git("commit", "-m", message)
    print(f"Committed: {message}")
    if not push:
        print("Not pushing (auto_push is off). Run 'git push' when ready.")
        return
    res = _git("push", check=False)
    if res.returncode == 0:
        print("Pushed! GitHub Pages usually updates within a minute or two.")
    else:
        print("Push failed:\n" + (res.stderr or res.stdout).strip())
