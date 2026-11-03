"""PreToolUse hook — log a Read of a note as a use of it, v0.5.0.

stdin JSON: session_id, tool_name, tool_input
hooks.json runs it for Read only. A Read of a shared or project note goes to
the hits log of the note's side (project .scribe/hits.jsonl, shared
<shared>/.hits.jsonl), so /scribe-garden can tell which notes are still opened.
It prints nothing: no permission decision, no added context.

Until 0.4 it also matched every tool call against note triggers, to warn or
block. In three days of real use they caught one real mistake in about a dozen
matches; the rest matched text inside scripts, notes and records rather than
real commands, and the blocks interrupted work, so 0.5.0 removed them.
"""
import json
import os
import sys
import time

import _scribe_core as core


def _same_dir(a: str, b: str) -> bool:
    norm = lambda p: os.path.normcase(p.replace("\\", "/").rstrip("/"))
    return norm(a) == norm(b)


def log_note_read(dirs, path, session: str) -> None:
    """A Read of a note counts as a use of it (for /scribe-garden)."""
    if not isinstance(path, str) or not path.endswith(".md"):
        return
    folder, _, name = path.replace("\\", "/").rpartition("/")
    if name.upper() in core.SKIP:
        return
    for scope in ("shared", "project"):
        d = dirs.folder(scope)
        if _same_dir(folder, d) or _same_dir(folder, os.path.realpath(d)):
            core.append_hit(dirs, scope, {"note": name[:-3], "kind": "read", "tool": "Read",
                                          "session": session})
            return


def main() -> None:
    dirs = core.Dirs()
    try:
        data = json.loads(sys.stdin.buffer.read().decode("utf-8", "replace") or "{}")
        tool = str(data.get("tool_name") or "")
        tool_input = data.get("tool_input") or {}
        session = str(data.get("session_id") or "")[:8]
        if tool == "Read" and isinstance(tool_input, dict):
            log_note_read(dirs, tool_input.get("file_path"), session)
    except Exception as e:  # never stand in the way of a tool call by crashing
        try:
            with open(os.path.join(dirs.scribe, "hook.log"), "a", encoding="utf-8") as f:
                f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} ERROR pre_tool_use: {e!r}\n")
        except OSError:
            pass


if __name__ == "__main__":
    main()
