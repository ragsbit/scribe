"""Stop hook — every 10 turns, inject SCRIBE review prompt.

stdin JSON: hook_event_name, session_id, stop_hook_active
"""
import json
import logging
import sys

from datetime import date
from _scribe_paths import LOG_FILE, TURN_COUNT_FILE, KNOWLEDGE_DIR, SHARED_DIR, ensure_dirs

ensure_dirs()
logging.basicConfig(filename=str(LOG_FILE), level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
try:
    sys.stdout.reconfigure(encoding="utf-8")  # Windows pipes default to the local code page
except Exception:
    pass

REVIEW_INTERVAL = 10


def _build_prompt() -> str:
    today = date.today().isoformat()
    return f"""\
[SCRIBE] Reflect on the last turns (respond in the user's language). Today: {today}

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


def _read_turn() -> int:
    try:
        return int(TURN_COUNT_FILE.read_text(encoding="utf-8").strip())
    except Exception:
        return 0


def _write_turn(n: int) -> None:
    TURN_COUNT_FILE.write_text(str(n), encoding="utf-8")


def main() -> None:
    try:
        raw = sys.stdin.read()
        data = json.loads(raw) if raw.strip() else {}
    except Exception as e:
        logging.error("stop stdin parse error: %s", e)
        sys.exit(0)

    if data.get("stop_hook_active"):
        sys.exit(0)

    session_id = data.get("session_id", "?")[:8]
    turn = _read_turn() + 1
    _write_turn(turn)

    if turn % REVIEW_INTERVAL == 0:
        logging.info("stop hook: session=%s turn=%d → inject", session_id, turn)
        print(json.dumps({"decision": "block", "reason": _build_prompt()}, ensure_ascii=False))
    else:
        logging.info("stop hook: session=%s turn=%d → skip (next in %d)",
                     session_id, turn, REVIEW_INTERVAL - (turn % REVIEW_INTERVAL))

    sys.exit(0)


if __name__ == "__main__":
    main()
