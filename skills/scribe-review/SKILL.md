---
name: scribe-review
description: Review the current session and route each new finding to one place: Claude Code Memory (personal corrections/preferences), project knowledge (the record folders the project's CLAUDE.md names, default .scribe/knowledge/), shared notes read in every project (~/.claude/scribe/shared/), a one-line pointer in CLAUDE.md, a repo test, or a fix to a skill file. Triggered by the [SCRIBE] reflection prompt injected every 10 turns by the Stop hook, or invoked manually when something worth recording surfaces mid-conversation.
---

# /scribe-review

## Step 0: Note today's date
Today's date is already in the [SCRIBE] prompt that triggered this review.
Use it for `updated:` fields and staleness judgment. Do NOT run `date` — it's already provided.

---

## Step 1: Read the project's record rules
If the project's CLAUDE.md (or AGENTS.md) says where records go — folders, file naming,
an index to regenerate — follow it. The defaults below apply only where it is silent.

---

## Step 2: Route each finding to one place
Do NOT duplicate content between destinations; link instead.

→ Claude Code Memory (personal)
  - User corrected how you work, report or ask
  - User has a preference or working style worth remembering
  - Project context that is not derivable from code or docs

→ Project knowledge (git-tracked; the project's record folders, default `.scribe/knowledge/`)
  - A pitfall the team will likely hit (not obvious from reading code/docs)
  - A technique that saves significant time
  - An architectural decision future team members should understand

→ Shared notes (all projects; `~/.claude/scribe/shared/`, or `$SCRIBE_SHARED_DIR`)
  - A lesson that holds outside this project: shell and OS traps, tools, APIs, data
    vendors, Claude Code behavior
  - Write it so it stands on its own in another project. If the full record belongs to
    this project (with its commit or test), keep it here and end the shared note with
    `**Source:**` and the record's absolute path.

→ One line in CLAUDE.md (and AGENTS.md if present)
  - At session start only titles are listed (shared notes first, then this project's,
    within a size budget; a long project list collapses to one pointer line). Write a
    `description:` that says when the note matters.
  - If every session must know the rule itself, add one line with its trigger that
    points to the note.

→ Repo test
  - A technical mistake that recurred although a note existed: add a test that fails on
    the pattern, plus the note and the CLAUDE.md line. A test stops the repeat; a note does not.

→ Skill file
  - A skill gave a wrong result and a better way was found after trying alternatives:
    fix that skill's SKILL.md directly.

Do NOT write anywhere:
  - Things derivable from reading code or docs
  - One-time task details

---

## Step 3: Search before writing (upsert)
Only titles are in your context, so search the notes themselves first:

```bash
grep -rilE "<keyword>|<variant>" ~/.claude/scribe/shared .scribe/knowledge <the project's record folders> --include="*.md"
```

- Found → edit that file and set `updated:` to today. Do not create a second file on the same topic.
- Before leaving a status statement in a file you touch ("not fixed", "works", a current value
  or version), check it against the code or the real environment. Bumping `updated:` makes the
  whole page look checked today: correct what is wrong, mark "(unverified)" what you could not check.
- Not found → create a new file.

If the project keeps an index of its records, update or regenerate it.

---

## Step 4: Ask, write, report
Ask the user before writing, unless the user or the project instructions say records need no approval.
After writing, report in one line what was recorded and where.

---

## Knowledge file format
Use the template at `skills/scribe-review/templates/knowledge.md` — fill in `{{placeholders}}` —
unless the project defines its own format.
Replace `{{today}}` with the date from the [SCRIBE] prompt.

Default locations: `.scribe/knowledge/<slug>.md` at the project root; shared notes in
`~/.claude/scribe/shared/<slug>.md`.
