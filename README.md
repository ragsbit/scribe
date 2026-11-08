# scribe

**Claude Code forgets what it learned when a session ends. scribe makes it write each lesson down where the next session will find it.** Free and open source (MIT); the hooks are plain Python.

```
/plugin marketplace add ragsbit/scribe
/plugin install scribe@scribe
/reload-plugins
```

Found this through a [Ragsbit](https://www.youtube.com/@ragsbit) Short? This is the memory from the videos. Ragsbit's human built it in May 2026 for their own Claude Code work and used it for five months before sharing it (216 notes across their projects so far); Ragsbit, an AI character, keeps its lessons in it too. If scribe saves you one repeated mistake, a star tells Ragsbit it was worth sharing.

---

**Agentic Skill Improve Loop** — Claude Code plugin that reflects on every 10th response and routes new findings to the right place: personal Memory, project Knowledge, Shared notes read in every project, a one-line CLAUDE.md pointer, a repo test, or a skill fix. At session start it shows the project map and lists the notes' titles, so Claude knows what exists.

Coding agents forget what they learned when a session ends, so the same trap costs you twice. scribe makes Claude stop every 10 turns, ask what it just learned, and write it where the next session will find it. A mistake that comes back after it was written down gets a failing test, because a test stops a repeat and a note does not; when no test can catch it, it gets a line in CLAUDE.md.

Built by the human behind [Ragsbit](https://www.youtube.com/@ragsbit) in May 2026 and shared on 2026-11-01; Ragsbit, an AI character run by that human, uses it every day.

Version **0.5.1** — see [Changes](#changes).

---

## What it does

Three hooks and three skills, in three layers.

**Find what is known**

1. **SessionStart hook** — Starts this session's turn count over on a new conversation (startup, `/clear`); a resume or a compaction keeps it. Puts the project map first: `.scribe/knowledge/MAP.md`, a short page of key facts and "situation → search words → note" lines, cut to `SCRIBE_MAP_BUDGET` characters (default 1500). Then lists one line per note (title — description): shared notes first, then this project's, newest first, everything within `SCRIBE_CATALOG_BUDGET` characters (default 6000). Whole notes are not injected (until 0.1.2 that grew past 200KB); Claude opens a note when its title fits the task. When the list does not fit, descriptions get shorter, then the project's titles give way to one pointer line (count, where to search, the project's index if it has one). What every session must know goes into CLAUDE.md as one line.
2. **`/scribe-search` skill** — Searches the notes for several spellings of a topic at once (the user's language and English, with and without spaces, transliterations, abbreviations), ranks them with `scripts/scribe.py` (name, description, body, and the project map's pointers), reads the top 3, and checks their status claims ("fixed", "works", a version) against the code — those date from the note's `updated:`. A note that turned out wrong is fixed on the spot.

**Write it down**

3. **Stop hook** — Counts this session's turns. Every 10th turn, and at the first turn end after the conversation was compacted, injects a `[SCRIBE] Reflect...` prompt asking Claude whether anything from the last turns should be recorded, and where. Each session keeps its own count, so sessions open in the same project neither reset nor share it, and a long session that compacts before ten turns is still reviewed. If nothing fits → Claude responds `"Nothing to record."` and moves on.
4. **`/scribe-review` skill** — Run by the reflect prompt (or invoked manually). Follows the project's own record rules (CLAUDE.md / AGENTS.md) when it has them, searches before writing so an existing note is updated instead of duplicated, checks status statements before bumping `updated:`, keeps the project map in step, and asks before writing unless the user or the project says records need no approval.

**Measure and tidy**

5. **PreToolUse hook** — Runs on Read only. A Read of a shared or project note is logged as a use: `.scribe/hits.jsonl` for this project's notes, `.hits.jsonl` in the shared folder for shared notes. The tool call itself goes on unchanged. Nothing in the logs leaves your machine, and they hold note names and times — not the tool input.
6. **`/scribe-garden` skill** — Once a month: merges duplicate notes, re-checks old status claims, and proposes pruning notes that no session opened in 60 days. Session start reminds you when a month has passed.

---

## Install

In Claude Code:

```
/plugin marketplace add ragsbit/scribe
/plugin install scribe@scribe
/reload-plugins
```

Or add the marketplace to `~/.claude/settings.json` yourself:

```json
{
  "extraKnownMarketplaces": {
    "scribe": {
      "source": {
        "source": "git",
        "url": "https://github.com/ragsbit/scribe.git"
      }
    }
  }
}
```

The hooks need Python 3.8+ (`python3`; `python` on Windows). They use the standard library only.

---

## Routing rules

If the project's CLAUDE.md or AGENTS.md says where records go, that wins; the table gives the defaults.

| Destination | What goes there | Read when |
|---|---|---|
| **Memory** (personal, Claude Code auto-managed) | User corrections of how Claude works, reports or asks; preferences; context not derivable from code | Built into Claude Code |
| **Knowledge** (git-tracked; the project's record folders, default `.scribe/knowledge/`) | Domain pitfalls, time-saving techniques, architectural decisions | Title at session start (`.scribe/knowledge/` only); body when opened or searched |
| **Project map** (`.scribe/knowledge/MAP.md`) | Key facts and "situation → search words → note" lines, kept in step by `/scribe-review` | First thing at session start |
| **Shared notes** (`~/.claude/scribe/shared/`) | Lessons that hold in other projects too: shell and OS traps, tools, APIs, data vendors, Claude Code behavior; a short note linking to the project record when that is where the full record lives | Title at session start in every project; body when opened or searched |
| **One line in CLAUDE.md** (and AGENTS.md) | Something every session must know, or a mistake that keeps coming back and no test can catch; the line points to its note | Every session |
| **Repo test** | A technical mistake that recurred although a note existed | Every test run |
| **Skill file** | A fix for a skill that gave a wrong result | When the skill runs |

**No duplication.** Personal corrections never go to knowledge. Domain rules never go to memory. Link instead of copying.

---

## Runtime artifacts

When scribe runs in any project, it creates:

```
<project-root>/
└── .scribe/
    ├── knowledge/*.md   ← git-tracked team knowledge
    ├── knowledge/MAP.md ← the project map (git-tracked; written by /scribe-review)
    ├── hits.jsonl       ← Reads of this project's notes, for /scribe-garden
    ├── garden_last      ← date of the last /scribe-garden
    ├── hook.log         ← hook execution log
    └── turns/*.json     ← Stop hook turn count, one file per session (removed after 14 days)
```

Shared notes live outside any project, in `~/.claude/scribe/shared/*.md` (created on first run), with their own `.hits.jsonl` and `.garden_last`.

Add to project `.gitignore`:

```
.scribe/
!.scribe/knowledge/
!.scribe/knowledge/**
```

---

## Configuration

`REVIEW_INTERVAL` (default `10`) — change in `hooks/stop.py` to adjust reflection frequency.

`CLAUDE_PROJECT_DIR` — if set by Claude Code, used as project root for `.scribe/`. Falls back to current working directory.

`SCRIBE_SHARED_DIR` (default `~/.claude/scribe/shared`) — folder of shared notes listed in every project.

`SCRIBE_CATALOG_BUDGET` (default `6000`) — most characters session start may add: the project map and the title list together.

`SCRIBE_MAP_BUDGET` (default `1500`) — most characters of the project map (at most half of the catalog budget).

---

## Plugin layout

```
scribe/
├── .claude-plugin/
│   ├── marketplace.json
│   └── plugin.json
├── hooks/
│   ├── _scribe_core.py     ← notes, the project map, hits logs (import-light)
│   ├── _scribe_paths.py    ← shared path resolver
│   ├── _scribe_turns.py    ← per-session turn count
│   ├── session_start.py    ← updates the turn count, shows the map, lists note titles
│   ├── pre_tool_use.py     ← logs a Read of a note as a use (runs on Read only)
│   ├── stop.py             ← counts turns, injects reflect prompt every 10 and after a compaction
│   ├── run-hook.cmd        ← cross-platform wrapper (Windows + Unix)
│   └── hooks.json          ← Claude Code hook registration
├── scripts/
│   └── scribe.py           ← search and garden reports for the skills
├── skills/
│   ├── scribe-review/
│   │   ├── SKILL.md
│   │   └── templates/
│   │       ├── knowledge.md
│   │       └── map.md
│   ├── scribe-search/
│   │   └── SKILL.md
│   └── scribe-garden/
│       └── SKILL.md
└── tests/
    └── test_hooks.py       ← runs the hooks through run-hook.cmd and the scripts (python3 -m unittest)
```

---

## Changes

**0.5.1** — The reflect prompt reaches long sessions.
- Why: every SessionStart reset one turn counter shared by all sessions of a project, and Claude Code runs SessionStart again when it compacts or resumes a conversation. A two-day session whose turns were an hour or two long compacted six times, never counted past 11, and was reviewed once. In a project with several sessions open, a new session reset the others' count, and the prompt came in whichever session ended the tenth turn.
- Each session now has its own count in `.scribe/turns/`. A new conversation (startup, `/clear`) starts it over, a resume keeps it, and a compaction keeps it and brings the reflect prompt at the next turn end, with a line to read the summary's list of user messages. The old `.scribe/turn_count` is removed at session start.

**0.5.0** — Note triggers removed.
- Why: in three days of real use they matched about a dozen tool calls and caught one real mistake, an unquoted `echo` of equals signs in zsh that would only have cost a retry. The rest matched text inside scripts, notes and records rather than real commands, and the blocks interrupted work. scribe keeps a feature only if it is useful.
- The PreToolUse hook now runs on Read only, to log a Read of a note as a use. Session start lists notes newest first again, the reflect prompt no longer lists this session's hits, and `/scribe-garden` no longer proposes promotions.
- Old `triggers:`, `enforce:` and `fix:` lines in notes are ignored, and an old `.scribe/triggers.json` can be deleted.

**0.4.0** — Three layers on top of the reflect loop.
- Find: the project map (`.scribe/knowledge/MAP.md`) comes first at session start; `/scribe-search` searches spelling variants together and re-checks status claims.
- Stop: notes can carry `triggers:`; a PreToolUse hook warns on a matching tool call, or blocks it with the fix (`enforce: block`), and suggests the block when a warning repeats.
- Measure and tidy: hits logs; notes hit in the last 30 days rise to the top of the session-start list; the reflect prompt lists this session's hits; monthly `/scribe-garden` merges duplicates, re-checks status claims, and proposes notes to prune or promote.

**0.3.0** — First public release: reflect every 10 turns, route findings, list note titles at session start.

---

## License

MIT
