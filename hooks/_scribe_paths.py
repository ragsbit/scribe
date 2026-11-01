"""Paths for scribe runtime data.

Resolves project root from CLAUDE_PROJECT_DIR (Claude Code hook env),
falling back to current working directory. Per-project artifacts live
under <project_root>/.scribe/. Shared notes, read in every project, live
in SCRIBE_SHARED_DIR (default ~/.claude/scribe/shared).
"""
import os
from pathlib import Path

PROJECT_ROOT = Path(os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd()))
ROOT = PROJECT_ROOT / ".scribe"
KNOWLEDGE_DIR = ROOT / "knowledge"
LOG_FILE = ROOT / "hook.log"
TURN_COUNT_FILE = ROOT / "turn_count"

SHARED_DIR = Path(os.environ.get("SCRIBE_SHARED_DIR")
                  or Path.home() / ".claude" / "scribe" / "shared").expanduser()

try:
    CATALOG_BUDGET = int(os.environ.get("SCRIBE_CATALOG_BUDGET", "6000"))
except ValueError:
    CATALOG_BUDGET = 6000


def ensure_dirs() -> None:
    KNOWLEDGE_DIR.mkdir(parents=True, exist_ok=True)
    SHARED_DIR.mkdir(parents=True, exist_ok=True)
