#!/usr/bin/env python3
"""Fixture tests for clean_gdoc_md.py. Standard library only.

  python tests/run_fixtures.py                     run every fixture against the repo's script
  python tests/run_fixtures.py --script OLD.py     run them against another copy (an older release)
  python tests/run_fixtures.py --regression EXPORT.md [CLEAN.md]
                                                   also run a real export (never committed) through
                                                   strip and check, and check a finished clean file

Exit 1 if any fixture fails. The fixture list was frozen at v0.1.4 (plan step A1); fixtures for
features not built yet are listed as pending, with the step that makes them live.
"""
import argparse, collections, importlib.util, json, os, re, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLUGIN = os.path.join(ROOT, "plugins", "legit-pdf2md")
SCRIPT = os.path.join(PLUGIN, "skills", "legit-pdf2md", "scripts", "clean_gdoc_md.py")
DOC, PDF = "application/vnd.google-apps.document", "application/pdf"
FIXTURES = []
PENDING = {   # name: (plan step that makes it live, what it will prove)
    "table_reorder": ("C2", "a correct table rebuild passes; prices moved to the wrong plan are rejected"),
}


def fixture(fn):
    FIXTURES.append(fn)
    return fn


def defs(*ids):
    return "".join(f"\n[image{i}]: <data:image/png;base64,AAAA>" for i in ids)


def lines(text):
    return [l for l in text.split("\n") if l.strip()]


# ---------------------------------------------------------------- A3: images in the stripped text

@fixture
def paired_images_in_code_span(m):
    src = "Intro\n\n`![][image6]![][image7]`\n\nOutro\n" + defs(6, 7)
    out, st = m.strip(src)
    assert lines(out) == ["Intro", "[image 6]", "[image 7]", "Outro"], out
    r = m.check(src, out)
    assert r["ok"] and not r["dropped_lines"] and not r["inline_drops"], r


@fixture
def bold_image(m):
    out = m.strip("**![][image1]**Title text\n" + defs(1))[0]
    assert lines(out) == ["[image 1]", "Title text"], out


@fixture
def three_adjacent_images(m):
    out = m.strip("![][image1]![][image2]![][image3]Caption\n" + defs(1, 2, 3))[0]
    assert lines(out) == ["[image 1]", "[image 2]", "[image 3]", "Caption"], out


@fixture
def image_ref_and_text_in_code_is_reported(m):
    src = "Label `![][image3] CONTENT` here\n" + defs(3)
    out, st = m.strip(src)
    assert st["images_kept_in_code"] == ["3"], st
    r = m.check(src, out)
    assert r["ok"] and r["images"]["kept_in_code"] == ["3"], r["images"]


@fixture
def images_in_list_heading_quote_table_stay_inline(m):
    src = ("- ![][image1] Step one\n\n# ![][image2] Title\n\n> ![][image3] Quoted\n\n| ![][image4] | cell |\n\n"
           "1. ![][image5] First\n" + defs(1, 2, 3, 4, 5))
    assert lines(m.strip(src)[0]) == ["- [image 1] Step one", "# [image 2] Title", "> [image 3] Quoted",
                                      "| [image 4] | cell |", "1. [image 5] First"]
    out = m.strip("1. Step one\n\n   ![][image1]Caption\n\n2. Step two\n" + defs(1))[0]
    assert lines(out) == ["1. Step one", "   [image 1]", "   Caption", "2. Step two"], "a list continuation keeps its indent"


@fixture
def split_never_creates_block_syntax(m):
    for tail in ("- not a list", "# not a heading", "1. not a list", "> not a quote", "---", "```"):
        out = m.strip("![][image1]" + tail + "\n" + defs(1))[0]
        assert lines(out) == ["[image 1] " + tail], (tail, out)


@fixture
def gmc008_link_named_like_image(m):
    link = "[Manual][image1]\n\n[image1]: https://example.com/manual"
    assert m.strip(link)[0].strip() == link
    r = m.check(link, link)
    assert r["ok"] and r["images"]["source"] == [], r["images"]
    code = "See `![][image1]` here\n\n[image1]: https://example.com/manual"
    assert m.strip(code)[0].strip() == code, "code around an image-style link is real code"


@fixture
def inline_data_image_in_code_is_kept(m):
    src = "Code `![](data:image/png;base64,AAAA)` here"
    out = m.strip(src)[0]
    assert out.strip() == src
    r = m.check(src, out)
    assert r["ok"] and r["images"]["kept_in_code"] == [], "the picture data is still there, nothing to report"


# ---------------------------------------------------------------- A4: check v2 (image gate, positioned drops)

IMGS = "Intro\n\n![][image1]First part\n\n![][image2]![][image3]\n\nEnd\n" + defs(1, 2, 3)


@fixture
def image_gate_passes_stripped_text(m):
    out = m.strip(IMGS)[0]
    r = m.check(IMGS, out)
    assert r["ok"] and r["images"]["source"] == ["1", "2", "3"] and r["images"]["cleaned"] == ["1", "2", "3"], r


@fixture
def dropped_placeholder_fails(m):
    out = m.strip(IMGS)[0].replace("[image 2]\n", "")
    r = m.check(IMGS, out)
    assert not r["ok"] and r["images"]["missing"] == ["2"], r["images"]


@fixture
def invented_placeholder_fails(m):
    out = m.strip(IMGS)[0] + "\n[image 9]\n"
    r = m.check(IMGS, out)
    assert not r["ok"] and r["images"]["invented"] == ["9"], r["images"]


@fixture
def reordered_placeholders_fail(m):
    out = m.strip(IMGS)[0].replace("[image 2]\n[image 3]", "[image 3]\n[image 2]")
    r = m.check(IMGS, out)
    assert not r["ok"] and not r["images"]["in_order"], r["images"]


@fixture
def image_repeated_by_source_is_allowed(m):
    src = "![][image1]A\n\n![][image1]B\n" + defs(1)
    r = m.check(src, m.strip(src)[0])
    assert r["ok"] and r["images"]["source"] == ["1", "1"], r["images"]


@fixture
def drops_carry_positions_and_full_text(m):
    furniture = "You're here: part two of the guide, page seven, @joeoliveimpact, engineforimpact dot com"
    src = "Real line one.\n\n" + furniture + "\n\nReal line two.\n"
    r = m.check(src, "Real line one.\n\nReal line two.\n")
    assert r["ok"] and len(r["drop_spans"]) == 1, r
    d = r["drop_spans"][0]
    assert d["kind"] == "line" and src[d["chars"][0]:d["chars"][1]] == furniture, d
    assert len(d["text"]) > 80 and d["letters"][1] - d["letters"][0] == len(re.sub(r"\W", "", furniture)), d


@fixture
def flow_0_1_3_still_works(m):
    """The 0.1.3 SKILL.md flow: strip -o, then check exits 0 on the rebuild and 1 on an invented word;
    every key 0.1.3 printed is still there."""
    src = "T O S T A R T\n\nIntro text here.\n\n![][image1]Fathom\n" + defs(1)
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    with tempfile.TemporaryDirectory() as d:
        e, c, bad = (os.path.join(d, n) for n in ("export.md", "clean.md", "bad.md"))
        open(e, "w", encoding="utf-8").write(src)
        run = lambda *a: subprocess.run([sys.executable, m.__file__, *a], env=env, capture_output=True, text=True,
                                        encoding="utf-8", timeout=60)
        p = run("strip", e, "-o", c)
        out = json.loads(p.stdout)
        assert p.returncode == 0 and {"stats", "worklist"} <= set(out), p.stdout
        assert {"chars_in", "chars_out", "est_tokens_in", "est_tokens_out", "image_definitions", "image_refs",
                "code_spans_unwrapped", "inline_images"} <= set(out["stats"]), out["stats"]
        rebuilt = open(c, encoding="utf-8").read().replace("T O S T A R T", "## To start")
        open(c, "w", encoding="utf-8").write(rebuilt)
        open(bad, "w", encoding="utf-8").write(rebuilt.replace("Intro text", "Intro new text"))
        p = run("check", e, c)
        keys = {"source_letters", "cleaned_letters", "added_runs", "partial_word_drops", "merged_words",
                "moved_runs", "split_words", "inline_drops", "dropped_lines", "ok"}
        assert p.returncode == 0 and keys <= set(json.loads(p.stdout)), p.stdout
        assert run("check", e, bad).returncode == 1


# ---------------------------------------------------------------- A5: naming

@fixture
def clean_file_names(m):
    assert m.clean_name("Notes 09.11.26", DOC) == "Notes 09.11.26 - clean.md"
    assert m.clean_name("Field Guide - Getting Started - 09.11.26.pdf", PDF) == "Field Guide - Getting Started - 09.11.26 - clean.md"
    assert m.clean_name("Report.PDF", PDF) == "Report - clean.md"
    assert m.clean_name("Draft.pdf", DOC) == "Draft.pdf - clean.md", "only a PDF loses .pdf"
    assert m.clean_name("Guide.md", "text/markdown") == "Guide - clean.md", "a local Markdown file loses .md"
    assert m.clean_name("Notes.md", DOC) == "Notes.md - clean.md", "only a Markdown file loses .md"


# ---------------------------------------------------------------- B: analyze, autofix, apply-edits, pipeline

NAV = "`You're here: {} • Next: {}` → `• @coachhandle`"
GUIDE = "\n\n".join([
    "Coach Name", "@ C O A C H H A N D L E",
    "P A R T 1 · S T A R T H E R E @ C O A C H H A N D L E",
    "What we use it for: every call recorded, then turned into tasks.",
    "Make a free account. It takes a minute. 1", "Connect it to your calendar. 2", "Run your first call.", "3",
    NAV.format("the map", "step one"),
    "P A R T 2 · S T E P O N E @ C O A C H H A N D L E",
    "What we use it for: talking instead of typing all day long.",
    "**S t e p 1** Write down every app",
    "`Here is every app I use: [LIST].`", "`For each one, tell me what to connect first.`",
    "Paste the answer out, then paste it", "somewhere else. It stays simple.",
    NAV.format("step one", "step two"),
    "P A R T 3 · T H E T O O L S @ C O A C H H A N D L E",
    "What we use it for: booking calls without the back and forth.",
    "A real line that stays in the guide.",
    NAV.format("step two", "the end"),
    "The end of the guide.",
]) + "\n"


def run_pipeline(m, export, edits=None, final=False, state=None):
    with tempfile.TemporaryDirectory() as d:
        p = state or os.path.join(d, "state.json")
        r = m.pipeline(export, p, final=False)
        errors = None
        if edits is not None:
            st = m._load_state(p)
            errors = m._apply(st, edits(st, r), st["issues"])
            if not errors:
                m._save_state(p, st)
        if final:
            r = m.pipeline(export, p, final=True)
        return r, errors, m._load_state(p)


@fixture
def analyze_flags_nav_and_handle_not_repeated_openings(m):
    issues = m.analyze(m.strip(GUIDE)[0])
    kinds = collections.Counter(x["type"] for x in issues)
    assert kinds["page_nav"] == 3 and kinds["repeated_handle"] == 3, kinds
    whatwe = [x for x in issues if "What we use it for" in x["text"]]
    assert not whatwe, ("a repeated opening alone is not furniture", whatwe)


@fixture
def autofix_passes_check_with_reconciled_ledger(m):
    r, _, st = run_pipeline(m, GUIDE, final=True)
    assert r["status"] == "validated", r
    assert len(st["ledger"]) == 6 and "@ C O A C H H A N D L E" in st["text"].split("\n")[2], st["text"][:200]
    for gone in ("You're here", "S T A R T H E R E @"):
        assert gone not in st["text"], gone
    for made in ("**Step 1**", "```\nHere is every app", "paste it somewhere else."):
        assert made in st["text"], made


def _apply_suggested_lists(st, r):
    """Confirm every suggested list as-is, the way a host AI that agrees with it would."""
    return [{"issue": x["id"], "op": "number_list", "lines": s["lines"], "text": s["text"]}
            for x in r["issues"] for s in x.get("suggested_list", ())]


@fixture
def detached_number_lists_go_to_the_ai(m):
    """Autofix never rebuilds a numbered list (Joe 09.23.26): the AI gets the block with the suggested list and
    the number_list op, and confirming the suggestion validates. The checker's known-limit shapes stay as they
    are after autofix, for the AI to judge."""
    r, _, st = run_pipeline(m, GUIDE)
    assert r["status"] == "needs_host_edits" and "Make a free account. It takes a minute. 1" in st["text"], r["status"]
    L = st["text"].split("\n")   # every packet line carries its real line number: "12| text"
    for x in r["issues"]:
        for row in x["text"].split("\n"):
            n, _, line = row.partition("| ")
            assert L[int(n) - 1] == line and x["lines"][0] <= int(n) <= x["lines"][1], (row, x["lines"])
        rows = [int(r.partition("| ")[0]) for r in x["text"].split("\n")]   # blank lines shown too: no gaps
        assert rows == list(range(x["lines"][0], x["lines"][1] + 1)), (rows, x["lines"])
        for side in ("before", "after"):   # the whole neighbouring line, with its number: an edit may cover it
            if x[side]:
                n, _, line = x[side].partition("| ")
                assert L[int(n) - 1] == line and line.strip() and not x["lines"][0] <= int(n) <= x["lines"][1], (side, x)
    blk = [x for x in r["issues"] if "suggested_list" in x]
    assert len(blk) == 1 and "number_list" in r["ops_by_type"]["number_list"], blk
    assert blk[0]["suggested_list"][0]["text"].startswith("1. Make a free account. It takes a minute.\n2. Connect"), blk
    r, errors, st = run_pipeline(m, GUIDE, _apply_suggested_lists, final=True)
    assert errors == [] and r["status"] == "validated" and "3. Run your first call." in st["text"], (errors, r)
    for exp in ("Intro line.\n\nfinal score: 1\n\nnext game: 2\n\nlast one: 3\n\nEnd.\n",
                "Intro line.\n\n1\n\nFirst item here.\n\n2\n\nSecond item here.\n\nEnd.\n",
                "First item here. 1\n\nSecond item here. 1\n\nThird item here. 2\n\nEnd.\n"):
        r, _, st = run_pipeline(m, exp)
        assert not re.search(r"^\d+\. ", st["text"], re.M), st["text"]
    # two lists merged into one block keep both suggestions, each with its own lines (checker 09.23.26)
    r, _, _ = run_pipeline(m, exp)
    assert [s["lines"] for x in r["issues"] for s in x.get("suggested_list", ())] == [[1, 1], [3, 5]], r["issues"]


@fixture
def real_line_next_to_furniture(m):
    """A real sentence deleted beside logged page furniture must not hide inside the furniture's deletion."""
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "s.json")
        m.pipeline(GUIDE, p)
        st = m._load_state(p)
        st["text"] = st["text"].replace("A real line that stays in the guide.\n", "")   # bypasses _edit: unlogged
        m._save_state(p, st)
        r = m.pipeline(GUIDE, p, final=True)
    assert r["status"] == "needs_review" and any("real line" in t for t in r["unexplained_drops"]), r


@fixture
def furniture_word_deleted_elsewhere(m):
    """Deleting a word that also appears in logged furniture ("here") is still unexplained: position, not text."""
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "s.json")
        m.pipeline(GUIDE, p)
        st = m._load_state(p)
        assert "START HERE" not in st["text"]
        st["text"] = st["text"].replace("The end of the guide.", "The end of guide.")
        m._save_state(p, st)
        r = m.pipeline(GUIDE, p, final=True)
    assert r["status"] == "needs_review" and r["unexplained_drops"] == ["the"], r


def _issue_for(st, needle):
    L = st["text"].split("\n")
    ln = next(i + 1 for i, l in enumerate(L) if needle in l)
    return ln, next(x["id"] for x in st["issues"] if x["lines"][0] <= ln <= x["lines"][1])


@fixture
def apply_edits_valid_heading_then_validated(m):
    def edits(st, r):
        ln, i = _issue_for(st, "P A R T 2")
        return [{"issue": i, "op": "replace", "lines": [ln, ln], "text": "## Part 2 · Step one"}]
    r, errors, st = run_pipeline(m, GUIDE, edits, final=True)
    assert errors == [] and r["status"] == "validated" and "## Part 2 · Step one" in st["text"], (errors, r)


@fixture
def apply_edits_rejects_added_word_and_out_of_range(m):
    def added(st, r):
        ln, i = _issue_for(st, "P A R T 2")
        return [{"issue": i, "op": "replace", "lines": [ln, ln], "text": "## Part 2 · Step one, the fun part"}]
    _, errors, st = run_pipeline(m, GUIDE, added)
    assert errors and "changes the wording" in errors[0] and "fun part" not in st["text"], errors

    def outside(st, r):
        _, i = _issue_for(st, "P A R T 2")
        ln = next(n + 1 for n, l in enumerate(st["text"].split("\n")) if l.startswith("The end"))
        return [{"issue": i, "op": "replace", "lines": [ln, ln], "text": "The end of the guide."}]
    _, errors, _ = run_pipeline(m, GUIDE, outside)
    assert errors and "outside its issues' lines" in errors[0], errors

    def unlogged_delete(st, r):
        ln, i = _issue_for(st, "P A R T 2")
        return [{"issue": i, "op": "delete", "lines": [ln, ln]}]
    _, errors, _ = run_pipeline(m, GUIDE, unlogged_delete)
    assert errors and "needs a reason" in errors[0], errors


@fixture
def edit_scope_and_batch_guards(m):
    """Deletions stay on flagged lines; an edit naming two blocks cannot take the real text between them;
    overlapping edits and a batch with one bad edit change nothing; a second apply-edits run through the CLI
    is checked against fresh line numbers."""
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "s.json")
        r0 = m.pipeline(GUIDE, p)
        st = m._load_state(p)
        L = st["text"].split("\n")
        find = lambda s: next(i + 1 for i, l in enumerate(L) if s in l)
        blk = lambda ln: next(x for x in st["issues"] if x["lines"][0] <= ln <= x["lines"][1])
        p1, p2 = find("P A R T 1"), find("P A R T 2")
        b1, b2 = blk(p1)["id"], blk(p2)["id"]
        real = find("What we use it for: every call")
        before = json.dumps(st, sort_keys=True)
        tries = {
            "span": [{"issues": [b1, b2], "op": "delete", "lines": [p1, p2], "reason": "x"}],
            "context delete": [{"issue": b1, "op": "delete", "lines": [real, real], "reason": "x"}],
            "overlap": [{"issue": b1, "op": "replace", "lines": [p1, p1], "text": L[p1 - 1]},
                        {"issue": b1, "op": "delete", "lines": [p1, p1], "reason": "x"}],
            "one bad": [{"issue": b1, "op": "replace", "lines": [p1, p1], "text": "## Part 1 · Start here"},
                        {"issue": b2, "op": "replace", "lines": [p2, p2], "text": "## Part 2 · Step one more"}],
        }
        for name, edits in tries.items():
            errors = m._apply(st, edits, st["issues"])
            assert errors and json.dumps(st, sort_keys=True) == before, (name, errors)
        env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
        cli = lambda f: subprocess.run([sys.executable, m.__file__, "apply-edits", f, "--state", p], env=env,
                                       capture_output=True, text=True, encoding="utf-8", timeout=120)
        first = os.path.join(d, "e1.json")
        json.dump({"rev": r0["rev"], "edits": [{"issue": b1, "op": "replace", "lines": [p1, p1], "text": "## Part 1\n\nStart here"}]},
                  open(first, "w", encoding="utf-8"))
        assert cli(first).returncode == 0
        stale = os.path.join(d, "e2.json")   # written from the first packet: refused, whatever its numbers hit now
        json.dump({"rev": r0["rev"], "edits": [{"issue": b2, "op": "delete", "lines": [p2, p2], "reason": "x"}]},
                  open(stale, "w", encoding="utf-8"))
        r = cli(stale)
        assert r.returncode == 1 and "stale" in r.stdout and "P A R T 2" in m._load_state(p)["text"], r.stdout
    # a real line between two flagged lines of one block is not flagged, so it cannot be deleted
    exp = "Intro text here.\n\n- W H Y\n- This real sentence matters a lot.\n- H O W\n\nEnd text.\n"
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "s.json")
        m.pipeline(exp, p)
        st = m._load_state(p)
        b = next(x for x in st["issues"] if x["lines"][0] <= 4 <= x["lines"][1])
        errors = m._apply(st, [{"issue": b["id"], "op": "delete", "lines": [4, 4], "reason": "x"}], st["issues"])
        assert errors and "real sentence" in st["text"], errors


@fixture
def reconcile_edge_cases(m):
    """Strip removing an entity's letters inside code font is logged, not a crash; a letter entity there fails
    cleanly; a damaged state restarts; a logged drop holding a backtick cannot hide a merge; a logged line
    inside multi-line inline code cannot hide an unlogged deletion after it."""
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "s.json")
        assert m.pipeline("`W H Y T H I S&amp;nbsp;`\n\nSome text here.\n", p, final=True)["status"] == "validated"
        r = m.pipeline("`C A F &Eacute;`\n\nSome text here.\n", os.path.join(d, "t.json"), final=True)
        assert r["status"] == "failed" and "error" in r, r
        for junk in ("{half", "[]", '{"stage": "stripped"}'):
            open(p, "w", encoding="utf-8").write(junk)
            assert m.pipeline(GUIDE, p, final=True)["status"] == "validated", junk
        # apply-edits on a damaged state or a malformed batch: a clean refusal, never a traceback
        good = m._load_state(p)
        env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
        e = os.path.join(d, "e.json")
        for field, bad in (("text", 5), ("nav_openings", [5]), ("audit", None)):
            m._save_state(p, {**good, field: bad})
            json.dump({"rev": "x", "edits": []}, open(e, "w", encoding="utf-8"))
            r = subprocess.run([sys.executable, m.__file__, "apply-edits", e, "--state", p], env=env,
                               capture_output=True, text=True, encoding="utf-8", timeout=120)
            assert r.returncode == 1 and "Traceback" not in r.stderr and "damaged" in r.stdout, (field, r.stderr[-300:])
        m._save_state(p, good)
        json.dump({"rev": m._sha(good["text"])[:12], "edits": 5}, open(e, "w", encoding="utf-8"))
        r = subprocess.run([sys.executable, m.__file__, "apply-edits", e, "--state", p], env=env,
                           capture_output=True, text=True, encoding="utf-8", timeout=120)
        assert r.returncode == 1 and "Traceback" not in r.stderr and "list of objects" in r.stdout, r.stderr[-300:]
    exp = "`KEEP` x `big**word** here` end of line.\n"
    st = m._new_state(exp)
    line = st["text"].split("\n")[0]
    assert not m._apply(st, [{"op": "replace", "lines": [1, 1], "reason": "x", "drops": ["KEEP` x "],
                              "text": "`" + line.replace("`KEEP` x ", "").replace("big**word**", "bigword")}])
    assert not m.reconcile(st, exp)[0]["ok"], "the merge is still seen"
    exp = ("Intro text.\n\nSay `alpha\nCONFIDENTIAL DRAFT\nBeta` then ok `code with ![Revenue doubled][image1] "
           "inside` end.\n\nOutro text.\n\n[image1]: <data:image/png;base64,AAAA>\n")
    st = m._new_state(exp)
    L = st["text"].split("\n")
    n = L.index("CONFIDENTIAL DRAFT") + 1
    assert not m._apply(st, [{"op": "delete", "lines": [n, n], "reason": "x"}])
    st["text"] = st["text"].replace(" ![Revenue doubled][image1]", "")   # an unlogged deletion
    r, unexplained = m.reconcile(st, exp)
    assert not r["ok"] or unexplained, (r["ok"], unexplained)
    # a logged word between single letters must not turn them into one letter-spaced run that hides a merge
    for exp, drop, text in (("Grades A B and C are fine.\n", "and ", "Grades A BC are fine."),
                            ("Plans 1 2 and 3 today.\n", "and ", "Plans 1 23 today."),
                            ("Grades A B x C are fine.\n", "x ", "Grades A BC are fine."),
                            ("A BC DE FG HI JK 1 2 3 today.\n", "JK ", "A BC DE FG HI 1 23 today.")):
        st = m._new_state(exp)
        assert not m._apply(st, [{"op": "replace", "lines": [1, 1], "drops": [drop], "reason": "x", "text": text}])
        assert not m.reconcile(st, exp)[0]["ok"], text
    # number lists move only stand-alone step numbers; digits in the item text stay put
    with tempfile.TemporaryDirectory() as d:
        exp = "Intro line.\n\nTop 10 tips for you. 1\n\nSecond item here. 2\n\nThird item there. 3\n\nEnd line.\n"
        r, errors, st = run_pipeline(m, exp, _apply_suggested_lists, final=True, state=os.path.join(d, "s.json"))
        assert errors == [] and r["status"] == "validated" and "1. Top 10 tips for you." in st["text"], (errors, r)
        st = m._new_state("Buy 7 get 3 free today.\n")
        assert m._apply(st, [{"op": "number_list", "lines": [1, 1], "text": "Buy 3 get 7 free today."}]), "digits swapped"
        st = m._new_state("This is not safe at all.\n")
        assert m._apply(st, [{"op": "move_heading", "lines": [1, 1], "text": "This is safe at all.\n\nnot"}]), "word lifted"
        st = m._new_state("Take 3.5 mg daily\n\n1\n\nSecond item here\n\n2\n")   # a number from inside a sentence
        assert m._apply(st, [{"op": "number_list", "lines": [1, 3], "text": "5. Take 3. mg daily\n\n1"}]), "mid-sentence number"
        st = m._new_state("Alpha item\n\n1\n\nBeta item\n\n2\n")   # markers keep their order
        assert m._apply(st, [{"op": "number_list", "lines": [1, 7], "text": "2. Alpha item\n1. Beta item"}]), "markers swapped"
        assert not m._apply(st, [{"op": "number_list", "lines": [1, 7], "text": "1. Alpha item\n2. Beta item"}])
        st = m._new_state("Alpha item\n\n1\n\nBeta item\n\n2\n\nGamma item\n\n3\n")   # markers keep order, stay home
        for bad in ("2. Alpha item\n\n1\n\nBeta item\n\n3. Gamma item", "Alpha item\n\n2. Beta item\n\n3. Gamma item\n\n1"):
            assert m._apply(st, [{"op": "number_list", "lines": [1, 11], "text": bad}]), bad
        assert not m._apply(st, [{"op": "number_list", "lines": [1, 11], "text": "1. Alpha item\n2. Beta item\n3. Gamma item"}])
        st = m._new_state("Launched in\n2026\n\n5\n\nNext step here.\n")   # a year is not a step number
        assert m._apply(st, [{"op": "number_list", "lines": [2, 6], "text": "\n5\n\n2026. Next step here."}]), "year lifted"
        st = m._new_state("Launched in\n\n2026\n\nNext step here.\n")
        assert m._apply(st, [{"op": "number_list", "lines": [1, 5], "text": "Launched in\n\n2026. Next step here."}]), "year"
        st = m._new_state("Alpha item\n\n1\n\nBeta item\n\nGamma item\n")   # a marker cannot travel past other items
        assert m._apply(st, [{"op": "number_list", "lines": [1, 7], "text": "Alpha item\n\nBeta item\n\n1. Gamma item"}])
        # a sentence line flagged by another issue type (code label) is not movable next to a letter-spaced line
        exp = "Intro line.\n\nStep one: unplug.\nStep two: press `RESET`.\nW H Y\nStep three: wait.\n\nEnd.\n"
        p3 = os.path.join(d, "v.json")
        m.pipeline(exp, p3)
        st = m._load_state(p3)
        L = st["text"].split("\n")
        a, b = L.index("Step one: unplug.") + 1, L.index("Step three: wait.") + 1
        blk = next(x for x in st["issues"] if x["lines"][0] <= a + 1 <= x["lines"][1])
        assert m._apply(st, [{"issue": blk["id"], "op": "move_heading", "lines": [a, b],
                               "text": "Step two: press `RESET`.\nStep one: unplug.\nW H Y\nStep three: wait."}], st["issues"])
        # only flagged lines may move: a plain sentence line next to a flagged heading stays where it is
        exp = "Intro line.\n\nDo not\nW H Y\npress the red button.\n\nEnd.\n"
        p2 = os.path.join(d, "u.json")
        m.pipeline(exp, p2)
        st = m._load_state(p2)
        L = st["text"].split("\n")
        a, b = L.index("Do not") + 1, L.index("press the red button.") + 1
        blk = next(x for x in st["issues"] if x["lines"][0] <= a + 1 <= x["lines"][1])
        assert m._apply(st, [{"issue": blk["id"], "op": "move_heading", "lines": [a, b],
                               "text": "W H Y\npress the red button.\nDo not"}], st["issues"]), "sentence line moved"
        # a hand-edited ledger pointing outside the export is thrown away, never a traceback
        m._save_state(p2, {**st, "ledger": [{"letters": [0, 10 ** 6], "reason": "x"}]})
        assert m.pipeline(exp, p2, final=True)["status"] in ("validated", "failed", "needs_review")
        # a letter map that no longer matches its text: never validated, never a traceback
        p = os.path.join(d, "t.json")
        m.pipeline(GUIDE, p)
        st = m._load_state(p)
        m._save_state(p, {**st, "lmap": st["lmap"][:-5]})
        assert m.pipeline(GUIDE, p, final=True)["status"] != "validated"
        st = m._load_state(p)
        assert m._apply(st, [{"op": "replace", "lines": [1, 1], "text": st["text"].split("\n")[0]}])
    # a logged letter cut from inside a word fails, even when a lookalike standalone letter sits next to it
    exp = "W H Y Books s tips\n"
    st = m._new_state(exp)
    assert not m._apply(st, [{"op": "replace", "lines": [1, 1], "drops": ["s"], "reason": "x", "text": "W H Y Book s tips"}])
    r = m.reconcile(st, exp)[0]
    assert not r["ok"] and r["partial_word_drops"], r


@fixture
def ledger_guards(m):
    """A logged deletion that cuts into a word fails; a logged deletion that takes a picture with it fails."""
    exp = "The troubleshooting guide.\n"
    st = m._new_state(exp)
    assert not m._apply(st, [{"op": "replace", "lines": [1, 1], "text": "The shooting guide.", "drops": ["trouble"], "reason": "x"}])
    r, _ = m.reconcile(st, exp)
    assert not r["ok"] and r["partial_word_drops"], r
    exp = "Intro text.\n\n![][image1]Caption here.\n\n[image1]: <data:image/png;base64,AAAA>\n"
    st = m._new_state(exp)
    L = st["text"].split("\n")
    a = L.index("[image 1]") + 1
    assert not m._apply(st, [{"op": "delete", "lines": [a, a + 1], "reason": "x"}])
    r, _ = m.reconcile(st, exp)
    assert not r["ok"] and r["images"]["missing"] == ["1"], r["images"]


@fixture
def pipeline_resumes_after_a_crash(m):
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "s.json")
        st = m._new_state(GUIDE)   # the crash came right after strip: state saved, autofix never ran
        m._save_state(p, st)
        open(p + ".tmp", "w").write("{half a write")   # and a torn temp file from the crashed write
        r = m.pipeline(GUIDE, p, final=True)
        assert r["status"] == "validated" and r["autofixed"] > 0, r
        again = m.pipeline(GUIDE, p, final=True)
        assert again["clean_sha256"] == r["clean_sha256"] and again["autofixed"] == r["autofixed"], again


# ---------------------------------------------------------------- A2: one version everywhere

def version_places(m):
    """The 7 places the version is written. Returns {place: version found}."""
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    run = lambda *a: subprocess.run([sys.executable, m.__file__, *a], env=env, capture_output=True, text=True,
                                    encoding="utf-8", timeout=60)
    read = lambda *p: open(os.path.join(*p), encoding="utf-8").read()
    with tempfile.TemporaryDirectory() as d:
        f = os.path.join(d, "a.md")
        open(f, "w", encoding="utf-8").write("Hello.\n")
        strip_v = json.loads(run("strip", f, "-o", f + ".out").stdout).get("version")
        check_v = json.loads(run("check", f, f).stdout).get("version")
    first = lambda pat, text: (re.search(pat, text, re.M) or [None, None])[1]
    return {
        "script __version__": getattr(m, "__version__", None),
        "--version": run("--version").stdout.strip() or None,
        "strip and check JSON": strip_v if strip_v == check_v else f"strip {strip_v} / check {check_v}",
        "plugin.json": json.loads(read(PLUGIN, ".claude-plugin", "plugin.json")).get("version"),
        "marketplace.json": first(r"^v(\S+) - ", json.loads(read(ROOT, ".claude-plugin", "marketplace.json"))
                                  ["plugins"][0]["description"]),
        "CHANGELOG.md": first(r"^## (\S+) - ", read(PLUGIN, "CHANGELOG.md")),
        "SKILL.md": first(r"This is version (\S+?)\.? ", read(PLUGIN, "skills", "legit-pdf2md", "SKILL.md")),
    }


@fixture
def one_version_everywhere(m):
    v = version_places(m)
    assert len(v) == 7 and None not in v.values() and len(set(v.values())) == 1, v


# ---------------------------------------------------------------- D2: Drive transaction (fake Drive)

QSTR = r"'((?:[^'\\]|\\.)*)'"   # a quoted string in a Drive query: an unescaped quote ends it


class FakeDrive:
    """Just enough Drive for drive_txn: files by id, a log of calls, and switches for the failures. Queries are
    parsed as strictly as Drive does (an unescaped quote is a 400), `name contains` matches the start of a name,
    My Drive root is 'root', and a shared drive's files are found only with the all-drives flags."""
    def __init__(self, create_error=None, corrupt_readback=False, copy_id=True, export_error=None,
                 no_link=False, trash_sticks=True):
        self.files = {"src": {"id": "src", "name": "Guide.pdf", "mimeType": PDF, "parents": ["fold"]},
                      "src2": {"id": "src2", "name": "Other.pdf", "mimeType": PDF, "parents": ["foldB"]},
                      "src3": {"id": "src3", "name": "Guide.pdf", "mimeType": PDF, "parents": ["foldC"]},   # same title
                      "doc": {"id": "doc", "name": "Notes", "mimeType": DOC, "parents": ["fold"]},
                      "deck": {"id": "deck", "name": "Deck", "mimeType": DOC, "parents": ["sd"], "driveId": "D1"},
                      "orphan": {"id": "orphan", "name": "Shared", "mimeType": DOC}}   # no parents visible
        self.shared = {"sd"}   # folders in a shared drive
        self.log, self.urls, self.n, self.copies = [], {}, 0, 0
        self.create_error, self.corrupt, self.copy_id = create_error, corrupt_readback, copy_id
        self.export_error, self.no_link, self.trash_sticks = export_error, no_link, trash_sticks
        self.key_error = self.find_error = None

    def _url(self, text):
        self.n += 1
        self.urls[f"u{self.n}"] = text
        return {"file": {"s3url": f"u{self.n}"}}

    def created(self):
        return [(f["name"], f["parent"]) for f in self.files.values() if "parent" in f]

    def __call__(self, slug, a, account=None):
        self.log.append((slug, a.get("fileId") or a.get("file_id") or a.get("file_name")))
        f = self.files.get(a.get("fileId") or a.get("file_id"), {})
        if slug == "GOOGLEDRIVE_GET_FILE_METADATA":   # only the fields asked for, as Drive does
            if not f:
                return {"data": None}, "404 File not found"
            want = a["fields"].split(",")
            return {"data": {k: f.get(k, False if k == "trashed" else None) for k in want
                             if k in f or k == "trashed"}}, ""
        if slug == "GOOGLEDRIVE_COPY_FILE_ADVANCED":
            self.copies += 1
            tid = f"tmp{self.copies}"
            self.files[tid] = {"id": tid, "name": a["name"], "mimeType": DOC, "parents": a["parents"],
                               "body": f.get("pdf_text", "Export.\r\n"), "ocr": a.get("ocrLanguage"),
                               **({"description": a["description"]} if "description" in a else {})}
            return {"data": {"id": tid} if self.copy_id else {"name": a["name"]}}, ""
        if slug == "GOOGLEDRIVE_EXPORT_GOOGLE_WORKSPACE_FILE":
            if self.export_error:
                return {"data": None}, self.export_error
            return {"data": self._url(f.get("body", "Export.\n"))}, ""
        if slug == "GOOGLEDRIVE_CREATE_FILE_FROM_TEXT":
            if a.get("parent_id") and self.create_error:
                return {"data": None}, self.create_error
            nid = f"out{len(self.created()) + 1}"
            self.files[nid] = {"id": nid, "name": a["file_name"], "parent": a.get("parent_id", "root"),
                               "body": a["text_content"].replace("\n", "\r\n") + ("x" if self.corrupt else "")}
            return {"data": {"id": nid}}, ""
        if slug == "GOOGLEDRIVE_DOWNLOAD_FILE":
            return {"data": {"id": f["id"]} if self.no_link else {"downloaded_file_content": self._url(f["body"])}}, ""
        if slug == "GOOGLEDRIVE_TRASH_FILE":
            f["trashed"] = self.trash_sticks
            return {"data": {"id": f["id"]}}, ""
        if slug == "GOOGLEDRIVE_FIND_FILE":
            if self.find_error and "'root' in parents" not in a["q"]:   # the source's folder only
                return {"data": None}, self.find_error
            q = re.fullmatch(rf"name (=|contains) {QSTR} and {QSTR} in parents(?: and mimeType = {QSTR})? and trashed = false", a["q"])
            if not q:
                return {"data": None}, "400 Invalid Value: q"
            op, name, folder, mime = q.groups()
            name, folder = (re.sub(r"\\(.)", r"\1", s) for s in (name, folder))
            if folder in self.shared and not (a.get("includeItemsFromAllDrives") and a.get("supportsAllDrives")):
                return {"data": {"files": [], "kind": "drive#fileList"}}, ""
            want = re.fullmatch(r"files\(([^)]*)\)", a.get("fields", "files(id,name)")).group(1).split(",")
            hits = [{k: x[k] for k in want if k in x}
                    for x in self.files.values()
                    if (x.get("name") == name if op == "=" else x.get("name", "").startswith(name))
                    and x.get("parent", (x.get("parents") or [None])[0]) == folder and not x.get("trashed")
                    and (mime is None or x.get("mimeType") == mime)]
            return {"data": {"files": hits[:a.get("pageSize", 100)], "kind": "drive#fileList"}}, ""   # one page
        if slug == "GOOGLEDRIVE_UPDATE_FILE_PUT":
            if isinstance(self.key_error, Exception):
                raise self.key_error
            if self.key_error:
                return {"data": None}, self.key_error
            f["description"] = a["description"]
            return {"data": {"id": f["id"]}}, ""
        raise AssertionError(slug)


def _refused(fn, why):
    try:
        fn()
    except Exception as e:
        if type(e).__name__ not in ("DriveError", "NoRoom"):
            raise
        return str(e)
    raise AssertionError(why)


@fixture
def drive_txn_saves_verifies_then_trashes_only_its_own(m):
    spec = importlib.util.spec_from_file_location("drive_txn", os.path.join(os.path.dirname(m.__file__), "drive_txn.py"))
    t = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(t)
    text = "# Guide\n\nClean text.\n"
    ok = t.sha(text)
    with tempfile.TemporaryDirectory() as d:
        e = os.path.join(d, "e.md")
        fd = FakeDrive()

        def mk(src, account="me", journals=d, **k):
            x = t.Txn(fd, account, src, journals=journals, fetch=fd.urls.__getitem__, **k)
            x.open()
            return x
        trashes = lambda: [i for s, i in fd.log if s == "GOOGLEDRIVE_TRASH_FILE"]
        for step in (lambda x: x.export(e), lambda x: x.save(text, ok, "Guide - clean.md"),
                     lambda x: x.reusable("Guide - clean.md"), lambda x: x.cleanup()):
            _refused(lambda: step(t.Txn(fd, "me", "src", journals=d)), "used before open() checked the run")
        x = mk("src")
        x.export(os.path.join(d, "export.md"))
        assert open(os.path.join(d, "export.md"), encoding="utf-8", newline="").read() == "Export.\r\n"   # as exported
        assert fd.files["tmp1"]["parents"] == ["root"], "the temporary Doc goes in the private My Drive root"
        assert fd.files["tmp1"]["description"] == "legit-pdf2md temp: source src modified None", fd.files["tmp1"]
        mk("src").export(os.path.join(d, "export.md"))   # the same source reopened mid-run (a later cell)
        assert fd.copies == 1, fd.copies
        _refused(lambda: x.cleanup(), "trash before a verified save")
        _refused(lambda: x.save(text + "!", ok, "Guide - clean.md"), "saved text that is not the checked text")
        assert not fd.created()
        # a second run on another source keeps its own journal: run A's save and cleanup are untouched
        y = mk("src2")
        y.export(os.path.join(d, "b.md"))
        assert x.save(text, ok, "Guide - clean.md")["where"] == "beside the source"   # read-back came back CRLF
        assert fd.created() == [("Guide - clean.md", "fold")] and fd.files["out1"]["body"].endswith("\r\n"), fd.created()
        # no modified time from Drive: no reuse key, so nothing can match every version
        assert "description" not in fd.files["out1"] and x.reuse_key() is None and x.reusable("Guide - clean.md") is None
        # the save cell run again (after a context reset): the same file back, never a second one
        assert mk("src").save(text, ok, "Guide - clean.md")["id"] == "out1" and len(fd.created()) == 1
        other = "# Other\n"
        _refused(lambda: mk("src").save(other, t.sha(other), "Guide - clean.md"), "a second, different save")
        z = mk("src")   # cell 1 run again before cleanup: the run carries on, no second temp Doc
        assert z.j.get("temp_doc") == "tmp1" and z.j.get("saved_ok") and fd.copies == 2, (z.j, fd.copies)
        c = mk("src")   # a later cell, from the journal
        assert c.cleanup() == {"temp_doc": "tmp1", "trashed": True}
        assert c.cleanup() == {"temp_doc": "tmp1", "trashed": True} and c.j["temp_trashed"]
        assert trashes() == ["tmp1"] and "trashed" not in fd.files["tmp2"] and "trashed" not in fd.files["src"]
        _refused(lambda: y.cleanup(), "run B trashed before its own save")
        # finished: the save cell run again starts a new run, which finds the identical file: no second save
        assert mk("src", None).save(text, ok, "Guide - clean.md")["id"] == "out1" and len(fd.created()) == 1
        z = mk("src", "other")   # finished: pins no account on the next run
        assert "temp_doc" not in z.j and "saved" not in z.j and z.j["account"] == "other", z.j
        # nor test mode: a finished test-mode run leaves the next run free
        mk("doc", test_folder="fold").save(text, ok, "Notes - clean.md")
        assert t.Txn(fd, None, "doc", journals=d).account is None, "a finished run's account leaks into the next"
        assert mk("doc", None).test_folder is None
        assert t.Txn(fd, "me", "src2", journals=d).j["temp_doc"] == "tmp2"   # a mid-run journal is kept
        # one run, one account: a later cell cannot switch it, and one that names none inherits it
        _refused(lambda: mk("src2", "other"), "account switched mid-run")
        assert mk("src2", None).account == "me"

    for name, fd_kw, save_kw, expect in (
            ("read-back differs", {"corrupt_readback": True}, {}, "does not match"),
            ("no read-back link", {"no_link": True}, {}, "no download link"),
            ("rate limit is not a permission error", {"create_error": "403 User rate limit exceeded"}, {}, "rate limit"),
            ("quota is not a permission error", {"create_error": "403 The storage quota has been exceeded"}, {}, "quota"),
            ("a missing folder is not a permission error",
             {"create_error": "404 File not found: fold. Check the permissions."}, {}, "not found"),
            ("test mode never falls back", {"create_error": "403 insufficient permissions"}, {"test_folder": "fold"}, "insufficient"),
            ("test mode, another folder", {}, {"test_folder": "elsewhere"}, "test mode"),
            ("a permission error while searching is not a refused save", {}, {}, "sufficient permissions")):
        with tempfile.TemporaryDirectory() as d:
            fd = FakeDrive(**fd_kw)
            fd.files["src"]["modifiedTime"] = "T1"
            fd.files["same"] = {"id": "same", "name": "Guide - clean.md", "parent": "fold", "body": text}   # identical text
            x = t.Txn(fd, "me", "src", journals=d, fetch=fd.urls.__getitem__, **save_kw)
            x.open()
            x.export(os.path.join(d, "e.md"))
            if name.startswith("a permission error while searching"):
                fd.find_error = "403 The user does not have sufficient permissions for this file."
            elif name != "test mode, another folder":   # there, an identical file beside the source must not matter
                del fd.files["same"]
            err = _refused(lambda: x.save(text, ok, "Guide - clean.md"), name)
            assert expect in err, (name, err)
            assert not [c for c in fd.created() if c[1] == "root"], (name, "fell back to My Drive root")
            assert not [f for f in fd.files.values() if "description" in f and "parent" in f], (name, "key before read-back")
            _refused(lambda: x.cleanup(), (name, "trashed after a failed save"))
            assert not [s for s, _ in fd.log if s == "GOOGLEDRIVE_TRASH_FILE"], name

    with tempfile.TemporaryDirectory() as d:
        e = os.path.join(d, "e.md")

        def mk(src, account="me", journals=d, **k):
            x = t.Txn(fd, account, src, journals=journals, fetch=fd.urls.__getitem__, **k)
            x.open()
            return x
        # no permission beside the source: My Drive root, it says why, and a re-run finds it there by its key
        fd = FakeDrive(create_error="403 The user does not have sufficient permissions for this file.")
        fd.files["doc"]["modifiedTime"] = "T1"
        s = mk("doc").save(text, ok, "Notes - clean.md")
        assert "no permission" in s["where"] and fd.created()[0][1] == "root" and s["reuse_key"], s
        assert mk("doc", journals=d + "/again").reusable("Notes - clean.md") == \
            {"id": s["id"], "name": "Notes - clean.md", "where": "My Drive root"}
        # a source Drive shows no folder for: root, and never called "beside the source"
        assert "no folder" in mk("orphan").save(text, ok, "Shared - clean.md")["where"]
        fd = FakeDrive(create_error="400 Cannot add files to this folder")   # Drive's other wording for it
        assert "no permission" in mk("doc", journals=d + "/cannot").save(text, ok, "Notes - clean.md")["where"]
        # test mode is kept in the journal: a later cell without it, or with another folder, cannot drop it
        fd = FakeDrive()
        mk("src2", test_folder="fold")
        later = mk("src2")
        later.export(e)
        _refused(lambda: later.save(text, ok, "Other - clean.md"), "a later cell dropped test mode")
        _refused(lambda: mk("src2", test_folder="x"), "test folder switched mid-run")
        # a sandbox reset between cells (/mnt/files empty): the temp Doc id carried in the chat rebuilds the run
        fd = FakeDrive()
        mk2 = lambda sub, **k: mk("src", journals=os.path.join(d, "reset", sub), **k)
        mk2("a").export(e)
        b = mk2("b", temp_doc="tmp1")   # fresh sandbox
        b.export(e)
        assert fd.copies == 1 and b.j["temp_doc"] == "tmp1", (fd.copies, b.j)
        lost = mk2("x")   # the id lost from the chat as well: found in My Drive by its stamp, never a second copy
        lost.export(e, copy=False)
        assert fd.copies == 1 and lost.j["temp_doc"] == "tmp1", (fd.copies, lost.j)
        b.save(text, ok, "Guide - clean.md")
        _refused(lambda: mk2("b", temp_doc="budget"), "a temp id from the chat that contradicts the journal")
        c = mk2("c", temp_doc="tmp1")   # reset again between the save and the cleanup
        assert c.save(text, ok, "Guide - clean.md")["id"] == "out1" and len(fd.created()) == 1, fd.created()
        assert c.cleanup() == {"temp_doc": "tmp1", "trashed": True}
        assert "in the trash" in _refused(lambda: mk2("e", temp_doc="tmp1"), "a finished run restarted")
        _refused(lambda: mk2("n").export(e, copy=False), "a later cell made a new temp Doc")   # a trashed one is not found
        assert fd.copies == 1
        _refused(lambda: mk2("f", temp_doc="src"), "adopted the source as the temp Doc")
        fd.files["budget"] = {"id": "budget", "name": "Budget", "mimeType": DOC, "parents": ["root"]}
        assert "is not this run's" in _refused(lambda: mk2("g", temp_doc="budget"), "adopted someone else's Doc")
        # lookalikes carrying a copied stamp: a PDF with the temp name, a Doc whose name only starts like it
        for bad, kind, nm in (("pdfl", PDF, "Guide - temp"), ("cpy", DOC, "Guide - temp copy")):
            fd.files[bad] = {"id": bad, "name": nm, "mimeType": kind, "parents": ["root"], "description": c.temp_stamp()}
            _refused(lambda: mk2("l" + bad, temp_doc=bad), "adopted " + bad)
        _refused(lambda: mk2("lk").export(e, copy=False), "a search adopted a stamped lookalike")
        assert all("trashed" not in fd.files[i] for i in ("budget", "src", "pdfl", "cpy"))
        # F1: a Google Doc source makes no temporary Doc, so it never takes one: the user's own "Notes - temp" is safe
        fd.files["mine"] = {"id": "mine", "name": "Notes - temp", "mimeType": DOC, "parents": ["root"],   # even stamped
                            "description": "legit-pdf2md temp: source doc modified None"}
        _refused(lambda: mk("doc", journals=d + "/F1", temp_doc="mine"), "a Doc source took a temp_doc")
        assert "trashed" not in fd.files["mine"]
        # a same-named file with other content is not taken for this run's save
        fd.files["prev"] = {"id": "prev", "name": "Notes - clean.md", "parent": "fold", "body": "# old\n"}
        s = mk("doc", journals=os.path.join(d, "reset", "h")).save(text, ok, "Notes - clean.md")
        assert s["id"] not in ("prev", None) and s["name"] == "Notes - clean (2).md", s   # never overwrite
        # reset between that "(2)" save and the next cell: the identical "(2)" is this run's save, never a "(3)"
        n = len(fd.created())
        assert mk("doc", journals=os.path.join(d, "reset", "h2")).save(text, ok, "Notes - clean.md")["id"] == s["id"]
        assert len(fd.created()) == n
        # D3: a re-run on the unchanged source finds the keyed clean file and does no work: no copy, no save
        fd.files["src"]["modifiedTime"] = "T1"
        r1 = mk2("r1")
        r1.export(e)
        s1 = r1.save(text, ok, "Guide - clean.md")
        assert s1["reuse_key"] and fd.files[s1["id"]]["description"].endswith("modified T1"), s1
        copies, saves = fd.copies, len(fd.created())
        assert mk2("r2").reusable("Guide - clean.md") == {"id": s1["id"], "name": s1["name"], "where": "beside the source"}
        assert fd.copies == copies and len(fd.created()) == saves
        # the source changed: no reuse, and the new clean file is "(2)", the old one untouched
        fd.files["src"]["modifiedTime"] = "T2"
        r3 = mk2("r3")
        assert r3.reusable("Guide - clean.md") is None
        r3.export(e)
        other = "# Guide\n\nChanged text.\n"
        s3 = r3.save(other, t.sha(other), "Guide - clean.md")
        assert s3["name"] == "Guide - clean (2).md" and fd.files[s1["id"]]["body"].startswith("# Guide\r\n\r\nClean"), s3
        # the key cannot be set: the save still stands, and says so, even when the call itself blows up
        for n, err in ((3, "500 backend error"), (4, TimeoutError("slow"))):
            fd.key_error = err
            r4 = mk2(f"r4{n}")
            r4.export(e)
            body = f"# Guide\n\nText {n}.\n"
            s4 = r4.save(body, t.sha(body), "Guide - clean.md")
            assert s4["reuse_key"] is False and s4["name"] == f"Guide - clean ({n}).md", s4
            assert json.load(open(r4.path))["saved_ok"], "the verified save is on disk before the key is tried"
        fd.key_error = None

    with tempfile.TemporaryDirectory() as d:
        e = os.path.join(d, "e.md")

        def mk(src, account="me", journals=d, **k):
            x = t.Txn(fd, account, src, journals=journals, fetch=fd.urls.__getitem__, **k)
            x.open()
            return x
        # F2: two PDFs with the same title in different folders never take each other's temporary Doc
        fd = FakeDrive()
        mk("src", journals=d + "/A").export(e)
        assert "is not this run's" in _refused(lambda: mk("src3", journals=d + "/B", temp_doc="tmp1"),
                                               "run B adopted run A's temporary Doc")
        B = mk("src3", journals=d + "/B")
        B.export(e)
        assert B.j["temp_doc"] == "tmp2" and fd.copies == 2 and not B.j.get("leftovers"), B.j
        B.save(text, ok, "Guide - clean.md")
        assert B.cleanup()["trashed"] and "trashed" not in fd.files["tmp1"]
        # X1: an unfinished journal left from an older version of the source is never carried on
        fd = FakeDrive()
        fd.files["src"].update(modifiedTime="T1", pdf_text="OLD VERSION TEXT\n")
        mk("src", journals=d + "/X1").export(e)   # tmp1, never saved
        fd.files["src"].update(modifiedTime="T2", pdf_text="NEW VERSION TEXT\n")
        new = mk("src", "another", journals=d + "/X1")   # its old account pin does not bind a new run either
        new.export(e)
        assert open(e, encoding="utf-8").read() == "NEW VERSION TEXT\n" and new.j["temp_doc"] == "tmp2", new.j
        assert new.j["leftovers"] == ["tmp1"] and new.reuse_key().endswith("modified T2"), new.j
        # F3: the source edited between the start cell and a later one: the run stops, whatever the sandbox kept
        fd = FakeDrive()
        fd.files["src"]["modifiedTime"] = "T1"
        mk("src", journals=d + "/F3").export(e)   # tmp1, stamped T1
        fd.files["src"]["modifiedTime"] = "T2"
        for sub in ("/F3", "/F3-reset"):
            assert "source changed" in _refused(lambda: mk("src", journals=d + sub, temp_doc="tmp1"), "stale temp Doc"), sub
        gone = mk("src", journals=d + "/F3-lost")   # the id lost too: the old version's Doc is not taken
        _refused(lambda: gone.export(e, copy=False), "exported the old version's temporary Doc")
        assert gone.j["leftovers"] == ["tmp1"] and fd.copies == 1, gone.j
        restart = mk("src", journals=d + "/F3")   # the start cell again: a new copy for the new version
        restart.export(e)
        assert restart.j["temp_doc"] == "tmp2" and "tmp1" in restart.j["leftovers"] and fd.copies == 2, restart.j
        assert not [f for f in fd.files.values() if (f.get("description") or "").startswith(t.REUSE)]
        # F5: a same-named file with identical text but the user's own description is theirs: saved as "(2)"
        fd = FakeDrive()
        fd.files["note"] = {"id": "note", "name": "Notes - clean.md", "parent": "fold", "body": text,
                            "description": "my notes, do not touch"}
        s = mk("doc", journals=d + "/F5").save(text, ok, "Notes - clean.md")
        assert s["name"] == "Notes - clean (2).md" and fd.files["note"]["description"] == "my notes, do not touch", s
        # nor is one keyed to another source: the reuse key names the source
        fd = FakeDrive()
        fd.files["kx"] = {"id": "kx", "name": "Notes - clean.md", "parent": "fold", "body": text,
                          "description": "legit-pdf2md reuse: source elsewhere modified T1"}
        assert mk("doc", journals=d + "/F5b").save(text, ok, "Notes - clean.md")["name"] == "Notes - clean (2).md"
        # names: a lookalike never counts ("... .md.bak"), "(10)" does, and quotes and backslashes are escaped
        fd = FakeDrive()
        fd.files["bak"] = {"id": "bak", "name": "Notes - clean.md.bak", "parent": "fold", "body": text}
        s = mk("doc", journals=d + "/bak").save(text, ok, "Notes - clean.md")
        assert s["id"] != "bak" and s["name"] == "Notes - clean.md", s
        fd = FakeDrive()
        for n in range(1, 121):   # past one default page of 100
            nm = "Notes - clean.md" if n == 1 else f"Notes - clean ({n}).md"
            fd.files[f"n{n}"] = {"id": f"n{n}", "name": nm, "parent": "fold", "body": f"# {n}\n"}
        assert mk("doc", journals=d + "/ten").save(text, ok, "Notes - clean.md")["name"] == "Notes - clean (121).md"
        fd = FakeDrive()
        fd.files["q"] = {"id": "q", "name": "O'Brien \\ notes", "mimeType": DOC, "parents": ["fold"]}
        fd.files["qc"] = {"id": "qc", "name": "O'Brien \\ notes - clean.md", "parent": "fold", "body": "# other\n"}
        s = mk("q", journals=d + "/q").save(text, ok, "O'Brien \\ notes - clean.md")
        assert s["name"] == "O'Brien \\ notes - clean (2).md", s
        # a shared drive: its files are found only with the all-drives flags, so "(2)" is still right there
        fd.files["dc"] = {"id": "dc", "name": "Deck - clean.md", "parent": "sd", "body": "# other\n"}
        assert mk("deck", journals=d + "/sd").save(text, ok, "Deck - clean.md")["name"] == "Deck - clean (2).md"
        # the copy returned no id: stops, and the next start cell finds that copy by its stamp instead of a second
        fd = FakeDrive(copy_id=False)
        x = mk("src", journals=d + "/noid")
        assert "no id" in _refused(lambda: x.export(e), "untracked temp Doc")
        fd.copy_id = True
        x = mk("src", journals=d + "/noid-reset")
        x.export(e)
        assert fd.copies == 1 and x.j["temp_doc"] == "tmp1", (fd.copies, x.j)
        # the OCR language reaches the copy
        fd = FakeDrive()
        mk("src", journals=d + "/o").export(e, "de")
        assert fd.files["tmp1"]["ocr"] == "de", fd.files["tmp1"]
        # a trash Drive does not confirm is not reported as done
        fd = FakeDrive(trash_sticks=False)
        x = mk("src", journals=d + "/t")
        x.export(e)
        x.save(text, ok, "Guide - clean.md")
        assert "does not report it trashed" in _refused(lambda: x.cleanup(), "unconfirmed trash")
        # the copy is logged before it is used: a failed export leaves the temp Doc in the journal
        fd = FakeDrive(export_error="500 backend error")
        x = mk("src", journals=d + "/e")
        _refused(lambda: x.export(e), "export error swallowed")
        assert json.load(open(x.path))["temp_doc"] == "tmp1"
        # a journal whose temp Doc is the source itself (damaged) never trashes the source
        json.dump({"source": fd.files["src"], "temp_doc": "src", "saved_ok": True}, open(x.path, "w"))
        _refused(lambda: mk("src", journals=d + "/e").cleanup(), "trashed the source")
        assert "trashed" not in fd.files["src"]


# ---------------------------------------------------------------- runner

def load(path):
    spec = importlib.util.spec_from_file_location("clean_gdoc_md", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def regression(m, export, clean):
    src = open(export, encoding="utf-8").read()
    out, st = m.strip(src)
    r = m.check(src, out)
    print(f"regression strip: {st['est_tokens_in']} -> {st['est_tokens_out']} tokens, images {r['images']['source'][:3]}..."
          f" ({len(r['images']['source'])}), kept_in_code {r['images']['kept_in_code']}")
    ok = r["images"]["ok"] and not r["added_runs"] and not r["partial_word_drops"]
    print(f"  check(export, strip output): images ok {r['images']['ok']}, added {r['added_runs']}, "
          f"partial {r['partial_word_drops']}")
    if clean:
        r = m.check(src, open(clean, encoding="utf-8").read())
        print(f"  check(export, {os.path.basename(clean)}): ok {r['ok']}, images {json.dumps({k: v for k, v in r['images'].items() if k not in ('source', 'cleaned')})}")
        ok = ok and r["ok"]
    return ok


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--script", default=SCRIPT)
    ap.add_argument("--regression", nargs="+", metavar="FILE")
    a = ap.parse_args()
    m = load(a.script)
    failed = 0
    for fn in FIXTURES:
        try:
            fn(m)
            print(f"pass     {fn.__name__}")
        except Exception as e:   # a missing function on an older script is a failure too
            failed += 1
            print(f"FAIL     {fn.__name__}: {type(e).__name__}: {str(e)[:300]}")
    for name, (step, what) in PENDING.items():
        print(f"pending  {name} ({step}: {what})")
    print(f"{len(FIXTURES) - failed}/{len(FIXTURES)} fixtures passed, {len(PENDING)} pending")
    if a.regression and not regression(m, a.regression[0], a.regression[1] if len(a.regression) > 1 else None):
        failed += 1
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
