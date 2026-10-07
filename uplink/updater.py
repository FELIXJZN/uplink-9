"""Firmware updates: the app folder is a git clone, and an update is a fast-forward pull from GitHub."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent


def _git(*args, timeout=60):
    try:
        p = subprocess.run(["git", "-C", str(APP_DIR), *args], capture_output=True, text=True, timeout=timeout)
        return p.returncode == 0, (p.stdout + p.stderr).strip()
    except FileNotFoundError:
        return False, "git is not installed"
    except subprocess.TimeoutExpired:
        return False, "git timed out"


def is_git() -> bool:
    return (APP_DIR / ".git").exists()


def local_version() -> str:
    try:
        return (APP_DIR / "VERSION").read_text().strip()
    except OSError:
        return "0.0.0"


def commit() -> str:
    ok, out = _git("rev-parse", "--short", "HEAD")
    return out if ok else ""


def remote_url() -> str:
    ok, out = _git("remote", "get-url", "origin")
    return out if ok else ""


def check(branch: str = "main") -> dict:
    """Fetch from GitHub and compare. Returns a dict with ok, error, behind, version, changes."""
    if not is_git():
        return {"ok": False, "error": "NOT INSTALLED FROM GIT. RUN INSTALL.SH FROM A CLONE."}
    if not remote_url():
        return {"ok": False, "error": "NO UPDATE SOURCE. ADD A GITHUB REMOTE NAMED ORIGIN."}
    ok, out = _git("fetch", "--quiet", "origin", branch, timeout=90)
    if not ok:
        return {"ok": False, "error": "CANNOT REACH UPDATE SERVER: " + out.splitlines()[-1][:60] if out else "FETCH FAILED"}
    ok, behind = _git("rev-list", "--count", f"HEAD..origin/{branch}")
    if not ok:
        return {"ok": False, "error": "BRANCH " + branch.upper() + " NOT FOUND"}
    _, ahead = _git("rev-list", "--count", f"origin/{branch}..HEAD")
    ok_v, ver = _git("show", f"origin/{branch}:VERSION")
    _, log = _git("log", "--format=%s", "-n", "8", f"HEAD..origin/{branch}")
    return {
        "ok": True, "error": "", "behind": int(behind or 0), "ahead": int(ahead or 0),
        "version": ver.strip() if ok_v else "?", "changes": [l for l in log.splitlines() if l],
    }


def dirty() -> bool:
    ok, out = _git("status", "--porcelain", "--untracked-files=no")
    return bool(ok and out)


def install(branch: str = "main") -> tuple[bool, str, str]:
    """Fast-forward to origin/branch. Returns (ok, message, previous_commit)."""
    prev = commit()
    if dirty():
        return False, "LOCAL CHANGES FOUND. COMMIT OR DISCARD THEM FIRST.", prev
    _, old_req = _git("show", "HEAD:requirements.txt")
    ok, out = _git("merge", "--ff-only", f"origin/{branch}")
    if not ok:
        return False, "CANNOT FAST-FORWARD: " + (out.splitlines()[-1][:60] if out else ""), prev
    _, new_req = _git("show", "HEAD:requirements.txt")
    if new_req != old_req:
        ok, out = install_requirements()
        if not ok:
            return False, "UPDATED, BUT DEPENDENCIES FAILED: " + out[-60:], prev
    return True, "UPDATE INSTALLED", prev


def install_requirements():
    try:
        p = subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-r", str(APP_DIR / "requirements.txt")],
                           capture_output=True, text=True, timeout=600)
        return p.returncode == 0, (p.stdout + p.stderr).strip()
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, str(e)


def rollback(prev: str) -> tuple[bool, str]:
    if not prev:
        return False, "NOTHING TO ROLL BACK TO"
    if dirty():
        return False, "LOCAL CHANGES FOUND. COMMIT OR DISCARD THEM FIRST."
    ok, out = _git("reset", "--hard", prev)
    return ok, ("ROLLED BACK TO " + prev) if ok else out[-60:]


def restart() -> None:
    """Replace this process with a fresh copy of the app (the 'reboot' after an update)."""
    os.environ["PYTHONPATH"] = str(APP_DIR) + os.pathsep + os.environ.get("PYTHONPATH", "")
    os.execv(sys.executable, [sys.executable, "-m", "uplink", "--after-update"])
