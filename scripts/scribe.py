"""scribe command line, used by the /scribe-search and /scribe-garden skills.

  python3 scripts/scribe.py search [--top 3] [--dir DIR]... TERM [TERM...]
  python3 scripts/scribe.py garden [--days 60] [--promote 3] [--stale 30] [--status-words RE]
  python3 scripts/scribe.py garden --done

The project is --project, else CLAUDE_PROJECT_DIR, else the current directory;
shared notes are SCRIBE_SHARED_DIR, else ~/.claude/scribe/shared. Both commands
only read, except `garden --done`, which records the date of the run and drops
hit lines older than a year.
"""
import argparse
import json
import os
import re
import sys
import unicodedata

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, "hooks"))
import _scribe_core as core  # noqa: E402

STATUS = (r"\b(fixed|works?|working|broken|not yet|no longer|still|deprecated|TODO|currently|"
          r"as of|latest|v\d+\.\d+(?:\.\d+)?|\d+\.\d+\.\d+)\b")
STOP = {"the", "and", "for", "with", "that", "this", "when", "from", "not", "are", "its", "into",
        "only", "then", "than", "you", "your", "one", "all", "but", "use", "via", "out", "has"}


def squash(text):
    """Lower case, NFC, without spaces, hyphens or underscores: 'Test-Server',
    'test server' and 'testserver' all become 'testserver'."""
    return re.sub(r"[\s\-_]+", "", unicodedata.normalize("NFC", text).lower())


def load(dirs, extra=()):
    """Every note as a dict: scope, stem, path, name, desc, updated, triggers, fix, lines."""
    paths = [("shared", os.path.join(dirs.shared, n)) for n in core.note_files(dirs.shared)]
    paths += [("project", os.path.join(dirs.knowledge, n)) for n in core.note_files(dirs.knowledge)]
    for folder in extra:
        for root, subdirs, files in os.walk(folder):
            subdirs[:] = sorted(s for s in subdirs if not s.startswith("."))
            paths += [(dirs.label(folder), os.path.join(root, f))
                      for f in sorted(files) if f.endswith(".md") and f.upper() not in core.SKIP]
    notes, seen = [], set()
    for scope, path in paths:
        real = os.path.realpath(path)
        if real in seen:
            continue
        seen.add(real)
        try:
            meta, body = core.read_note(path)
        except (OSError, UnicodeDecodeError):
            continue
        stem = os.path.splitext(os.path.basename(path))[0]
        triggers = core.parse_triggers(meta.get("triggers"))
        notes.append({
            "scope": scope, "stem": stem, "path": path,
            "name": str(meta.get("name") or stem),
            "desc": " ".join(str(meta.get("description") or meta.get("title") or "").split()),
            "updated": str(meta.get("updated") or meta.get("date") or ""),
            "enforce": core.enforce_of(meta),
            "triggers": triggers,
            "extra": " ".join([str(meta.get("fix") or "")] + [k + " " + p for k, p in triggers]),
            "lines": body,
        })
    return notes


# ---------------------------------------------------------------- search

def usable(term):
    s = squash(term)
    return len(s) >= 2 or (len(s) == 1 and not s.isascii())


def score(note, terms, map_hits):
    """(score, matched terms). Name 6, description 3, triggers/fix 2, body lines
    1 each (at most 5) per term; +4 for each further term matched; +5 per map
    line that names the note and matches a term."""
    name, desc = squash(note["name"] + " " + note["stem"]), squash(note["desc"])
    extra, body = squash(note["extra"]), [squash(line) for line in note["lines"]]
    total, matched = 0, []
    for term in terms:
        t = squash(term)
        s = 6 * (t in name) + 3 * (t in desc) + 2 * (t in extra) + min(5, sum(t in b for b in body))
        if s:
            total += s
            matched.append(term)
    if matched:
        total += 4 * (len(matched) - 1)
    total += 5 * map_hits.get(note["stem"], 0)
    return total, matched


def map_hits(dirs, notes, terms):
    """{stem: number of map lines that match a term and name the note}."""
    found = core.read_map(dirs.project)
    if not found:
        return {}
    out = {}
    for line in found[1].splitlines():
        s = squash(line)
        if not any(squash(t) in s for t in terms):
            continue
        for note in notes:
            if note["stem"] in line:
                out[note["stem"]] = out.get(note["stem"], 0) + 1
    return out


def search(dirs, terms, top, extra):
    terms = [t for t in dict.fromkeys(terms) if usable(t)]
    if not terms:
        return "Give at least one search word (two letters or more, or one letter of a non-Latin script)."
    notes = load(dirs, extra)
    hits = map_hits(dirs, notes, terms)
    ranked = sorted(((score(n, terms, hits), n) for n in notes), key=lambda x: -x[0][0])
    ranked = [(s, m, n) for (s, m), n in ranked if s > 0]
    if not ranked:
        return (f"No note matches any of: {', '.join(terms)}. Try more variants (the user's language "
                "and English, a shorter stem, an abbreviation), then grep the project's record folders.")
    out = [f"Top {min(top, len(ranked))} of {len(ranked)} matching notes "
           f"(searched {len(notes)}; terms: {', '.join(terms)}):"]
    for i, (s, matched, n) in enumerate(ranked[:top], 1):
        out.append(f"{i}. {n['name']} — {n['scope']}, updated {n['updated'] or '?'}, score {s}, "
                   f"matched: {', '.join(matched)}")
        out.append(f"   {n['path']}")
        if n["desc"]:
            out.append(f"   {n['desc'][:300]}")
    rest = ranked[top:top + 7]
    if rest:
        out.append("Also matching: " + ", ".join(f"{n['name']} ({s})" for s, _, n in rest))
    out.append("Status claims (\"fixed\", \"works\", a version) date from each note's `updated:`; "
               "check them against the code before acting on them.")
    return "\n".join(out)


# ---------------------------------------------------------------- garden

def words(text):
    """Words worth comparing: Latin ones of 3+ letters (not stop words), and words
    of 2+ letters in other scripts, where words are shorter."""
    return {w for w in re.findall(r"[^\W_]+", unicodedata.normalize("NFC", text).lower())
            if (len(w) >= 3 and w not in STOP) or (len(w) >= 2 and not w.isascii())}


def jaccard(a, b):
    return len(a & b) / len(a | b) if a and b else 0.0


def duplicates(notes):
    pairs = []
    for i, a in enumerate(notes):
        for b in notes[i + 1:]:
            why = []
            same = {p for _, p in a["triggers"]} & {p for _, p in b["triggers"]}
            if same:
                why.append(f"same trigger `{sorted(same)[0]}`")
            na, nb = words(a["stem"].replace("-", " ").replace("_", " ")), \
                words(b["stem"].replace("-", " ").replace("_", " "))
            if len(na & nb) >= 2 and jaccard(na, nb) >= 0.5:
                why.append(f"names share {', '.join(sorted(na & nb))}")
            da, db = words(a["desc"]), words(b["desc"])
            if len(da & db) >= 4 and jaccard(da, db) >= 0.3:
                why.append(f"descriptions overlap {jaccard(da, db):.0%}")
            if why:
                pairs.append((len(why), a, b, why))
    pairs.sort(key=lambda p: -p[0])
    return pairs


def map_report(dirs, notes):
    project = [n for n in notes if n["scope"] == "project"]
    found = core.read_map(dirs.project)
    if not found:
        return [f"- No project map. {len(project)} project notes; draft `.scribe/knowledge/MAP.md` "
                "from the scribe-review template."] if project else []
    rel, text = found
    stems = {n["stem"] for n in notes} | {n["name"] for n in notes}
    out, named = [], set()
    for line in text.splitlines():
        if "→" not in line:
            continue
        tail = line.rsplit("→", 1)[1]  # situation → search words → note
        named |= {n["stem"] for n in notes if n["stem"] in tail or n["name"] in tail}
        for ref in re.findall(r"[A-Za-z0-9][\w.]*[-_][\w.\-]*", tail):
            if ref not in stems:
                out.append(f"- `{rel}` names `{ref}`, which is not a note.")
    missing = [n["stem"] for n in project if n["stem"] not in named]
    if missing:
        out.append(f"- Not on the map: {', '.join(missing[:20])}" + (" …" if len(missing) > 20 else ""))
    return out


def garden(dirs, days, promote, stale, status_words=""):
    notes = load(dirs)
    status = re.compile(STATUS + (f"|{status_words}" if status_words else ""), re.I)
    by_scope = {s: core.read_hits(dirs, s) for s in ("shared", "project")}
    fired = {s: core.count(e, days=days) for s, e in by_scope.items()}
    used = {s: core.count(e, kinds=core.FIRED + ("read",), days=days) for s, e in by_scope.items()}
    started = {s: next((e.get("t") for e in by_scope[s] if e.get("t")), None) for s in by_scope}
    stale_before = core.now_iso(stale * 86400)[:10]
    old_before = core.now_iso(days * 86400)[:10]
    out = [f"# scribe garden — {core.now_iso()[:10]}",
           f"Notes: shared {sum(n['scope'] == 'shared' for n in notes)} (`{dirs.label(dirs.shared)}`), "
           f"project {sum(n['scope'] == 'project' for n in notes)} (`.scribe/knowledge`); "
           f"with triggers {sum(bool(n['triggers']) for n in notes)}."]

    out.append("\n## 1. Possible duplicates (merge?)")
    pairs = duplicates(notes)
    out += [f"- {a['scope']}/{a['stem']} ↔ {b['scope']}/{b['stem']}: {'; '.join(why)}"
            for _, a, b, why in pairs[:15]] or ["- none found"]

    out.append(f"\n## 2. Status claims to re-check (notes not updated since {stale_before})")
    claims = []
    for n in notes:
        if n["updated"] and n["updated"] >= stale_before:
            continue
        lines = [line.strip() for line in [n["desc"]] + n["lines"] if status.search(line)]
        for line in lines[:3]:
            claims.append(f"- {n['scope']}/{n['stem']} ({n['updated'] or 'no date'}): "
                          f"{line[:140]}{'…' if len(line) > 140 else ''}")
    out += claims[:40] or ["- none"]
    if len(claims) > 40:
        out.append(f"- … {len(claims) - 40} more lines")

    out.append(f"\n## 3. Prune candidates (no trigger hit and not opened in {days} days)")
    for scope in ("shared", "project"):
        since = core.days_since(started[scope]) if started[scope] else None
        if since is None or since < days:
            ready = core.now_iso(-(days - (since or 0)) * 86400)[:10]
            out.append(f"- {scope}: not judged yet; hits are logged since "
                       f"{(started[scope] or core.now_iso())[:10]}, enough from {ready}.")
            continue
        cands = [n for n in notes if n["scope"] == scope and not used[scope].get(n["stem"])
                 and (not n["updated"] or n["updated"] < old_before)]
        out += [f"- {scope}/{n['stem']} (updated {n['updated'] or '?'})"
                + (" — its trigger never fired" if n["triggers"] else "") for n in cands] \
            or [f"- {scope}: none"]

    out.append(f"\n## 4. Promote candidates (trigger fired {promote}+ times in {days} days)")
    proms = []
    for n in notes:
        hits = fired.get(n["scope"], {}).get(n["stem"], 0)
        if hits >= promote:
            step = ("a repo test that fails on the pattern, or a CLAUDE.md line"
                    if n["enforce"] == "block" else "`enforce: block` with a `fix:` line")
            proms.append(f"- {n['scope']}/{n['stem']}: {hits} hits ({n['enforce'] or 'warn'}) → {step}")
    out += proms or ["- none"]

    out.append("\n## 5. Trigger problems")
    out += [f"- {scope}/{stem} `{key}`: {why}" for scope, stem, key, why in
            core.build_triggers(dirs)[1]] or ["- none"]

    out.append("\n## 6. Project map")
    out += map_report(dirs, notes) or ["- fine"]
    return "\n".join(out)


def _keep(line, first, cut):
    """Keep the log's `start` line and every event from the last year."""
    try:
        e = json.loads(line)
    except ValueError:
        return False
    return isinstance(e, dict) and ((first and e.get("kind") == "start") or str(e.get("t")) >= cut)


def garden_done(dirs):
    cut = core.now_iso(365 * 86400)
    dropped = 0
    for scope in ("shared", "project"):
        folder = dirs.shared if scope == "shared" else dirs.scribe
        if not os.path.isdir(folder):
            continue
        with open(dirs.garden_stamp(scope), "w", encoding="utf-8") as f:
            f.write(core.now_iso() + "\n")
        path = dirs.hits_file(scope)
        try:
            with open(path, encoding="utf-8") as f:
                lines = f.readlines()
        except OSError:
            continue
        keep = [line for i, line in enumerate(lines) if _keep(line, i == 0, cut)]
        if len(keep) < len(lines):
            dropped += len(lines) - len(keep)
            with open(path, "w", encoding="utf-8") as f:
                f.writelines(keep)
    return f"Recorded the garden run ({core.now_iso()[:10]}); dropped {dropped} hit lines older than a year."


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser(prog="scribe.py", description=__doc__.split("\n\n")[0])
    ap.add_argument("--project", default="")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("search", help="rank notes by spelling variants of a topic")
    s.add_argument("terms", nargs="+")
    s.add_argument("--top", type=int, default=3)
    s.add_argument("--dir", action="append", default=[], help="another record folder (recursive)")
    g = sub.add_parser("garden", help="monthly report: duplicates, status claims, prune, promote")
    g.add_argument("--days", type=int, default=60)
    g.add_argument("--promote", type=int, default=3)
    g.add_argument("--stale", type=int, default=30)
    g.add_argument("--status-words", default="",
                   help="regex of more status words, e.g. in the language the notes are written in")
    g.add_argument("--done", action="store_true", help="record the run and trim old hit lines")
    args = ap.parse_args(argv)
    dirs = core.Dirs(project=args.project or None)
    if args.cmd == "search":
        print(search(dirs, args.terms, args.top, [os.path.join(dirs.project, d) for d in args.dir]))
    elif args.done:
        print(garden_done(dirs))
    else:
        print(garden(dirs, args.days, args.promote, args.stale, args.status_words))


if __name__ == "__main__":
    main()
