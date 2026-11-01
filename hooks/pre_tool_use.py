"""PreToolUse hook — match the pending tool call against note triggers, v0.4.0.

stdin JSON: session_id, tool_name, tool_input
A note can carry `triggers:` in its front matter (tool: regex). When the call
matches, the note speaks up: by default as a warning next to the tool result
(additionalContext); with `enforce: block` the call is denied, with the fix.
A warning that fired before for the same note says so and suggests the block.
Every match goes to the hits log of the note's side (project .scribe/hits.jsonl,
shared <shared>/.hits.jsonl), and so does a Read of a note, for /scribe-garden.

It runs on every tool call, so it stays import-light and reads the triggers
from .scribe/triggers.json (rebuilt only when a note changed); with no
triggers it is done after one look at the note folders.
"""
import json
import os
import sys
import time

import _scribe_core as core

TEXT_CAP = 400      # characters of a description or fix line
OUTPUT_CAP = 9000   # Claude Code moves hook text over 10,000 characters to a file


def _cap(text: str) -> str:
    return text if len(text) <= TEXT_CAP else text[:TEXT_CAP - 1].rstrip() + "…"


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


def _earlier(dirs, note: dict, session: str) -> str:
    """For a warning that fired before: how often, and the suggestion to block."""
    before = [e for e in core.read_hits(dirs, note["scope"])
              if e.get("note") == note["stem"] and e.get("kind") in core.FIRED]
    if not before:
        return ""
    here = sum(1 for e in before if e.get("session") == session)
    times = "once" if len(before) == 1 else f"{len(before)} times"
    add = "`enforce: block`" + ("" if note["fix"] else " and a one-line `fix:`")
    return (f"This trigger fired {times} before (last {str(before[-1].get('t'))[:10]}, "
            f"{here} in this session). A warning that comes back is what `enforce: block` is for: "
            f"ask the user whether to add {add} to the note's front matter.")


def describe(dirs, note: dict, key: str, pattern: str, tool: str, session: str) -> str:
    lines = [f"scribe note `{note['name']}` ({note['scope']}, {dirs.label(note['path'])}) "
             f"matches this {tool} call (trigger {key}: `{pattern}`)."]
    if note["desc"]:
        lines.append(_cap(note["desc"]))
    if note["fix"]:
        lines.append("Fix: " + _cap(note["fix"]))
    if note["enforce"] == "block":
        lines[0] = "Blocked by s" + lines[0][1:]
        if not note["fix"]:
            lines.append("Fix: read the note.")
        lines.append("Rewrite the call. If this match is wrong, tell the user: the pattern is "
                     "under `triggers:` in the note.")
    elif not note["enforce"]:
        lines.append(_earlier(dirs, note, session))
    return "\n".join(line for line in lines if line)


def main() -> None:
    dirs = core.Dirs()
    try:
        data = json.loads(sys.stdin.buffer.read().decode("utf-8", "replace") or "{}")
        tool = str(data.get("tool_name") or "")
        tool_input = data.get("tool_input") or {}
        session = str(data.get("session_id") or "")[:8]
        if tool == "Read" and isinstance(tool_input, dict):
            log_note_read(dirs, tool_input.get("file_path"), session)
        notes = core.load_triggers(dirs).get("notes")
        if not notes:
            return
        found = core.match(notes, tool, tool_input)
        if not found:
            return
        blocks, warns = [], []
        for note, key, pattern in found:
            text = describe(dirs, note, key, pattern, tool, session)
            (blocks if note["enforce"] == "block" else warns).append(text)
        for note, key, _ in found:
            core.append_hit(dirs, note["scope"], {
                "note": note["stem"], "kind": "block" if note["enforce"] == "block" else "warn",
                "tool": tool, "trigger": key, "session": session})
        out = {"hookEventName": "PreToolUse"}
        if blocks:
            out["permissionDecision"] = "deny"
            out["permissionDecisionReason"] = "\n\n".join(blocks + warns)[:OUTPUT_CAP]
        else:
            out["additionalContext"] = "\n\n".join(warns)[:OUTPUT_CAP]
        # ASCII-escaped JSON reads the same on every console code page
        print(json.dumps({"hookSpecificOutput": out}))
    except Exception as e:  # never stand in the way of a tool call by crashing
        try:
            with open(os.path.join(dirs.scribe, "hook.log"), "a", encoding="utf-8") as f:
                f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} ERROR pre_tool_use: {e!r}\n")
        except OSError:
            pass


if __name__ == "__main__":
    main()
