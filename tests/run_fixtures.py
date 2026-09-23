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
    assert m.clean_name("export.md", "text/markdown") == "export.md - clean.md"


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

class FakeDrive:
    """Just enough Drive for drive_txn: files by id, a log of calls, and switches for the failures."""
    def __init__(self, create_error=None, corrupt_readback=False, copy_id=True, export_error=None,
                 no_link=False, trash_sticks=True):
        self.files = {"src": {"id": "src", "name": "Guide.pdf", "mimeType": PDF, "parents": ["fold"]},
                      "src2": {"id": "src2", "name": "Other.pdf", "mimeType": PDF, "parents": ["foldB"]},
                      "doc": {"id": "doc", "name": "Notes", "mimeType": DOC, "parents": ["fold"]},
                      "orphan": {"id": "orphan", "name": "Shared", "mimeType": DOC}}   # no parents visible
        self.log, self.urls, self.n, self.copies = [], {}, 0, 0
        self.create_error, self.corrupt, self.copy_id = create_error, corrupt_readback, copy_id
        self.export_error, self.no_link, self.trash_sticks = export_error, no_link, trash_sticks

    def _url(self, text):
        self.n += 1
        self.urls[f"u{self.n}"] = text
        return {"file": {"s3url": f"u{self.n}"}}

    def created(self):
        return [(f["name"], f["parent"]) for f in self.files.values() if "parent" in f]

    def __call__(self, slug, a, account=None):
        self.log.append((slug, a.get("fileId") or a.get("file_id") or a.get("file_name")))
        f = self.files.get(a.get("fileId") or a.get("file_id"), {})
        if slug == "GOOGLEDRIVE_GET_FILE_METADATA":
            return ({"data": {k: v for k, v in f.items() if k != "body"}}, "") if f else ({"data": None}, "404 File not found")
        if slug == "GOOGLEDRIVE_COPY_FILE_ADVANCED":
            self.copies += 1
            tid = f"tmp{self.copies}"
            self.files[tid] = {"id": tid, "name": a["name"], "mimeType": DOC, "parents": a["parents"], "body": "Export.\r\n",
                               "ocr": a.get("ocrLanguage")}
            return {"data": {"id": tid} if self.copy_id else {"name": a["name"]}}, ""
        if slug == "GOOGLEDRIVE_EXPORT_GOOGLE_WORKSPACE_FILE":
            if self.export_error:
                return {"data": None}, self.export_error
            return {"data": self._url(f.get("body", "Export.\n"))}, ""
        if slug == "GOOGLEDRIVE_CREATE_FILE_FROM_TEXT":
            if a.get("parent_id") and self.create_error:
                return {"data": None}, self.create_error
            nid = f"out{len(self.created()) + 1}"
            self.files[nid] = {"id": nid, "name": a["file_name"], "parent": a.get("parent_id", "ROOT"),
                               "body": a["text_content"].replace("\n", "\r\n") + ("x" if self.corrupt else "")}
            return {"data": {"id": nid}}, ""
        if slug == "GOOGLEDRIVE_DOWNLOAD_FILE":
            return {"data": {"id": f["id"]} if self.no_link else {"downloaded_file_content": self._url(f["body"])}}, ""
        if slug == "GOOGLEDRIVE_TRASH_FILE":
            f["trashed"] = self.trash_sticks
            return {"data": {"id": f["id"]}}, ""
        raise AssertionError(slug)


def _refused(fn, why):
    try:
        fn()
    except Exception as e:
        if type(e).__name__ != "DriveError":
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
        fd = FakeDrive()
        mk = lambda src, **k: t.Txn(fd, "me", src, journals=d, fetch=fd.urls.__getitem__, **k)
        trashes = lambda: [i for s, i in fd.log if s == "GOOGLEDRIVE_TRASH_FILE"]
        x = mk("src")
        x.open()
        x.export(os.path.join(d, "export.md"))
        assert open(os.path.join(d, "export.md"), encoding="utf-8", newline="").read() == "Export.\r\n"   # as exported
        assert fd.files["tmp1"]["parents"] == ["root"], "the temporary Doc goes in the private My Drive root"
        mk("src").open()   # the same source reopened mid-run (a later cell): no second copy
        mk("src").export(os.path.join(d, "export.md"))
        assert fd.copies == 1, fd.copies
        _refused(lambda: x.cleanup(), "trash before a verified save")
        _refused(lambda: x.save(text + "!", ok, "Guide - clean.md"), "saved text that is not the checked text")
        assert not fd.created()
        # a second run on another source keeps its own journal: run A's save and cleanup are untouched
        y = mk("src2")
        y.open()
        y.export(os.path.join(d, "b.md"))
        assert x.save(text, ok, "Guide - clean.md")["where"] == "beside the source"   # read-back came back CRLF
        assert fd.created() == [("Guide - clean.md", "fold")] and fd.files["out1"]["body"].endswith("\r\n"), fd.created()
        # the save cell run again (after a context reset): the same file back, never a second one
        assert mk("src").save(text, ok, "Guide - clean.md")["id"] == "out1" and len(fd.created()) == 1
        other = "# Other\n"
        _refused(lambda: mk("src").save(other, t.sha(other), "Guide - clean.md"), "a second, different save")
        z = mk("src")   # cell 1 run again before cleanup: the run carries on, no second temp Doc
        z.open()
        assert z.j.get("temp_doc") == "tmp1" and z.j.get("saved_ok") and fd.copies == 2, (z.j, fd.copies)
        assert mk("src").cleanup() == {"temp_doc": "tmp1", "trashed": True}   # a later cell, from the journal
        assert mk("src").cleanup() == {"temp_doc": "tmp1", "trashed": True} and mk("src").j["temp_trashed"]
        assert trashes() == ["tmp1"] and "trashed" not in fd.files["tmp2"] and "trashed" not in fd.files["src"]
        _refused(lambda: y.cleanup(), "run B trashed before its own save")
        assert t.Txn(fd, None, "src", journals=d).save(text, ok, "x")["id"] == "out1"   # finished: still answers
        z = t.Txn(fd, "other", "src", journals=d, fetch=fd.urls.__getitem__)   # finished: pins no account on the next run
        z.open()
        assert "temp_doc" not in z.j and "saved" not in z.j and z.j["account"] == "other", z.j
        # nor test mode: a finished test-mode run leaves the next run free
        w = t.Txn(fd, "me", "doc", journals=d, test_folder="fold", fetch=fd.urls.__getitem__)
        w.open()
        w.save(text, ok, "Notes - clean.md")
        assert t.Txn(fd, None, "doc", journals=d).test_folder is None
        assert mk("src2").j["temp_doc"] == "tmp2"   # a mid-run journal is kept
        # one run, one account: a later cell cannot switch it, and one that names none inherits it
        _refused(lambda: t.Txn(fd, "other", "src2", journals=d), "account switched mid-run")
        assert t.Txn(fd, None, "src2", journals=d).account == "me"

    for name, fd_kw, save_kw, expect in (
            ("read-back differs", {"corrupt_readback": True}, {}, "does not match"),
            ("no read-back link", {"no_link": True}, {}, "no download link"),
            ("rate limit is not a permission error", {"create_error": "403 User rate limit exceeded"}, {}, "rate limit"),
            ("quota is not a permission error", {"create_error": "403 The storage quota has been exceeded"}, {}, "quota"),
            ("test mode never falls back", {"create_error": "403 insufficient permissions"}, {"test_folder": "fold"}, "insufficient"),
            ("test mode, another folder", {}, {"test_folder": "elsewhere"}, "test mode")):
        with tempfile.TemporaryDirectory() as d:
            fd = FakeDrive(**fd_kw)
            x = t.Txn(fd, "me", "src", journals=d, fetch=fd.urls.__getitem__, **save_kw)
            x.open()
            x.export(os.path.join(d, "e.md"))
            err = _refused(lambda: x.save(text, ok, "Guide - clean.md"), name)
            assert expect in err, (name, err)
            assert not [c for c in fd.created() if c[1] == "ROOT"], (name, "fell back to My Drive root")
            _refused(lambda: x.cleanup(), (name, "trashed after a failed save"))
            assert not [s for s, _ in fd.log if s == "GOOGLEDRIVE_TRASH_FILE"], name

    with tempfile.TemporaryDirectory() as d:
        # no permission beside the source: My Drive root, and it says why
        fd = FakeDrive(create_error="403 The user does not have sufficient permissions for this file.")
        x = t.Txn(fd, "me", "doc", journals=d, fetch=fd.urls.__getitem__)
        x.open()
        assert "no permission" in x.save(text, ok, "Notes - clean.md")["where"] and fd.created()[0][1] == "ROOT"
        # a source Drive shows no folder for: root, and never called "beside the source"
        x = t.Txn(fd, "me", "orphan", journals=d, fetch=fd.urls.__getitem__)
        x.open()
        assert "no folder" in x.save(text, ok, "Shared - clean.md")["where"]
        # test mode is kept in the journal: a later cell without it, or with another folder, cannot drop it
        fd = FakeDrive()
        t.Txn(fd, "me", "src2", journals=d, test_folder="fold", fetch=fd.urls.__getitem__).open()
        later = t.Txn(fd, "me", "src2", journals=d, fetch=fd.urls.__getitem__)
        later.export(os.path.join(d, "e.md"))
        _refused(lambda: later.save(text, ok, "Other - clean.md"), "a later cell dropped test mode")
        _refused(lambda: t.Txn(fd, "me", "src2", journals=d, test_folder="x"), "test folder switched mid-run")
        # the OCR language reaches the copy
        fd = FakeDrive()
        x = t.Txn(fd, "me", "src", journals=d + "/o", fetch=fd.urls.__getitem__)
        x.open()
        x.export(os.path.join(d, "e.md"), "de")
        assert fd.files["tmp1"]["ocr"] == "de", fd.files["tmp1"]
        # a trash Drive does not confirm is not reported as done
        fd = FakeDrive(trash_sticks=False)
        x = t.Txn(fd, "me", "src", journals=d + "/t", fetch=fd.urls.__getitem__)
        x.open()
        x.export(os.path.join(d, "e.md"))
        x.save(text, ok, "Guide - clean.md")
        assert "does not report it trashed" in _refused(lambda: x.cleanup(), "unconfirmed trash")
        # the copy is logged before it is used: a failed export leaves the temp Doc in the journal
        fd = FakeDrive(export_error="500 backend error")
        x = t.Txn(fd, "me", "src", journals=d + "/e", fetch=fd.urls.__getitem__)
        x.open()
        _refused(lambda: x.export(os.path.join(d, "e.md")), "export error swallowed")
        assert json.load(open(x.path))["temp_doc"] == "tmp1"
        # a copy whose id was lost is reported by the next attempt, and a copy with no id stops the run
        j = json.load(open(x.path))
        j.pop("temp_doc")
        json.dump(j, open(x.path, "w"))
        fd = FakeDrive(copy_id=False)
        x = t.Txn(fd, "me", "src", journals=d + "/e", fetch=fd.urls.__getitem__)
        assert "Guide - temp" in _refused(lambda: x.export(os.path.join(d, "e.md")), "untracked temp Doc")
        assert "Guide - temp" in json.load(open(x.path))["possible_orphan"]
        # a journal whose temp Doc is the source itself (damaged) never trashes the source
        json.dump({"source": fd.files["src"], "temp_doc": "src", "saved_ok": True}, open(x.path, "w"))
        _refused(lambda: t.Txn(fd, "me", "src", journals=d + "/e").cleanup(), "trashed the source")
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
