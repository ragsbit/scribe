"""Run the hooks the way Claude Code does (through run-hook.cmd), and the
scripts/scribe.py command line, in temp folders.

python3 -m unittest discover -s tests
"""
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOOKS = ROOT / "hooks"


def run(hook, project, shared, stdin="{}", budget=None, env_extra=None, raw=False):
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(project), SCRIBE_SHARED_DIR=str(shared))
    if budget is not None:
        env["SCRIBE_CATALOG_BUDGET"] = str(budget)
    env.update(env_extra or {})
    # The wrapper has no shebang (it is also a .cmd file); Claude Code's shell runs it as
    # a shell script, so run it with sh the same way.
    proc = subprocess.run(["/bin/sh", str(HOOKS / "run-hook.cmd"), hook], input=stdin, env=env,
                          capture_output=True, text=True, check=True)
    if raw:
        return proc
    return json.loads(proc.stdout) if proc.stdout.strip() else None


def call(project, shared, tool, tool_input, session="sess-0001", **kw):
    """One PreToolUse event."""
    payload = json.dumps({"session_id": session, "hook_event_name": "PreToolUse",
                          "tool_name": tool, "tool_input": tool_input})
    return run("pre-tool-use", project, shared, stdin=payload, **kw)


def note(folder, stem, description="", updated="2026-10-29", extra=(), body="Body line."):
    folder.mkdir(parents=True, exist_ok=True)
    head = ["---", f"name: {stem}"]
    head += [f"description: {description}"] if description else []
    head += [f"updated: {updated}", *extra, "---", "", body]
    (folder / f"{stem}.md").write_text("\n".join(head), encoding="utf-8")


def zsh_note(folder, enforce="block"):
    """The note as 0.4 wrote it on 2026-11-01: its front matter still has `triggers:`,
    `enforce:` and `fix:`, which 0.5 ignores."""
    note(folder, "zsh-is-the-mac-shell",
         "The Bash tool on a Mac runs zsh: `echo =====` fails with \"= not found\".",
         updated="2026-11-01",
         extra=["triggers:", "  Bash: 'echo\\s+='   # a word that starts with = after echo",
                "  Write|Edit:", "    - '(^|/)\\.env$'",
                f"enforce: {enforce}", "fix: \"Quote it: echo '====='\""])


def iso(seconds):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(seconds))


def write_log(path, events):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(e) + "\n" for e in events), encoding="utf-8")


def read_log(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


class Folders(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.project, self.shared = base / "proj", base / "shared"
        self.knowledge = self.project / ".scribe" / "knowledge"
        self.project.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def context(self, **kw):
        out = run("session-start", self.project, self.shared, **kw)
        return out and out["hookSpecificOutput"]["additionalContext"]

    def call(self, tool, tool_input, **kw):
        return call(self.project, self.shared, tool, tool_input, **kw)


class SessionStartCatalog(Folders):
    def test_lists_shared_first_then_project(self):
        note(self.shared, "zsh-traps", "zsh is the Mac shell")
        note(self.knowledge, "deploy-gate", "deploy only through the gate")
        text = self.context()
        self.assertIn("- zsh-traps — zsh is the Mac shell", text)
        self.assertIn("- deploy-gate — deploy only through the gate", text)
        self.assertLess(text.index("zsh-traps"), text.index("deploy-gate"))

    def test_newest_first(self):
        note(self.shared, "old", "old", updated="2026-01-01")
        note(self.shared, "new", "new", updated="2026-10-29")
        text = self.context()
        self.assertLess(text.index("- new"), text.index("- old"))

    def test_no_output_without_notes_and_counter_reset(self):
        legacy = self.project / ".scribe" / "turn_count"
        legacy.parent.mkdir(parents=True, exist_ok=True)
        legacy.write_text("7")
        start = '{"session_id": "s-1", "source": "startup"}'
        self.assertIsNone(run("session-start", self.project, self.shared, stdin=start))
        state = json.loads((self.project / ".scribe" / "turns" / "s-1.json").read_text())
        self.assertEqual(state, {"count": 0, "review_next": False})
        self.assertFalse(legacy.exists())  # the shared counter of 0.5.0 is gone
        self.assertTrue(self.shared.is_dir())

    def test_large_project_folds_to_pointer_within_budget(self):
        note(self.shared, "zsh-traps", "zsh is the Mac shell")
        for i in range(600):
            note(self.knowledge, f"long-note-name-for-folding-{i:04d}", "x" * 120)
        (self.project / "docs").mkdir()
        (self.project / "docs" / "INDEX.md").write_text("index", encoding="utf-8")
        text = self.context(budget=6000)
        self.assertLessEqual(len(text), 6000)
        self.assertIn("- zsh-traps — zsh is the Mac shell", text)
        self.assertIn("600 notes, too many to list", text)
        self.assertIn("docs/INDEX.md", text)
        self.assertNotIn("long-note-name-for-folding-0000", text)

    def test_tiny_budget_still_fits(self):
        for i in range(50):
            note(self.shared, f"shared-note-{i:02d}", "y" * 100)
        text = self.context(budget=400)
        self.assertLessEqual(len(text), 400)
        self.assertIn("older shared notes not listed", text)

    def test_title_folded_and_heading_fallbacks(self):
        self.knowledge.mkdir(parents=True)
        (self.knowledge / "a.md").write_text("---\ntitle: Title only\ntags: [x]\n---\n\nBody",
                                             encoding="utf-8")
        (self.knowledge / "b.md").write_text("---\nname: b\ndescription: >-\n  folded\n  text\n---\nBody",
                                             encoding="utf-8")
        (self.knowledge / "c.md").write_text("# Heading only\n\nBody", encoding="utf-8")
        (self.knowledge / "INDEX.md").write_text("# index", encoding="utf-8")
        (self.knowledge / "log.md").write_text("# log", encoding="utf-8")
        text = self.context()
        self.assertIn("- a — Title only", text)
        self.assertIn("- b — folded text", text)
        self.assertIn("- c — Heading only", text)
        self.assertNotIn("- INDEX", text)
        self.assertNotIn("- log", text)
        self.assertIn("found with grep", text)
        self.assertIn("`updated:`", text)

    def test_description_quoting(self):
        """A description that starts with a quote but goes on stays whole; a quoted one loses
        its quotes, and a comment after them."""
        self.shared.mkdir()
        (self.shared / "q.md").write_text(
            '---\nname: q\ndescription: "Hedge the crash" is a recurring ask\n---\nBody', encoding="utf-8")
        (self.shared / "r.md").write_text(
            "---\nname: r\ndescription: 'it''s quoted'   # comment\n---\nBody", encoding="utf-8")
        text = self.context()
        self.assertIn('- q — "Hedge the crash" is a recurring ask', text)
        self.assertIn("- r — it's quoted", text)

    def test_old_trigger_lines_are_ignored(self):
        """A note from 0.4 lists by its description; its `triggers:` block, even a pattern that
        does not compile, adds no line, and a key after the block still reads."""
        zsh_note(self.shared)
        note(self.knowledge, "broken", updated="2026-10-30",
             extra=["triggers:", "  Bash: 'echo ('", "enforce: warn", "description: still read"])
        text = self.context()
        self.assertIn('- zsh-is-the-mac-shell — The Bash tool on a Mac runs zsh: `echo =====` fails '
                      'with "= not found".', text)
        self.assertIn("- broken — still read", text)
        for word in ("trigger", "enforce", "block", "Quote it", "skipped", "["):
            self.assertNotIn(word, text)
        self.assertFalse((self.project / ".scribe" / "triggers.json").exists())


class SessionStartMapAndLogs(Folders):
    MAP = ("---\nname: map\nupdated: 2026-11-01\n---\n\n## Key facts\n- Ships only with `make release`\n\n"
           "## Situation → search words → note\n- before a release → `release|deploy|ship` → deploy-gate\n")

    def test_project_map_comes_first(self):
        note(self.shared, "zsh-traps", "zsh is the Mac shell")
        note(self.knowledge, "deploy-gate", "deploy only through the gate")
        (self.knowledge / "MAP.md").write_text(self.MAP, encoding="utf-8")
        text = self.context()
        self.assertTrue(text.startswith("## scribe project map (`.scribe/knowledge/MAP.md`)\n## Key facts"))
        self.assertIn("- before a release → `release|deploy|ship` → deploy-gate", text)
        self.assertLess(text.index("Key facts"), text.index("## scribe notes"))
        self.assertNotIn("name: map", text)
        self.assertNotIn("- map", text)  # the map is not listed as a note

    def test_long_map_is_cut_and_everything_fits(self):
        self.knowledge.mkdir(parents=True)
        lines = "\n".join(f"- situation {i} → `word{i}` → note-{i}" for i in range(300))
        (self.knowledge / "MAP.md").write_text(f"---\nname: map\n---\n{lines}\n", encoding="utf-8")
        for i in range(40):
            note(self.shared, f"shared-note-{i:02d}", "z" * 120)
        text = self.context(budget=3000)
        self.assertLessEqual(len(text), 3000)
        self.assertIn("… (cut; read `.scribe/knowledge/MAP.md` for the rest)", text)
        self.assertNotIn("situation 299", text)
        self.assertIn("## scribe notes", text)

    def test_the_hits_log_does_not_change_the_order(self):
        """Newest first, whatever the log holds: reads, or the warnings 0.4 wrote."""
        now = time.time()
        note(self.shared, "old-but-read", "a", updated="2026-01-01")
        note(self.shared, "newest", "b", updated="2026-10-30")
        note(self.shared, "old-warned", "c", updated="2026-01-02")
        write_log(self.shared / ".hits.jsonl", [{"t": iso(now - 400 * 86400), "kind": "start"}]
                  + [{"t": iso(now - 60), "note": "old-but-read", "kind": "read"}] * 9
                  + [{"t": iso(now - 3600), "note": "old-warned", "kind": "warn"}] * 5)
        text = self.context()
        self.assertLess(text.index("- newest — b"), text.index("- old-warned — c"))
        self.assertLess(text.index("- old-warned — c"), text.index("- old-but-read — a"))
        self.assertNotIn("[", text)  # no [N hits] marks

    def test_garden_reminder_after_a_month(self):
        note(self.shared, "a", "x")
        write_log(self.shared / ".hits.jsonl", [{"t": iso(time.time() - 40 * 86400), "kind": "start"}])
        self.assertIn("notes not gardened for 40 days. /scribe-garden", self.context())
        (self.shared / ".garden_last").write_text(iso(time.time() - 86400), encoding="utf-8")
        self.assertNotIn("not gardened", self.context())

    def test_fresh_install_starts_both_hit_logs_quietly(self):
        note(self.shared, "a", "x")
        note(self.knowledge, "b", "y")
        self.assertNotIn("not gardened", self.context())
        for log in (self.shared / ".hits.jsonl", self.project / ".scribe" / "hits.jsonl"):
            self.assertEqual(read_log(log)[0]["kind"], "start")


class PreToolUse(Folders):
    def test_registered_for_read_only(self):
        hooks = json.loads((HOOKS / "hooks.json").read_text(encoding="utf-8"))["hooks"]
        self.assertEqual([entry["matcher"] for entry in hooks["PreToolUse"]], ["Read"])

    def test_never_blocks_or_warns(self):
        """Not even for a note from 0.4 whose `triggers:` match the call and say `enforce: block`."""
        zsh_note(self.shared)
        note(self.knowledge, "any-tool", "x", extra=["triggers:", "  '*': 'qqq-marker'", "enforce: block"])
        for tool, tool_input in (("Bash", {"command": "echo ====="}),
                                 ("Write", {"file_path": "/repo/.env", "content": "A=1"}),
                                 ("Grep", {"pattern": "qqq-marker"}),
                                 ("Read", {"file_path": "/repo/qqq-marker/echo =====.txt"}),
                                 ("Read", {"file_path": str(self.shared / "zsh-is-the-mac-shell.md")})):
            proc = self.call(tool, tool_input, raw=True)
            self.assertEqual((proc.returncode, proc.stdout), (0, ""), tool)
        logs = (self.shared / ".hits.jsonl", self.project / ".scribe" / "hits.jsonl")
        kinds = [e["kind"] for log in logs if log.exists() for e in read_log(log)]
        self.assertEqual(sorted(kinds), ["read", "start"])  # only the Read of the note
        self.assertFalse((self.project / ".scribe" / "triggers.json").exists())

    def test_reading_a_note_is_logged(self):
        zsh_note(self.shared)
        note(self.knowledge, "local", "y")
        self.assertIsNone(self.call("Read", {"file_path": str(self.shared / "zsh-is-the-mac-shell.md")},
                                    session="abcdefgh-1234"))
        self.call("Read", {"file_path": str(self.knowledge / "local.md")})
        self.call("Read", {"file_path": os.path.realpath(self.knowledge / "local.md")})
        self.call("Read", {"file_path": str(self.project / "README.md")})
        self.call("Read", {"file_path": str(self.knowledge / "MAP.md")})
        self.call("Bash", {"command": f"cat {self.knowledge / 'local.md'}"})  # only a Read counts
        self.assertEqual([(e["note"], e["kind"], e["tool"], e["session"])
                          for e in read_log(self.shared / ".hits.jsonl")[1:]],
                         [("zsh-is-the-mac-shell", "read", "Read", "abcdefgh")])
        self.assertEqual([(e["note"], e["kind"]) for e in read_log(self.project / ".scribe" / "hits.jsonl")[1:]],
                         [("local", "read"), ("local", "read")])

    def test_stays_import_light(self):
        """It runs before every Read, so it must not import logging or pathlib (~8 ms)."""
        note(self.shared, "plain", "x")
        payload = json.dumps({"tool_name": "Read", "tool_input": {"file_path": str(self.shared / "plain.md")}})
        proc = run("pre-tool-use", self.project, self.shared, stdin=payload, raw=True,
                   env_extra={"PYTHONPROFILEIMPORTTIME": "1"})
        imported = {line.rsplit("|", 1)[-1].strip() for line in proc.stderr.splitlines()}
        self.assertIn("_scribe_core", imported)
        self.assertFalse(imported & {"logging", "pathlib", "calendar"}, imported)

    def test_broken_input_never_blocks(self):
        zsh_note(self.shared)
        for stdin in ("", "not json", '["Read"]', '{"tool_name": "Read", "tool_input": "x.md"}',
                      '{"tool_name": "Read", "tool_input": {"file_path": 7}}'):
            self.assertIsNone(run("pre-tool-use", self.project, self.shared, stdin=stdin), stdin)


def start(project, shared, session, source):
    run("session-start", project, shared,
        stdin=json.dumps({"session_id": session, "source": source}))


def stops(project, shared, session, n):
    """n Stop events of one session; the 1-based turns that got the reflect prompt."""
    outs = [run("stop", project, shared, stdin=json.dumps({"session_id": session}))
            for _ in range(n)]
    return [i + 1 for i, o in enumerate(outs) if o], outs


class StopPrompt(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.project, self.shared = Path(self._tmp.name) / "proj", Path(self._tmp.name) / "shared"
        self.project.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def test_every_tenth_turn_and_names_shared_folder(self):
        start(self.project, self.shared, "t", "startup")
        fired, outs = stops(self.project, self.shared, "t", 20)
        self.assertEqual(fired, [10, 20])
        self.assertEqual(outs[9]["decision"], "block")
        self.assertIn(str(self.shared), outs[9]["reason"])
        self.assertIn("→ TEST:", outs[9]["reason"])
        self.assertNotIn("compacted", outs[9]["reason"])
        self.assertIsNone(run("stop", self.project, self.shared,
                              stdin='{"session_id": "t", "stop_hook_active": true}'))
        # the prompt's own follow-up Stop is not counted as a turn
        self.assertEqual(stops(self.project, self.shared, "t", 10)[0], [10])

    def test_compaction_keeps_the_count_and_reviews_at_next_stop(self):
        """2026-11-07: a long session compacted six times and was reviewed once in two days,
        because every compaction reset the count before it reached ten."""
        start(self.project, self.shared, "long", "startup")
        self.assertEqual(stops(self.project, self.shared, "long", 6)[0], [])
        start(self.project, self.shared, "long", "compact")
        fired, outs = stops(self.project, self.shared, "long", 1)
        self.assertEqual(fired, [1])
        self.assertIn("compacted", outs[0]["reason"])
        self.assertIn("→ TEST:", outs[0]["reason"])
        self.assertEqual(stops(self.project, self.shared, "long", 10)[0], [10])

    def test_compaction_with_few_turns_between_still_reviews(self):
        """Three turns between compactions: 0.5.0 never reviewed; now each compaction does."""
        start(self.project, self.shared, "long", "startup")
        fired = []
        for _ in range(4):
            fired.append(stops(self.project, self.shared, "long", 3)[0])
            start(self.project, self.shared, "long", "compact")
        self.assertEqual(fired, [[], [1], [1], [1]])
        self.assertEqual(stops(self.project, self.shared, "long", 1)[0], [1])

    def test_resume_keeps_the_count(self):
        start(self.project, self.shared, "r", "startup")
        stops(self.project, self.shared, "r", 6)
        start(self.project, self.shared, "r", "resume")
        self.assertEqual(stops(self.project, self.shared, "r", 4)[0], [4])

    def test_startup_and_clear_start_over(self):
        for source in ("startup", "clear"):
            start(self.project, self.shared, "c", "startup")
            stops(self.project, self.shared, "c", 6)
            start(self.project, self.shared, "c", source)
            self.assertEqual(stops(self.project, self.shared, "c", 10)[0], [10], source)

    def test_sessions_in_one_project_count_apart(self):
        """2026-11-05: four sessions of one project added to one counter, and the prompt came
        in the session that happened to end the tenth turn."""
        start(self.project, self.shared, "a", "startup")
        self.assertEqual(stops(self.project, self.shared, "a", 6)[0], [])
        start(self.project, self.shared, "b", "startup")  # used to reset a's count
        self.assertEqual(stops(self.project, self.shared, "b", 5)[0], [])
        self.assertEqual(stops(self.project, self.shared, "a", 4)[0], [4])
        self.assertEqual(stops(self.project, self.shared, "b", 5)[0], [5])

    def test_bad_input_never_breaks(self):
        for stdin in ("", "not json", "[1, 2]", '{"session_id": 7}', '{"session_id": "../../x"}'):
            run("session-start", self.project, self.shared, stdin=stdin)
            run("stop", self.project, self.shared, stdin=stdin)
        turns = self.project / ".scribe" / "turns"
        self.assertTrue(all(f.parent == turns for f in turns.iterdir()))
        self.assertFalse((self.project.parent / "x.json").exists())

    def test_old_session_files_are_pruned(self):
        start(self.project, self.shared, "old", "startup")
        old = self.project / ".scribe" / "turns" / "old.json"
        then = time.time() - 15 * 86400
        os.utime(old, (then, then))
        start(self.project, self.shared, "new", "startup")
        self.assertFalse(old.exists())
        self.assertTrue((old.parent / "new.json").exists())

    def test_no_word_about_triggers(self):
        """Not even when the hits log still holds this session's warnings, written by 0.4."""
        with tempfile.TemporaryDirectory() as t:
            project, shared = Path(t) / "proj", Path(t) / "shared"
            project.mkdir()
            zsh_note(shared)
            now = time.time()
            write_log(shared / ".hits.jsonl", [{"t": iso(now), "kind": "start"}]
                      + [{"t": iso(now), "note": "zsh-is-the-mac-shell", "kind": "warn",
                          "session": "abcdefgh"}] * 2)
            run("session-start", project, shared)
            stop = '{"session_id": "abcdefgh-1"}'
            reason = [run("stop", project, shared, stdin=stop) for _ in range(10)][-1]["reason"]
            for word in ("trigger", "enforce", "block", "fired", "zsh-is-the-mac-shell"):
                self.assertNotIn(word, reason.lower())


class ScribeCli(Folders):
    def cli(self, *args):
        env = dict(os.environ, SCRIBE_SHARED_DIR=str(self.shared))
        env.pop("CLAUDE_PROJECT_DIR", None)
        return subprocess.run([sys.executable, str(ROOT / "scripts" / "scribe.py"), "--project",
                               str(self.project), *args], env=env, capture_output=True, text=True,
                              check=True).stdout

    def test_search_ranks_spelling_variants(self):
        note(self.shared, "zsh-is-the-mac-shell", "The Mac Bash tool runs zsh; echo ===== fails")
        note(self.knowledge, "test-server-login", "Der Prüf-Server ist nur hinter dem VPN erreichbar")
        note(self.knowledge, "unrelated", "nothing to see")
        nfd = "Prüf server"  # macOS hands out decomposed (NFD) text; notes are NFC
        out = self.cli("search", nfd, "test server", "staging")
        self.assertIn("1. test-server-login — project", out)
        self.assertIn(f"matched: {nfd}, test server", out)
        self.assertNotIn("unrelated", out)
        self.assertIn("1. zsh-is-the-mac-shell — shared", self.cli("search", "zsh", "shells", "SHELL"))
        self.assertIn("No note matches any of: kubernetes, k8s", self.cli("search", "kubernetes", "k8s"))

    def test_search_ignores_old_trigger_lines(self):
        zsh_note(self.shared)
        self.assertIn("No note matches any of: quote", self.cli("search", "quote"))  # only in `fix:`
        self.assertIn("No note matches any of: env", self.cli("search", "env"))  # only in `triggers:`
        self.assertIn("1. zsh-is-the-mac-shell — shared", self.cli("search", "zsh"))

    def test_search_follows_the_project_map(self):
        note(self.knowledge, "a-note", "alpha")
        note(self.knowledge, "b-note", "beta")
        (self.knowledge / "MAP.md").write_text("- before a release → `release` → b-note\n",
                                               encoding="utf-8")
        out = self.cli("search", "release")
        self.assertIn("1. b-note", out)
        self.assertNotIn("a-note", out)

    def test_search_reads_extra_record_folders(self):
        docs = self.project / "docs" / "decisions"
        note(docs, "why-postgres", "we chose postgres over mysql")
        self.assertIn("1. why-postgres — docs", self.cli("search", "--dir", "docs", "postgres"))

    def test_garden_report_and_done(self):
        now = time.time()
        today = iso(now)[:10]
        zsh_note(self.shared)
        note(self.shared, "zsh-mac-shell-traps", "zsh traps", updated="2026-01-01",
             extra=["triggers:", "  Bash: 'echo\\s+='"])
        note(self.knowledge, "stale-claim", "the export works", updated="2026-01-01",
             body="Fixed in v1.2.0 and still fine.")
        note(self.knowledge, "used-old", "old but read", updated="2026-01-01")
        note(self.knowledge, "fresh", "new note", updated=today)
        (self.knowledge / "MAP.md").write_text("- releases → `release` → fresh, gone-note\n",
                                               encoding="utf-8")
        write_log(self.shared / ".hits.jsonl", [{"t": iso(now - 400 * 86400), "kind": "start"},
                                                {"t": iso(now - 380 * 86400), "note": "x", "kind": "read"}]
                  + [{"t": iso(now - 3600), "note": "zsh-mac-shell-traps", "kind": "warn"}] * 4)
        write_log(self.project / ".scribe" / "hits.jsonl",
                  [{"t": iso(now - 90 * 86400), "kind": "start"},
                   {"t": iso(now - 86400), "note": "used-old", "kind": "read"}])
        out = self.cli("garden")
        self.assertIn("project 3 (`.scribe/knowledge`).\n", out)
        dup = out.split("## 1.")[1].split("## 2.")[0]
        self.assertIn("shared/zsh-is-the-mac-shell ↔ shared/zsh-mac-shell-traps: names share mac, shell, zsh",
                      dup)
        claims = out.split("## 2.")[1].split("## 3.")[0]
        self.assertIn("project/stale-claim (2026-01-01): Fixed in v1.2.0 and still fine.", claims)
        prune = out.split("## 3.")[1].split("## 4.")[0]
        self.assertIn("project/stale-claim (updated 2026-01-01)", prune)
        self.assertIn("shared/zsh-mac-shell-traps (updated 2026-01-01)", prune)  # a warning is no use
        self.assertNotIn("used-old", prune)
        self.assertNotIn("fresh", prune)
        mapped = out.split("## 4. Project map")[1]
        self.assertIn("names `gone-note`, which is not a note", mapped)
        self.assertIn("Not on the map: stale-claim, used-old", mapped)
        for word in ("trigger", "promote", "enforce", "block", "## 5."):
            self.assertNotIn(word, out.lower())
        self.assertFalse((self.project / ".scribe" / "triggers.json").exists())  # the report only reads

        self.assertIn("dropped 1 hit lines", self.cli("garden", "--done"))
        log = read_log(self.shared / ".hits.jsonl")
        self.assertEqual(log[0]["kind"], "start")
        self.assertEqual(len(log), 5)
        self.assertTrue((self.shared / ".garden_last").is_file())
        self.assertTrue((self.project / ".scribe" / "garden_last").is_file())

    def test_garden_status_words_in_another_language(self):
        note(self.knowledge, "export", "Export nach CSV", updated="2026-01-01", body="Ist seit 2.1 behoben.")
        self.assertIn("- none", self.cli("garden").split("## 2.")[1].split("## 3.")[0])
        claims = self.cli("garden", "--status-words", "behoben|funktioniert").split("## 2.")[1]
        self.assertIn("project/export (2026-01-01): Ist seit 2.1 behoben.", claims)

    def test_garden_waits_for_sixty_days_of_hits(self):
        note(self.knowledge, "old", "x", updated="2026-01-01")
        write_log(self.project / ".scribe" / "hits.jsonl", [{"t": iso(time.time() - 10 * 86400),
                                                             "kind": "start"}])
        self.assertIn("project: not judged yet; Reads are logged since", self.cli("garden"))


if __name__ == "__main__":
    unittest.main()
