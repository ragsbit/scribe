"""Stop hook — every 10th turn of this session, and at the first Stop after a
compaction, inject the SCRIBE review prompt, v0.5.1.

stdin JSON: hook_event_name, session_id, stop_hook_active
The count is kept per session in .scribe/turns/ (see _scribe_turns).
"""
import json
import logging
import sys

from datetime import date
import _scribe_turns as turns
from _scribe_paths import LOG_FILE, TURNS_DIR, KNOWLEDGE_DIR, SHARED_DIR, ensure_dirs

ensure_dirs()
logging.basicConfig(filename=str(LOG_FILE), level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
try:
    sys.stdout.reconfigure(encoding="utf-8")  # Windows pipes default to the local code page
except Exception:
    pass

REVIEW_INTERVAL = 10


AFTER_COMPACT = """\
The conversation was compacted since the last review: the earlier turns are in
the summary above, so read its list of user messages too.
"""


def _build_prompt(after_compact: bool = False) -> str:
    today = date.today().isoformat()
    compact_note = ("\n" + AFTER_COMPACT) if after_compact else ""
    return f"""\
[SCRIBE] Reflect on the last turns (respond in the user's language). Today: {today}
{compact_note}
Route each finding to one place — do NOT duplicate, link instead:

→ Claude Code MEMORY (personal, auto-managed):
  - User corrected how you work, report or ask
  - User preferences or working style you observed
  - Project context not derivable from code or docs

→ Project KNOWLEDGE (git): the folders the project's CLAUDE.md or AGENTS.md
  names for records; default `{KNOWLEDGE_DIR}`.
  - Domain pitfalls the whole team will hit (non-obvious, not in docs)
  - Techniques that save significant time
  - Architectural decisions worth explaining to future team members
  When you add or rename a project note, update the project map
  (`.scribe/knowledge/MAP.md`: key facts, situation → search words → note).

→ SHARED notes, all projects `{SHARED_DIR}`:
  - Lessons that hold outside this project: shell and OS traps, tools, APIs,
    data vendors, Claude Code behavior
  - If the full record belongs to a project (with its commit or test), keep it
    there and write a short shared note that links to it.

Only note titles are listed at session start, so give each note a clear
description. If every session must know the rule itself, also add one line to
CLAUDE.md (and AGENTS.md) that points to the note.

→ TEST: a technical mistake that recurred although a note existed
  → a repo test that fails on the pattern, plus the note and the CLAUDE.md line.

→ SKILL FILE: a skill gave a wrong result and a better way was found
  → fix that skill's SKILL.md.

If anything fits → run /scribe-review. Ask the user first, unless the user or
the project instructions say records need no approval; then write and report
in one line.
If nothing → respond "Nothing to record." only."""


def main() -> None:
    try:
        raw = sys.stdin.read()
        data = json.loads(raw) if raw.strip() else {}
    except Exception as e:
        logging.error("stop stdin parse error: %s", e)
        sys.exit(0)
    if not isinstance(data, dict):
        sys.exit(0)

    if data.get("stop_hook_active"):
        sys.exit(0)

    sid = data.get("session_id")
    label = str(sid or "?")[:8]
    try:
        state = turns.load(TURNS_DIR, sid)
        state["count"] += 1
        after_compact = state["review_next"]
        due = after_compact or state["count"] >= REVIEW_INTERVAL
        turns.save(TURNS_DIR, sid, {"count": 0, "review_next": False} if due else state)
    except Exception as e:  # a full disk or a locked file must never break a turn
        logging.error("stop hook: session=%s turn count failed: %s", label, e)
        sys.exit(0)

    if due:
        logging.info("stop hook: session=%s turn=%d → inject%s", label, state["count"],
                     " (after compact)" if after_compact else "")
        print(json.dumps({"decision": "block", "reason": _build_prompt(after_compact)},
                         ensure_ascii=False))
    else:
        logging.info("stop hook: session=%s turn=%d → skip (next in %d)",
                     label, state["count"], REVIEW_INTERVAL - state["count"])

    sys.exit(0)


if __name__ == "__main__":
    main()
