"""Per-session turn count for the Stop hook.

One small JSON file per session under <project>/.scribe/turns/, so sessions
open in the same project neither reset nor add to each other's count.

Claude Code runs the SessionStart hook again when a conversation is resumed,
cleared or compacted, with `source` set to "resume", "clear" or "compact".
Only a new conversation ("startup", "clear", or no source) starts the count
over. A resume keeps it. A compaction keeps it and asks for a review at the
next Stop: the turns before it now live only in the summary, and in long
sessions a compaction often comes before ten turns are counted.
"""
import hashlib
import json
import os
import re
import time
from pathlib import Path

KEEP_DAYS = 14  # a session file not touched for this long is removed at session start

_SAFE = re.compile(r"[A-Za-z0-9_-]{1,80}")


def _file(turns_dir, session_id) -> Path:
    sid = str(session_id or "").strip()
    if not sid:
        name = "unknown"
    elif _SAFE.fullmatch(sid):
        name = sid
    else:
        name = hashlib.sha256(sid.encode("utf-8")).hexdigest()[:32]
    return Path(turns_dir) / f"{name}.json"


def load(turns_dir, session_id) -> dict:
    try:
        data = json.loads(_file(turns_dir, session_id).read_text(encoding="utf-8"))
        return {"count": max(0, int(data.get("count", 0))),
                "review_next": bool(data.get("review_next", False))}
    except Exception:
        return {"count": 0, "review_next": False}


def save(turns_dir, session_id, state: dict) -> None:
    path = _file(turns_dir, session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps({"count": int(state.get("count", 0)),
                               "review_next": bool(state.get("review_next", False))}),
                   encoding="utf-8")
    os.replace(tmp, path)


def on_session_start(turns_dir, session_id, source) -> str:
    """Apply a SessionStart to this session's count. Returns what was done."""
    source = str(source or "startup")
    if source in ("startup", "clear"):
        save(turns_dir, session_id, {"count": 0, "review_next": False})
        return "reset"
    if source == "compact":
        state = load(turns_dir, session_id)
        state["review_next"] = True
        save(turns_dir, session_id, state)
        return "kept, review at next stop"
    return "kept"  # resume, or a source this version does not know


def prune(turns_dir, keep_days: float = KEEP_DAYS) -> None:
    cutoff = time.time() - keep_days * 86400
    try:
        entries = list(os.scandir(turns_dir))
    except OSError:
        return
    for entry in entries:
        if not entry.name.endswith((".json", ".tmp")):
            continue
        try:
            if entry.stat().st_mtime < cutoff:
                os.remove(entry.path)
        except OSError:
            pass
