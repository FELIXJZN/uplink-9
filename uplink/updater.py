"""Pull updates for UPLINK-9 from its GitHub repo.

Two channels (config update.channel):
  tags   - install the newest release tag (v0.2.0 ...). Recommended.
  branch - follow the newest commit on update.branch (e.g. main).

Command line:
  python3 -m uplink.updater           check only
  python3 -m uplink.updater --apply   check and install
"""
from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent


@dataclass
class Status:
    ok: bool                 # False when the check itself failed (offline, not a git repo...)
    available: bool = False
    current: str = "?"
    target: str = ""
    message: str = ""


def git(*args: str, repo: Path = REPO_DIR, timeout: float = 30) -> tuple[bool, str]:
    try:
        res = subprocess.run(["git", "-C", str(repo), *args], capture_output=True,
                             text=True, timeout=timeout)
    except FileNotFoundError:
        return False, "git is not installed"
    except subprocess.TimeoutExpired:
        return False, "timed out (offline?)"
    return res.returncode == 0, (res.stdout if res.returncode == 0 else res.stderr).strip()


def current_version(repo: Path = REPO_DIR) -> str:
    ok, out = git("describe", "--tags", "--always", "--dirty", repo=repo)
    return out if ok else "unknown"


def latest_tag(repo: Path = REPO_DIR) -> str | None:
    ok, out = git("tag", "--list", "v*", "--sort=-v:refname", repo=repo)
    if not ok or not out:
        return None
    return out.splitlines()[0]


def _commit(ref: str, repo: Path) -> str | None:
    ok, out = git("rev-parse", f"{ref}^{{commit}}", repo=repo)
    return out if ok else None


def check(cfg: dict, repo: Path = REPO_DIR, fetch_timeout: float = 30) -> Status:
    up = cfg.get("update", {})
    remote = up.get("remote", "origin")
    current = current_version(repo)
    ok, out = git("fetch", "--tags", "--prune", "--force", remote, repo=repo, timeout=fetch_timeout)
    if not ok:
        return Status(False, current=current, message=f"FETCH FAILED: {out.splitlines()[-1] if out else ''}")

    if up.get("channel", "tags") == "tags":
        target = latest_tag(repo)
        if not target:
            return Status(True, current=current, message="NO RELEASES TAGGED YET")
    else:
        target = f"{remote}/{up.get('branch', 'main')}"

    head, want = _commit("HEAD", repo), _commit(target, repo)
    if want is None:
        return Status(False, current=current, target=target, message=f"{target} NOT FOUND")
    if head == want:
        return Status(True, current=current, target=target, message="UP TO DATE")
    behind, _ = git("merge-base", "--is-ancestor", target, "HEAD", repo=repo)
    if behind:  # the target is already contained in what we run (never downgrade)
        return Status(True, current=current, target=target, message="UP TO DATE")
    # On the branch channel, only offer it if the remote is ahead of us.
    if up.get("channel") == "branch":
        ahead, _ = git("merge-base", "--is-ancestor", "HEAD", target, repo=repo)
        if not ahead:
            return Status(True, current=current, target=target,
                          message="LOCAL COPY HAS ITS OWN CHANGES - NOT UPDATING")
    return Status(True, available=True, current=current, target=target,
                  message=f"UPDATE AVAILABLE: {target}")


def apply(cfg: dict, repo: Path = REPO_DIR) -> tuple[bool, str]:
    status = check(cfg, repo)
    if not status.ok or not status.available:
        return False, status.message
    ok, dirty = git("status", "--porcelain", "--untracked-files=no", repo=repo)
    if not ok or dirty:
        return False, "FILES WERE EDITED ON THE DEVICE - commit or reset them first"
    up = cfg.get("update", {})
    if up.get("channel", "tags") == "tags":
        ok, out = git("checkout", "--quiet", "--detach", status.target, repo=repo)
    else:
        branch = up.get("branch", "main")
        ok, out = git("checkout", "--quiet", branch, repo=repo)
        if ok:
            ok, out = git("merge", "--ff-only", "--quiet", status.target, repo=repo)
    if not ok:
        return False, f"UPDATE FAILED: {out}"
    return True, f"UPDATED {status.current} -> {current_version(repo)}"


def main(argv=None) -> int:
    from . import config

    args = sys.argv[1:] if argv is None else argv
    cfg = config.load()
    if "--apply" in args:
        ok, msg = apply(cfg)
        print(msg)
        return 0 if ok or "UP TO DATE" in msg or "NO RELEASES" in msg else 1
    status = check(cfg)
    print(f"current: {status.current}\n{status.message}")
    return 0 if status.ok else 1


if __name__ == "__main__":
    sys.exit(main())
