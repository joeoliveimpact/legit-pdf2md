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
import argparse, importlib.util, json, os, re, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLUGIN = os.path.join(ROOT, "plugins", "legit-pdf2md")
SCRIPT = os.path.join(PLUGIN, "skills", "legit-pdf2md", "scripts", "clean_gdoc_md.py")
DOC, PDF = "application/vnd.google-apps.document", "application/pdf"
FIXTURES = []
PENDING = {   # name: (plan step that makes it live, what it will prove)
    "real_line_next_to_furniture": ("B2", "a real sentence deleted next to page furniture comes out needs_review"),
    "furniture_word_deleted_elsewhere": ("B2", "a furniture word deleted on another line never reconciles a real deletion"),
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
