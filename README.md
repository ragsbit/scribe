# scribe

**Agentic Skill Improve Loop** — Claude Code plugin that reflects on every 10th response and routes new findings to the right place: personal Memory, project Knowledge, Shared notes read in every project, a trigger on a note, a one-line CLAUDE.md pointer, a repo test, or a skill fix. At session start it shows the project map and lists the notes' titles; before every tool call it checks the notes' triggers, so a known mistake is caught at the moment it is about to happen.

Coding agents forget what they learned when a session ends, so the same trap costs you twice. scribe makes Claude stop every 10 turns, ask what it just learned, and write it where the next session will find it. A title in a list is not always enough, though: with a note about zsh listed at session start, Claude still ran `echo =====` twice in the Mac's zsh, where it fails. So since 0.4 a note can carry a trigger that speaks up on the tool call itself — a warning first, a block with the fix once the mistake comes back — and a mistake that keeps coming back gets a failing test.

Made and used every day by [Ragsbit](https://www.youtube.com/@ragsbit), an AI character run by a human.

Version **0.4.0** — see [Changes](#changes).

---

## What it does

Three hooks and three skills, in three layers.

**Find what is known**

1. **SessionStart hook** — Resets the turn counter. Puts the project map first: `.scribe/knowledge/MAP.md`, a short page of key facts and "situation → search words → note" lines, cut to `SCRIBE_MAP_BUDGET` characters (default 1500). Then lists one line per note (title — description): shared notes first, then this project's, everything within `SCRIBE_CATALOG_BUDGET` characters (default 6000). Notes whose triggers fired in the last 30 days come first and show `[N hits]`; the rest follow, newest first. Whole notes are not injected (until 0.1.2 that grew past 200KB); Claude opens a note when its title fits the task. When the list does not fit, descriptions get shorter, then the project's titles give way to one pointer line (count, where to search, the project's index if it has one). What every session must know goes into CLAUDE.md as one line.
2. **`/scribe-search` skill** — Searches the notes for several spellings of a topic at once (the user's language and English, with and without spaces, transliterations, abbreviations), ranks them with `scripts/scribe.py` (name, description, triggers, body, and the project map's pointers), reads the top 3, and checks their status claims ("fixed", "works", a version) against the code — those date from the note's `updated:`. A note that turned out wrong is fixed on the spot.

**Stop a known mistake**

3. **PreToolUse hook** — Matches every pending tool call against the `triggers:` of all shared and project notes. On a match the note speaks up next to the tool result (a warning). A note with `enforce: block` denies the call instead and tells Claude its `fix:`. A warning that fires again says how often it fired and suggests the block. Triggers are cached in `.scribe/triggers.json` and rebuilt only when a note changes; a call costs about 22 ms on a Mac, most of it Python start-up, with 300 notes and 100 triggers about 25 ms.
4. **Stop hook** — Counts turns. Every 10th turn, injects a `[SCRIBE] Reflect...` prompt asking Claude whether anything from the last turns should be recorded, and where, and lists the triggers that fired in this session. If nothing fits → Claude responds `"Nothing to record."` and moves on.
5. **`/scribe-review` skill** — Triggered by the reflect prompt (or invoked manually). Follows the project's own record rules (CLAUDE.md / AGENTS.md) when it has them, searches before writing so an existing note is updated instead of duplicated, checks status statements before bumping `updated:`, adds a trigger when the mistake shows in a tool input, keeps the project map in step, and asks before writing unless the user or the project says records need no approval.

**Measure and tidy**

6. **Hits logs** — Every trigger match is logged: `.scribe/hits.jsonl` for this project's notes, `.hits.jsonl` in the shared folder for shared notes. A Read of a note is logged too, as a use. Nothing in the logs leaves your machine, and they hold note names, tools and times — not the tool input.
7. **`/scribe-garden` skill** — Once a month: merges duplicate notes, re-checks old status claims, proposes pruning notes that no trigger hit and no session opened in 60 days, and proposes promoting notes whose trigger fired 3+ times — a warning to `enforce: block`, a block to a repo test. Session start reminds you when a month has passed.

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

## Triggers

A note about a mistake you can see in a tool input — a command, a file path, a URL, an edit — can carry triggers in its front matter:

```yaml
---
name: zsh-is-the-mac-shell
description: The Bash tool on a Mac runs zsh; `echo =====` fails with "= not found".
updated: 2026-11-01
triggers:
  Bash: 'echo\s+='              # tool: regex, searched in every string of the input except `description`
  Edit.new_string: 'utcnow\('    # tool.field: only that field
  Write|Edit:                    # several tools; several patterns as a list
    - '(^|/)\.env$'
enforce: block                   # optional; without it the note warns
fix: "Quote it: echo '====='"   # one line, shown with the warning or the block
---
```

- **Tool**: the same rules as a hook matcher. `*` is every tool; names joined with `|` are exact; anything else is a regex searched in the tool name, such as `mcp__github__.*`. On Windows shell commands may come as `PowerShell`, so write `Bash|PowerShell` where that matters.
- **Pattern**: a Python regex, case-sensitive (`(?i)` to ignore case), best in single quotes. Match the mistake, not its fix: `echo\s+=` fires on `echo =====`, not on `echo '====='`.
- **Default**: a warning next to the tool result. When it fires again, the warning says so and suggests `enforce: block`. Set `enforce: warn` to keep it a warning without the suggestion.
- **`enforce: block`**: the call is denied, and Claude gets the note's description and `fix:` (or its `**How to apply:**` line) and rewrites the call.
- A pattern that does not compile is skipped, and session start names the note.

---

## Routing rules

If the project's CLAUDE.md or AGENTS.md says where records go, that wins; the table gives the defaults.

| Destination | What goes there | Read when |
|---|---|---|
| **Memory** (personal, Claude Code auto-managed) | User corrections of how Claude works, reports or asks; preferences; context not derivable from code | Built into Claude Code |
| **Knowledge** (git-tracked; the project's record folders, default `.scribe/knowledge/`) | Domain pitfalls, time-saving techniques, architectural decisions | Title at session start (`.scribe/knowledge/` only); body when opened or searched |
| **Project map** (`.scribe/knowledge/MAP.md`) | Key facts and "situation → search words → note" lines, kept in step by `/scribe-review` | First thing at session start |
| **Shared notes** (`~/.claude/scribe/shared/`) | Lessons that hold in other projects too: shell and OS traps, tools, APIs, data vendors, Claude Code behavior; a short note linking to the project record when that is where the full record lives | Title at session start in every project; body when opened or searched |
| **Trigger** (`triggers:` on a note) | A mistake that shows in a tool input | Before every matching tool call |
| **One line in CLAUDE.md** (and AGENTS.md) | Something every session must know, pointing to its note | Every session |
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
    ├── hits.jsonl       ← trigger matches and reads of this project's notes
    ├── triggers.json    ← trigger cache for the PreToolUse hook
    ├── garden_last      ← date of the last /scribe-garden
    ├── hook.log         ← hook execution log
    └── turn_count       ← Stop hook counter
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
│   ├── _scribe_core.py     ← notes, triggers, trigger cache, hits logs (import-light)
│   ├── _scribe_paths.py    ← shared path resolver
│   ├── session_start.py    ← resets the turn counter, shows the map, lists note titles
│   ├── pre_tool_use.py     ← matches tool calls against note triggers: warn or block
│   ├── stop.py             ← counts turns, injects reflect prompt every 10
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

**0.4.0** — Three layers on top of the reflect loop.
- Find: the project map (`.scribe/knowledge/MAP.md`) comes first at session start; `/scribe-search` searches spelling variants together and re-checks status claims.
- Stop: notes can carry `triggers:`; a PreToolUse hook warns on a matching tool call, or blocks it with the fix (`enforce: block`), and suggests the block when a warning repeats.
- Measure and tidy: hits logs; notes hit in the last 30 days rise to the top of the session-start list; the reflect prompt lists this session's hits; monthly `/scribe-garden` merges duplicates, re-checks status claims, and proposes notes to prune or promote.

**0.3.0** — First public release: reflect every 10 turns, route findings, list note titles at session start.

---

## License

MIT
