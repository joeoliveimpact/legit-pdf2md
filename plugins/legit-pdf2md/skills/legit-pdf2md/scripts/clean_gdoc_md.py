#!/usr/bin/env python3
"""Clean a Google Docs Markdown export. Standard library only.

  clean_gdoc_md.py strip INPUT -o OUTPUT   remove export junk, print stats + a rebuild worklist (JSON)
  clean_gdoc_md.py check SOURCE CLEANED    compare wording and images; exit 1 if anything was invented, cut or
                                           merged, or an image was lost, invented or reordered
  clean_gdoc_md.py selftest                prove strip and check both work
  clean_gdoc_md.py --version               print the version

strip never changes wording. Outside fenced code blocks it removes base64 images (kept as
[image N] placeholders), HTML entities like &nbsp;, broken characters, Google's backslash
escapes, code-font backticks around letter-spaced text and bare numbers, stray OCR asterisks
between letters, trailing spaces, and extra blank lines. Fenced code blocks (also inside quotes
and lists) and inline code are left untouched, except inline code holding nothing but images. Each image placeholder gets its own
line, except inside list items, headings, quotes and tables. The worklist names the lines that need judgment.
"""
__version__ = "0.1.4"

import argparse, bisect, collections, difflib, hashlib, html, json, os, re, secrets, subprocess, sys, tempfile, unicodedata

DATA_DEF = re.compile(r"^\[image(\d+)\]:[ \t]*<?data:image/[^\s>]*>?[ \t]*$", re.M)   # base64 image definition only
REF_USE = re.compile(r"!\[[^\]]*\]\[image(\d+)\]")                                   # ![][image1]
INLINE_DATA = re.compile(r"!\[[^\]]*\]\(\s*<?data:image/[^)\s>]*>?\s*\)")            # ![](data:image/...)
BOLD_WRAP = re.compile(r"\*\*\s*(\[image \d+\])\s*\*\*")
ENTITY = re.compile(r"&(?:[A-Za-z][A-Za-z0-9]{1,31}|#\d{1,7}|#[xX][0-9A-Fa-f]{1,6});")
ESC = re.compile(r"\\([\[\]().!#+\-=~{}&])")    # \* \_ \` \| \< \> stay escaped: they still matter
# An escape that stops a line (or a blockquote / list item) becoming syntax stays escaped. A heading whose
# own text starts with a hash keeps it too, so "# \#Tag" does not read back as the doubled marker "# # Tag".
LINE_HEAD_ESC = re.compile(
    r"^(\s*(?:>\s*)*(?:#{1,6}[ \t]+\\#|(?:(?:[-*+]|\d+[.)])\s+)?(?:\d+\\[.)]|\\[#>+\-=])))")
STRAY_MID = re.compile(r"(?<=[^\W\d_])\*+(?=[^\W\d_])")        # OCR: Con*tract (letters both sides only)
EMPH_JOIN = re.compile(r"(?<=[^\W_])[*_]+(?=[^\W_])")           # markers inside a word: un**paid**, **Fathom**B
SPACED = re.compile(r"(?:(?<![^\s*_`])\S ){2,}\S(?![^\s*_`])")  # "S T A R T", "W H Y", "**D a y 1**"
PLACEHOLDER = re.compile(r"\[image \d+\]")
# CommonMark code span: a backtick run, content (no blank line), the same-length run. ``a`b`` included.
CODE_SPAN = re.compile(r"(?<!`)(`+)(?!`)((?:(?!\n[ \t]*\n).)+?)(?<!`)\1(?!`)", re.S)
QUOTE_PREFIX = re.compile(r"^(?:[ ]{0,3}>[ ]?)*")
FENCE_OPEN = re.compile(r"^(?:[ ]{0,3}>[ ]?)*([ \t]*)((?:[-*+]|\d+[.)])[ \t]+)?(`{3,}|~{3,})(.*)$")
FENCE_CLOSE = re.compile(r"^(?:[ ]{0,3}>[ ]?)*[ \t]*(`{3,}|~{3,})[ \t]*$")
ASTERISK_RUN = re.compile(r"\*+")
BLOCK_LINE = re.compile(r"^\s*(?:[-*+]\s|\d+[.)]\s|#|>|\||\[image \d+\])")   # list items, headings, quotes, tables, images
IMAGE_ONLY = re.compile(r"\s*(?:" + REF_USE.pattern + r"\s*)+")                 # `![][image6]![][image7]`
IMAGE_TOKEN = re.compile(f"{REF_USE.pattern}|{INLINE_DATA.pattern}|{PLACEHOLDER.pattern}")
CONTAINER_LINE = re.compile(r"^\s*(?:[-*+]\s|\d+[.)]\s|#|>|\|)")   # list item, heading, quote, table: images stay inline
BLOCK_START = re.compile(r"^(?:[-*+](?:\s|$)|\d+[.)](?:\s|$)|#|>|\||[-=*_ ]+$|```|~~~)")   # text that would become syntax
JOINERS = "\0\ufffd\u200b\u200c\u200d\ufeff"   # removed by strip without splitting a word, so check joins across them


# ---------------------------------------------------------------- structure

def _quote_depth(line):
    return QUOTE_PREFIX.match(line).group(0).count(">")


def _line_kinds(lines):
    """'prose', 'fence' (a delimiter line) or 'code' for each line. Per CommonMark: a fence may sit inside
    blockquotes and list items; it closes on the same character repeated at least as many times as the
    opener at the same quote depth, or implicitly when its blockquote or list item ends (a line outside the
    quote, or a non-blank line indented less than the item's content); an unclosed fence runs to the end."""
    kinds, opener = [], None   # opener = (char, length, quote depth, list content indent or None)
    for line in lines:
        if opener is not None:
            depth = _quote_depth(line)
            body = line[QUOTE_PREFIX.match(line).end():]
            ended = (opener[2] and depth < opener[2]) or (
                opener[3] is not None and body.strip() and len(body) - len(body.lstrip(" \t")) < opener[3])
            if not ended:
                m = FENCE_CLOSE.match(line)
                if m and depth == opener[2] and m.group(1)[0] == opener[0] and len(m.group(1)) >= opener[1]:
                    kinds.append("fence")
                    opener = None
                else:
                    kinds.append("code")
                continue
            opener = None   # the container ended, so the fence did too; classify this line afresh
        m = FENCE_OPEN.match(line)
        if m and not (m.group(3)[0] == "`" and "`" in m.group(4)):
            indent = len(m.group(1)) + len(m.group(2)) if m.group(2) else None
            opener = (m.group(3)[0], len(m.group(3)), _quote_depth(line), indent)
            kinds.append("fence")
        else:
            kinds.append("prose")
    return kinds


def _blocks(lines):
    """Group lines into (is_prose, lines) runs."""
    blocks = []
    for line, kind in zip(lines, _line_kinds(lines)):
        prose = kind == "prose"
        if blocks and blocks[-1][0] == prose:
            blocks[-1][1].append(line)
        else:
            blocks.append((prose, [line]))
    return blocks


def _blank(m):   # same length, line breaks kept
    return re.sub("[^\n]", " ", m.group(0))


def _image_only(code, defined):
    """Inline code holding nothing but references to defined images: the export's code font around pictures."""
    return bool(IMAGE_ONLY.fullmatch(code)) and all(i in defined for i in REF_USE.findall(code))


# ---------------------------------------------------------------- strip

def _split_images(text):
    """Give each placeholder its own line (a single line break, so the paragraph renders the same). Lines that
    are list items, headings, quotes or tables keep theirs inline, and text that would turn into syntax on a
    line of its own ("- x", "# x", "---") stays after its placeholder."""
    out = []
    for line in text.split("\n"):
        if not PLACEHOLDER.search(line) or CONTAINER_LINE.match(line):
            out.append(line)
            continue
        indent, new = line[:len(line) - len(line.lstrip())], []   # an indented line stays inside its list item
        for piece in (p.strip() for p in re.split(r"(\[image \d+\])", line)):
            if not piece:
                continue
            if new and not PLACEHOLDER.fullmatch(piece) and BLOCK_START.match(piece):
                new[-1] += " " + piece
            else:
                new.append(piece)
        out.extend(indent + p for p in new)
    return "\n".join(out)


def _unescape_line(line):
    m = LINE_HEAD_ESC.match(line)
    head = m.group(1) if m else ""
    return head + ESC.sub(r"\1", line[len(head):])


def _strip_stray_asterisks(line):
    """Remove asterisk runs sitting between two letters, unless they open or close real emphasis."""
    n, pos = 0, 0
    while True:
        m = STRAY_MID.search(line, pos)
        if not m:
            return line, n
        run = m.group(0)
        closes = len(ASTERISK_RUN.findall(line[:m.start()])) % 2 == 1                  # **Fathom**B
        opens = any(len(r) == len(run) for r in ASTERISK_RUN.findall(line[m.end():]))  # B**old**
        if closes or opens:
            pos = m.end()
            continue
        line = line[:m.start()] + line[m.end():]
        n += 1
        pos = m.start()


def _clean_prose(text, s):
    s["nbsp_chars"] += text.count("\u00a0")
    text, n = ENTITY.subn(lambda m: html.unescape(m.group(0)), text)
    s["html_entities"] += n
    text = text.replace("\u00a0", " ")
    s["broken_chars"] += text.count("\ufffd")
    text = re.sub(r"(?m)^([ \t]*)\ufffd+[ \t]?", r"\1", text)   # only at line start may it take the space after it
    text = text.replace("\ufffd", "")
    text = re.sub("[\u200b\u200c\u200d\ufeff]", "", text)
    s["escapes"] += len(ESC.findall(text))
    out = []
    for line in text.split("\n"):
        line, n = _strip_stray_asterisks(_unescape_line(line))
        s["ocr_asterisks"] += n
        out.append(line)
    text = "\n".join(out)
    text = re.sub(r"(?<=\S) {2,}(?=\S)", " ", text)
    text = re.sub(r"[ \t]+$", "", text, flags=re.M)
    return re.sub(r"\n{3,}", "\n\n", text)


def strip(text):
    s = collections.Counter({k: 0 for k in ("code_spans_unwrapped", "nbsp_chars", "html_entities", "broken_chars",
                                           "escapes", "ocr_asterisks", "inline_images", "image_spans_unwrapped")})
    s["chars_in"] = len(text)
    text = text.replace("\r\n", "\n")
    nonce = secrets.token_hex(8)
    while nonce in text:
        nonce = secrets.token_hex(8)
    left, right = f"\ue000{nonce}:", "\ue001"
    kept, in_code = [], []
    raw_blocks = _blocks(text.split("\n"))
    defined = set(DATA_DEF.findall(CODE_SPAN.sub(_blank, "\n".join(l for p, ls in raw_blocks if p for l in ls))))

    def _mask(m):   # display labels and image-only spans lose their backticks; real inline code is set aside untouched
        c = m.group(2)
        if _image_only(c, defined):
            s["image_spans_unwrapped"] += 1
            return c
        if SPACED.search(c) or re.fullmatch(r"\s*\d{1,3}\s*", c):
            s["code_spans_unwrapped"] += 1
            return c
        in_code.extend(i for i in REF_USE.findall(c) if i in defined)
        kept.append(m.group(0))
        return f"{left}{len(kept) - 1}{right}"

    blocks = [(p, CODE_SPAN.sub(_mask, "\n".join(lines)) if p else "\n".join(lines)) for p, lines in raw_blocks]
    prose = "\n".join(t for p, t in blocks if p)
    data_ids = set(DATA_DEF.findall(prose))
    s["image_definitions"] = len(DATA_DEF.findall(prose))
    s["image_refs"] = sum(1 for i in REF_USE.findall(prose) if i in data_ids)
    staged = [(p, REF_USE.sub(lambda m: f"[image {m.group(1)}] " if m.group(1) in data_ids else m.group(0),
                              DATA_DEF.sub("", t)) if p else t) for p, t in blocks]
    ids = [int(x) for p, t in staged if p for x in re.findall(r"\[image (\d+)\]", t)]
    nxt = iter(range(max(ids, default=0) + 1, 10**6))
    unmask = re.compile(re.escape(left) + r"(\d+)" + re.escape(right))
    parts = []
    for p, t in staged:
        if p:
            t, n = INLINE_DATA.subn(lambda m: f"[image {next(nxt)}] ", t)
            s["inline_images"] += n
            t = _clean_prose(_split_images(BOLD_WRAP.sub(r"\1", t)), s)
            t = unmask.sub(lambda m: kept[int(m.group(1))] if int(m.group(1)) < len(kept) else m.group(0), t)
        parts.append(t)
    text = "\n".join(parts).lstrip("\n").rstrip() + "\n"
    s["chars_out"] = len(text)
    s["est_tokens_in"], s["est_tokens_out"] = s["chars_in"] // 4, s["chars_out"] // 4
    s["images_kept_in_code"] = in_code   # their definitions are gone, so the picture is lost: name them in the report
    return text, dict(s)


def worklist(text):
    lines = text.split("\n")
    kinds = _line_kinds(lines)
    prose = [(i, l) for i, (l, k) in enumerate(zip(lines, kinds)) if k == "prose"]
    pick = lambda pred: [{"line": i + 1, "text": l[:100]} for i, l in prose if pred(l)]
    no_code = lambda l: CODE_SPAN.sub("", l)
    view = lambda l: re.sub(r"[`*_]", "", l).strip()   # inline formatting removed, for sentence tests only
    counts = collections.Counter(l.strip() for _, l in prose if l.strip() and not PLACEHOLDER.fullmatch(l.strip()))
    openings = collections.defaultdict(list)
    for i, l in prose:
        words = re.sub(r"^[#>*\-\d.\s`]+", "", l).split()
        if len(words) >= 3 and min(len(w) for w in words[:2]) >= 2:  # single letters are letter_spaced's job
            openings[" ".join(words[:2]).lower()].append(i + 1)
    paras = [(i, l) for i, l in prose if l.strip()]
    splits = []
    for (i, ra), (j, rb) in zip(paras, paras[1:]):
        if any(kinds[k] != "prose" for k in range(i, j)) or BLOCK_LINE.match(ra) or BLOCK_LINE.match(rb):
            continue   # block structure (lists, headings, code) is never a split sentence
        a, b = view(ra), view(rb)
        if a and b and re.match(r"[a-z]", b) and not re.search(r"[.!?:;\"')\]]$", a):
            splits.append({"line": i + 1, "text": f"{a[-50:]} / {b[:40]}"})
    caps_span = lambda l: any(re.search(r"[^\W\d_]", m.group(2)) and not any(ch.islower() for ch in m.group(2))
                              for m in CODE_SPAN.finditer(l))
    return {
        "letter_spaced": pick(lambda l: SPACED.search(l)),
        "detached_numbers": pick(lambda l: re.fullmatch(r"\s*\d{1,2}\s*", l) or re.search(r"[.!?:]\s+\d{1,2}\s*$", l)),
        "split_sentences": splits,
        "repeated_lines": [{"text": k[:100], "count": v} for k, v in counts.most_common() if v >= 3],
        "repeated_openings": [{"opening": k, "lines": v} for k, v in openings.items() if len(v) >= 3],
        "code_spans": pick(caps_span),
        "odd_asterisks": pick(lambda l: re.sub(r"^\s*[*] ", "", no_code(l)).count("*") % 2),
        "image_lines": pick(lambda l: PLACEHOLDER.search(l)),
    }


# ---------------------------------------------------------------- wording check

def _prepare(text):
    """Blank fence delimiter lines (with info strings) and removed junk to same-length whitespace, decode
    entities padded with NUL (a decoded line break becomes a space, so lines never shift), and turn markers
    inside a word into NULs. Code lines and inline code stay exactly as written. Positions line up with the
    input, and nothing strip removes splits a word."""
    text = text.replace("\r\n", "\n")
    lines = text.split("\n")
    kinds = _line_kinds(lines)
    out = [" " * len(l) if k == "fence" else l for l, k in zip(lines, kinds)]
    groups, cur = [], []
    for i, k in enumerate(kinds):
        if k == "prose":
            cur.append(i)
        elif cur:
            groups.append(cur)
            cur = []
    if cur:
        groups.append(cur)
    blank = lambda m: re.sub("[^" + chr(10) + "]", " ", m.group(0))   # keep embedded line breaks
    outside = "\n".join(CODE_SPAN.sub(blank, "\n".join(lines[i] for i in g)) for g in groups)
    ids = set(DATA_DEF.findall(outside))

    def _ent(m):
        d = html.unescape(m.group(0))
        if "\n" in d or "\r" in d:
            d = " "
        return (d + "\0" * len(m.group(0)))[:len(m.group(0))] if len(d) <= len(m.group(0)) else m.group(0)

    def _segment(seg):
        seg = DATA_DEF.sub(blank, seg)
        seg = REF_USE.sub(lambda m: blank(m) if m.group(1) in ids else m.group(0), seg)
        seg = INLINE_DATA.sub(blank, seg)
        seg = ENTITY.sub(_ent, PLACEHOLDER.sub(blank, seg))
        return EMPH_JOIN.sub(lambda m: "\0" * len(m.group(0)), seg)

    for g in groups:
        blk = "\n".join(lines[i] for i in g)
        parts, last = [], 0
        for m in CODE_SPAN.finditer(blk):
            parts.append(_segment(blk[last:m.start()]))
            parts.append(_segment(m.group(0)) if _image_only(m.group(2), ids) else m.group(0))
            last = m.end()
        parts.append(_segment(blk[last:]))
        new_lines = "".join(parts).split("\n")
        assert len(new_lines) == len(g), "line structure changed during preparation"
        for i, line in zip(g, new_lines):
            out[i] = line
    return "\n".join(out)


def _stream(text):
    """Letters, digits and combining marks (any script), canonically composed per word, casefolded, with each
    unit's position and the word boundary in front of it: None inside a word, 'hard' between ordinary words,
    'soft' between letters of letter-spaced type (3+ single-character words joined by plain spaces).
    Alignment runs on letters only; boundaries are compared afterwards, so spaces never distort the diff."""
    t = _prepare(text)
    words, cur = [], None
    for i, ch in enumerate(t):
        if ch in JOINERS:
            continue
        if ch.isalnum() or unicodedata.category(ch).startswith("M"):
            if cur is None:
                cur = []
            if cur:   # canonical composition: e + U+0301, Hangul jamo sequences
                composed = unicodedata.normalize("NFC", cur[-1][0] + ch)
                if len(composed) == 1:
                    cur[-1][0] = composed
                    continue
            base = unicodedata.normalize("NFC", ch)
            cur.append([base if len(base) == 1 else ch, i])
        elif cur is not None:
            words.append(cur)
            cur = None
    if cur is not None:
        words.append(cur)
    n = len(words)

    def spaced_sep(k):   # plain spacing between words k-1 and k, allowing one spaced symbol like " · "
        sep = t[words[k - 1][-1][1] + 1:words[k][0][1]].replace("\0", "")
        return bool(sep) and sep[0] in " \t" and "\n" not in sep and len(sep.strip()) <= 1

    def chunk(k):
        """OCR joins two or three letters of display type together: "P A S TE", "P R OM P T", "WR ITE"."""
        return 2 <= len(words[k]) <= 3 and all(c.isupper() or c.isdigit() for c, _ in words[k])

    in_run = [False] * n
    k = 0
    while k < n:
        if len(words[k]) == 1:
            e = k + 1
            while e < n and spaced_sep(e) and (len(words[e]) == 1 or chunk(e)):
                e += 1
            # a run always starts on a single character, and ends on one or on a single trailing chunk
            # ("P A S TE:"), never on a stretch of ordinary words: "GO H O M E", "H O M E PA GE" stay merges
            while e - 1 > k and len(words[e - 1]) != 1 and len(words[e - 2]) != 1:
                e -= 1
            singles = sum(1 for w in words[k:e] if len(w) == 1)
            if singles >= 3 and singles >= (e - k) - singles:   # mostly single characters, not ordinary words
                in_run[k:e] = [True] * (e - k)
            k = e
        else:
            k += 1

    def kind(k):
        if in_run[k - 1] and in_run[k] and spaced_sep(k):
            return "soft"
        prev = words[k - 1]
        if (in_run[k] and not in_run[k - 1] and spaced_sep(k) and len(prev) > 1 and prev[-1][0].isupper()
                and any(ch.islower() for ch, _ in prev[:-1]) and words[k][0][0].isupper()):
            return "glue"   # a capital glued onto a mixed-case word before a spaced run: "MetricoolB O N U S"
        return "hard"

    chars, pos, bound = [], [], []
    for k, w in enumerate(words):
        first = True
        for ch, p in w:
            for c in ch.casefold():   # caseless (final sigma, ß); one character may fold to several, same position
                chars.append(c)
                pos.append(p)
                bound.append((kind(k) if k else None) if first else None)
                first = False
    return t, "".join(chars), pos, bound


def _show(seq, bound, x, y):
    return "".join((" " if k > x and bound[k] else "") + seq[k] for k in range(x, y))


def _bounded(seq, bound, x, y):
    return (x == 0 or bound[x] is not None) and (y == len(seq) or bound[y] is not None)


def _resolve(sa, bbound, j):
    """A glued-capital boundary counts as soft only when the cleaned text really split the word before the
    capital (MetricoolB to Metricool Bonus). Otherwise it is an ordinary hard boundary (ChatGPT P R O)."""
    if sa == "glue":
        return "soft" if j > 0 and bbound[j - 1] is not None else "hard"
    return sa


def _compatible(abound, bbound, s0, j1, n):
    """True when no word inside a candidate move is merged or split."""
    for k in range(1, n):
        sa, sb = _resolve(abound[s0 + k], bbound, j1 + k), bbound[j1 + k]
        if (sa == "hard" and sb is None) or (sa is None and sb is not None):
            return False
    return True


def _own_line(text, pos, j1, j2):
    """True when stream units j1..j2 are the only letters on their line (a heading or label)."""
    ls = text.rfind("\n", 0, pos[j1]) + 1
    le = text.find("\n", pos[j2 - 1])
    le = len(text) if le < 0 else le
    return bisect.bisect_left(pos, ls) >= j1 and bisect.bisect_left(pos, le) <= j2


def _whole_word(a, bound, i1, i2):
    """A deletion of a[i1:i2] is whole-word if some equivalent alignment starts and ends on word boundaries."""
    x, y = i1, i2
    while True:
        if _bounded(a, bound, x, y):
            return True
        if x > 0 and a[x - 1] == a[y - 1]:
            x, y = x - 1, y - 1
        else:
            break
    x, y = i1, i2
    while y < len(a) and a[x] == a[y]:
        x, y = x + 1, y + 1
        if _bounded(a, bound, x, y):
            return True
    return False


def _pair_moves(a, abound, b, bbound, drops, adds, ct, bpos):
    """Pair each added run with deleted text. Both ends must sit on word boundaries in both texts, so a
    letter shuffled inside a word is never a move. Exact matches are candidates; so is part of a longer
    deletion when the run is 6+ letters or stands on its own line as a heading. Among candidates, one whose
    inner word boundaries agree is preferred. A consumed deletion splits into separate prefix and suffix
    deletions that are never rejoined. Returns moves as (j1, j2, source start)."""
    drops = list(drops)
    moved, unmatched = [], []
    for j1, j2 in adds:
        x = b[j1:j2]
        candidates = []
        if _bounded(b, bbound, j1, j2):
            candidates = [(k, i1, i2, i1) for k, (i1, i2) in enumerate(drops)
                          if a[i1:i2] == x and _bounded(a, abound, i1, i2)]
            if len(x) >= 6 or _own_line(ct, bpos, j1, j2):
                for k, (i1, i2) in enumerate(drops):
                    off = a.find(x, i1, i2)
                    while off >= 0:
                        if (off, off + len(x)) != (i1, i2) and _bounded(a, abound, off, off + len(x)):
                            candidates.append((k, i1, i2, off))
                        off = a.find(x, off + 1, i2)
        hit = next((c for c in candidates if _compatible(abound, bbound, c[3], j1, len(x))),
                   candidates[0] if candidates else None)
        if hit is None:
            unmatched.append((j1, j2))
            continue
        k, i1, i2, start = hit
        moved.append((j1, j2, start))
        rest = [(i1, start), (start + len(x), i2)]
        drops[k:k + 1] = [(p, q) for p, q in rest if q > p]
    return moved, unmatched, drops


def _images(text):
    """The document's images in reading order as placeholder ids, read straight from the text and never from
    strip's output: base64 references (also in inline code holding nothing but images), inline data images
    numbered the way strip numbers them, and [image N] placeholders. Fenced code is ignored. Also returns the
    images left inside other inline code, whose pictures strip cannot keep."""
    lines = text.replace("\r\n", "\n").split("\n")
    prose = "\n".join(l if k == "prose" else "" for l, k in zip(lines, _line_kinds(lines)))
    defined = set(DATA_DEF.findall(CODE_SPAN.sub(_blank, prose)))
    found, kept, last = [], [], 0

    def scan(seg):
        for m in IMAGE_TOKEN.finditer(seg):
            ref, ph = REF_USE.fullmatch(m.group(0)), PLACEHOLDER.fullmatch(m.group(0))
            if ref:
                if ref.group(1) in defined:
                    found.append(ref.group(1))
            else:
                found.append(re.search(r"\d+", ph.group(0)).group(0) if ph else None)   # None: inline data

    for m in CODE_SPAN.finditer(prose):
        scan(prose[last:m.start()])
        if _image_only(m.group(2), defined):
            scan(m.group(2))
        else:
            kept += [i for i in REF_USE.findall(m.group(2)) if i in defined]   # inline data in code keeps its picture
        last = m.end()
    scan(prose[last:])
    nxt = iter(range(max((int(i) for i in found if i), default=0) + 1, 10**6))
    return [i or str(next(nxt)) for i in found], kept


def image_gate(source, cleaned):
    """Every image in the source must be a placeholder in the cleaned text, in the same order, none invented.
    An image the source itself repeats is expected as often as the source has it."""
    src, kept = _images(source)
    out = _images(cleaned)[0]
    missing = list((collections.Counter(src) - collections.Counter(out)).elements())
    invented = list((collections.Counter(out) - collections.Counter(src)).elements())
    a, b = list(src), list(out)
    for x in missing:
        a.remove(x)
    for x in invented:
        b.remove(x)
    return {"source": src, "cleaned": out, "missing": missing, "invented": invented, "in_order": a == b,
            "kept_in_code": kept, "ok": not missing and not invented and a == b}


def check(source, cleaned):
    """Compare wording, in any script, ignoring spacing, case, Markdown and removed junk.
    FAILS on: any added letter or digit that is not a whole-word move of deleted text; a deletion that cuts
    inside a word; two ordinary words merged into one (also inside moved text). REPORTS for review: whole
    words deleted inside a surviving line (inline_drops), whole lines deleted (dropped_lines), and one word
    split into two (split_words). Punctuation is not compared; code is compared exactly as written.
    Also FAILS when an image is lost, invented or reordered (images). drop_spans gives every deletion's letter
    range in the source's letter stream and its character range in the source (line breaks as LF), untruncated."""
    st, a, apos, abound = _stream(source)
    ct, b, bpos, bbound = _stream(cleaned)
    ops = difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes()
    merged, split, drops, adds = [], [], [], []

    def compare(i, j):
        sa, sb = _resolve(abound[i], bbound, j), bbound[j]
        if sa == "hard" and sb is None:
            merged.append(_show(a, abound, max(0, i - 12), min(len(a), i + 12)))
        elif sa is None and sb is not None:
            split.append(_show(b, bbound, max(0, j - 12), min(len(b), j + 12)))

    for t, i1, i2, j1, j2 in ops:
        if t == "equal":
            for k in range(i2 - i1):
                if not (k == 0 and (i1 == 0 or j1 == 0)):
                    compare(i1 + k, j1 + k)
        if t in ("delete", "replace") and i2 > i1:
            drops.append((i1, i2))
        if t in ("insert", "replace") and j2 > j1:
            adds.append((j1, j2))
    moved, added, drops = _pair_moves(a, abound, b, bbound, drops, adds, ct, bpos)
    for j1, j2, s0 in moved:
        for k in range(1, j2 - j1):
            compare(s0 + k, j1 + k)
    dropped_idx = {i for i1, i2 in drops for i in range(i1, i2)}
    partial, inline, lines, spans = [], [], [], []
    for i1, i2 in drops:
        frag = _show(a, abound, i1, i2)
        spans.append({"kind": "partial", "letters": [i1, i2], "chars": [apos[i1], apos[i2 - 1] + 1], "text": frag})
        if re.search(r"[^\W\d_]", frag) and not _whole_word(a, abound, i1, i2):
            partial.append(frag)
            continue
        ls = st.rfind("\n", 0, apos[i1]) + 1
        le = st.find("\n", apos[i2 - 1])
        le = len(st) if le < 0 else le
        survivors = any(ls <= p < le and k not in dropped_idx for k, p in enumerate(apos))
        (inline if survivors else lines).append(frag[:80])
        spans[-1]["kind"] = "inline" if survivors else "line"
    images = image_gate(source, cleaned)
    return {"version": __version__, "source_letters": len(a), "cleaned_letters": len(b),
            "added_runs": [_show(b, bbound, x, y) for x, y in added], "partial_word_drops": partial,
            "merged_words": merged, "moved_runs": [_show(b, bbound, x, y) for x, y, _ in moved],
            "split_words": split, "inline_drops": inline, "dropped_lines": lines, "drop_spans": spans,
            "images": images, "ok": not added and not partial and not merged and images["ok"]}


def clean_name(title, mime_type):
    """The clean file's name: the source's title, minus a trailing .pdf only when the source is a PDF (a dated
    title like "Notes 09.11.26" keeps every part), plus " - clean.md"."""
    if mime_type == "application/pdf" and title.lower().endswith(".pdf"):
        title = title[:-4]
    return f"{title} - clean.md"


# ---------------------------------------------------------------- pipeline: analyze, autofix, apply-edits

# Every edit, automatic or from the AI, goes through _edit. It follows each letter back to its position in the
# export (the letter map) and logs every intentional deletion there (the ledger). The final check compares the
# export with the result; a deletion the ledger cannot explain means needs_review, and the file is not saved.
HANDLE_OR_URL = re.compile(r"@\w{3,}|\b[\w-]+\.(?:com|ai|io|dev|co|org|net|app)\b|https?://")
NAV_MARK = re.compile(r"\bNext:|→|•|\|")
TRAILING_NUMBER = re.compile(r"^(.*[.!?:])\s+(\d{1,2})$")
MICRO_SPACED = re.compile(r"(?<![^\s*_])([A-Z](?: [a-z]){2,}) (\d{1,2})(?![^\s*_])")   # "S t e p 1", "D a y 2"
CODE_ONLY = re.compile(r"\s*`([^`]+)`\s*")   # a line that is one single-backtick code span
HOST_OPS = {"letter_spaced": ["replace", "move_heading", "delete"], "code_label": ["replace"],
            "odd_asterisks": ["replace"], "repeated_line": ["delete", "replace"],
            "page_nav_attached": ["replace"], "detached_number": ["number_list", "replace"]}


def _sha(text):
    return hashlib.sha256(text.replace("\r\n", "\n").encode("utf-8")).hexdigest()


def _rle(xs):
    runs = []
    for x in xs:
        if runs and runs[-1][0] + runs[-1][1] == x:
            runs[-1][1] += 1
        else:
            runs.append([x, 1])
    return runs


def _unrle(runs):
    return [s + k for s, n in runs for k in range(n)]


def _terminal(line):
    return bool(re.search(r"[.!?:;\"')\]]$", re.sub(r"[`*_]", "", line).strip()))


def _edit(st, a, b, text, op, drops=(), reason=None):
    """Replace lines a..b (1-based, inclusive) of st["text"] under op's rule, keeping the letter map and ledger
    true. Returns an error string and changes nothing, or None. Rules (letters = the check's letter stream):
    replace: letters identical once the exact `drops` substrings are removed (those go to the ledger).
    number_list: the same, except digits may move. move_heading: one whole line of the new text may be a
    contiguous piece of the old letters moved there; the rest keeps its order. delete: the lines go, logged."""
    old = st["text"]
    lines = old.split("\n")
    if not 1 <= a <= b <= len(lines):
        return f"lines {a}-{b} are outside the text (1-{len(lines)})"
    if drops and not reason or op == "delete" and not reason:
        return "a deletion needs a reason"
    c0 = len("\n".join(lines[:a - 1])) + (a > 1)
    seg = "\n".join(lines[a - 1:b])
    keep = [True] * len(seg)
    for d in drops:
        visible = [i for i, k in enumerate(keep) if k]
        at = "".join(seg[i] for i in visible).find(d) if d else -1
        if at < 0:
            return f"drop text not found on lines {a}-{b}: {d[:60]!r}"
        for i in visible[at:at + len(d)]:
            keep[i] = False
    if op == "delete":   # of the two blank lines around it, one goes too
        tail = b + 1 if a > 1 and b < len(lines) and not lines[a - 2].strip() and not lines[b].strip() else b
        keep, new = [False] * len(seg), "\n".join(lines[:a - 1] + lines[tail:])
        n_end = c0
    else:
        new = "\n".join(lines[:a - 1] + [text] + lines[b:])
        n_end = c0 + len(text)
    _, ca, pa, ba = _stream(old)
    _, cb, pb, _ = _stream(new)
    k0, k1 = bisect.bisect_left(pa, c0), bisect.bisect_left(pa, c0 + len(seg))
    n0, n1 = bisect.bisect_left(pb, c0), bisect.bisect_left(pb, n_end)
    if ca[:k0] != cb[:n0] or ca[k1:] != cb[n1:]:
        return "the edit changed letters outside its lines"
    lmap = st["lmap"]
    if len(lmap) != len(ca):
        return "the state's letter map does not match its text; run pipeline on a fresh state"
    kept = [k for k in range(k0, k1) if keep[pa[k] - c0]]
    gone = [k for k in range(k0, k1) if not keep[pa[k] - c0]]
    before, after = "".join(ca[k] for k in kept), cb[n0:n1]
    seg_map = [lmap[k] for k in kept]
    if op in ("replace", "delete"):
        if after != before:
            return "the new text changes the wording (letters differ from the source lines)"
    elif op == "number_list":
        # Only the list numbers at the start of the new lines may move, and each one must be a stand-alone number
        # of the original lines ("... account. 1", or "3" on its own line). Every other letter and digit, like
        # the 10 in "Top 10 tips", keeps its order.
        wid, w = [], -1
        for k in range(k0, k1):
            w += k == k0 or ba[k] is not None
            wid.append(w)
        words = collections.defaultdict(list)
        for k in range(k0, k1):
            words[wid[k - k0]].append(k)
        cand = [ks for _, ks in sorted(words.items()) if all(ca[k].isdigit() and keep[pa[k] - c0] for k in ks)]
        marks, off = [], c0
        for ln in text.split("\n"):
            m = re.match(r"\s*(\d+)[.)]\s", ln)
            if m:
                marks.append((m.group(1), [j for j in range(n0, n1) if off + m.start(1) <= pb[j] < off + m.end(1)]))
            off += len(ln) + 1
        mapped = None
        for order in (cand, cand[::-1]):   # the number that belongs to the item is usually the first match or the last
            used, picks = set(), []
            for v, js in marks:
                ks = next((ks for ks in order if id(ks) not in used and "".join(ca[k] for k in ks) == v), None)
                if ks is None or len(ks) != len(js):
                    break
                used.add(id(ks))
                picks.append((js, ks))
            if len(picks) != len(marks):
                continue
            taken_old = {k for _, ks in picks for k in ks}
            taken_new = {j for js, _ in picks for j in js}
            rest_old = [k for k in kept if k not in taken_old]
            rest_new = [j for j in range(n0, n1) if j not in taken_new]
            if "".join(ca[k] for k in rest_old) == "".join(cb[j] for j in rest_new):
                m_of = {j: lmap[k] for js, ks in picks for j, k in zip(js, ks)}
                it = iter(lmap[k] for k in rest_old)
                mapped = [m_of[j] if j in m_of else next(it) for j in range(n0, n1)]
                break
        if mapped is None:
            return "a number list may only move stand-alone step numbers to the start of its lines"
        seg_map = mapped
    elif op == "move_heading":
        # the moved piece must be whole original lines (a heading or label), never words lifted out of a sentence
        line_of = [seg.count("\n", 0, pa[k] - c0) for k in kept]
        starts = {i for i in range(len(kept)) if i == 0 or line_of[i] != line_of[i - 1]}
        ends = {i + 1 for i in range(len(kept)) if i + 1 == len(kept) or line_of[i + 1] != line_of[i]}
        found = None
        off = c0
        for ln in text.split("\n"):
            j0, j1 = bisect.bisect_left(pb, off) - n0, bisect.bisect_left(pb, off + len(ln)) - n0
            s = after[j0:j1]
            off += len(ln) + 1
            if not s:
                continue
            at = before.find(s)
            while at >= 0 and found is None:
                if at in starts and at + len(s) in ends and \
                        before[:at] + before[at + len(s):] == after[:j0] + after[j1:]:
                    found = (at, len(s), j0)
                at = before.find(s, at + 1)
        if found is None:
            return "move_heading must move one whole line of the original text, with everything else in order"
        at, n, j0 = found
        rest = seg_map[:at] + seg_map[at + n:]
        seg_map = rest[:j0] + seg_map[at:at + n] + rest[j0:]
    else:
        return f"unknown op {op!r}"
    for x0, n in _rle(sorted(lmap[k] for k in gone)):
        st["ledger"].append({"letters": [x0, x0 + n], "reason": reason})
    st["lmap"] = lmap[:k0] + seg_map + lmap[k1:]
    st["audit"].append({"op": op, "lines": [a, b], "reason": reason, "before": seg[:300],
                        "after": "" if op == "delete" else text[:300]})
    st["text"] = new
    return None


def analyze(text, nav_openings=()):
    """Issues in the text, each with an id, its lines, context, a confidence, whether autofix may apply it
    (safe_autofix) and the edit ops the AI may use on it. Autofix applies the safe ones; the rest go to the AI.
    nav_openings: page-navigation openings found earlier, so nav text still attached to a line is found after
    the stand-alone nav lines are gone."""
    lines = text.split("\n")
    kinds = _line_kinds(lines)
    prose = [i for i, k in enumerate(kinds) if k == "prose" and lines[i].strip()]
    plain = lambda l: re.sub(r"[`*]", "", l).strip()
    issues, taken = [], set()

    def ctx(i, step):
        j = i + step
        while 0 <= j < len(lines) and not lines[j].strip():
            j += step
        return j if 0 <= j < len(lines) else None

    def add(kind, a, b, conf, safe, fix=None, **extra):
        if any(i in taken for i in range(a, b + 1)):
            return
        taken.update(range(a, b + 1))
        p, n = ctx(a, -1), ctx(b, 1)
        issues.append({"type": kind, "lines": [a + 1, b + 1], "text": "\n".join(lines[a:b + 1]),
                       "before": lines[p][:120] if p is not None else "", "after": lines[n][:120] if n is not None else "",
                       "context_lines": [p + 1 if p is not None else a + 1, n + 1 if n is not None else b + 1],
                       "confidence": conf, "safe_autofix": safe, "ops": HOST_OPS.get(kind, []), **({"fix": fix} if fix else {}),
                       **extra})

    # page furniture: a repeated opening AND a handle or web address AND a navigation mark, all on the line
    openings = collections.defaultdict(list)
    for i in prose:
        words = plain(lines[i]).split()
        if len(words) >= 3 and min(len(w) for w in words[:2]) >= 2:
            openings[" ".join(words[:2]).lower()].append(i)
    nav_open = set(nav_openings)
    for o, idx in openings.items():
        hits = [i for i in idx if HANDLE_OR_URL.search(plain(lines[i])) and NAV_MARK.search(plain(lines[i]))]
        if len(idx) >= 3 and len(hits) >= 3:
            nav_open.add(o)
            for i in hits:
                add("page_nav", i, i, 0.95, True, {"op": "delete", "reason": "page navigation repeated on every page"},
                    opening=o)
    for i in prose:
        low = lines[i].lower()
        for o in nav_open:
            at = low.find(o)
            if at > 0 and plain(lines[i]).lower().find(o) > 0:
                add("page_nav_attached", i, i, 0.8, False, suggested_drop=lines[i][at:])
    # a handle repeated inside letter-spaced headings; its first appearance stays
    handles = collections.Counter()
    for i in prose:
        for m in re.finditer(r"@((?: ?[^\W_]){3,})", plain(lines[i])):
            if m.end() == len(plain(lines[i])) or " " not in m.group(1).strip():
                handles[m.group(1).replace(" ", "").casefold()] += 1
    first = {}
    for h in (h for h, c in handles.items() if c >= 3):
        pat = re.compile("@ ?" + " ?".join(map(re.escape, h)) + r"(?![^\W_])", re.I)
        for i in prose:
            m = pat.search(lines[i])
            if not m:
                continue
            if h not in first:
                first[h] = i
                continue
            if SPACED.search(lines[i]):
                rest = re.sub(r"\s{2,}", " ", lines[i][:m.start()] + lines[i][m.end():]).strip()
                fix = {"op": "delete", "reason": "handle repeated on every page"} if not rest else \
                    {"op": "replace", "text": rest, "drops": [m.group(0)], "reason": "handle repeated on every page"}
                add("repeated_handle", i, i, 0.95, True, fix)
    # "S t e p 1" and "D a y 2": capital, spaced lower-case letters, a number
    for i in prose:
        if MICRO_SPACED.search(lines[i]):
            new = MICRO_SPACED.sub(lambda m: m.group(1).replace(" ", "") + " " + m.group(2).replace(" ", ""), lines[i])
            add("spaced_label", i, i, 0.97, True, {"op": "replace", "text": new})
    # two or more lines that are each one inline code span (prompts, folder trees) become one fenced block
    code_only = [i for i in prose if CODE_ONLY.fullmatch(lines[i]) and "[image" not in lines[i]]
    runs = []
    for i in code_only:
        if runs and ctx(runs[-1][-1], 1) == i:
            runs[-1].append(i)
        else:
            runs.append([i])
    for r in runs:
        body = [CODE_ONLY.fullmatch(lines[i]).group(1).strip() for i in r]
        if len(r) >= 2 and any(re.search(r"[a-z]", t) for t in body) and not any("```" in t or "~~~" in t for t in body):
            add("code_run", r[0], r[-1], 0.95, True, {"op": "replace", "text": "```\n" + "\n".join(body) + "\n```"})
    # step numbers pulled out of their list: numbers 1..k in order, each standalone or ending its item's line
    view = lambda i: re.sub(r"[`*_]", "", lines[i]).strip()
    item_ok = lambda i: not BLOCK_LINE.match(lines[i]) and not SPACED.search(lines[i]) and not lines[i].lstrip().startswith(("*", "`", "#"))
    marks = []
    for i in prose:
        if re.fullmatch(r"\s*\d{1,2}\s*", lines[i]):
            marks.append((i, int(lines[i]), None))
        elif TRAILING_NUMBER.match(view(i)) and item_ok(i):
            m = TRAILING_NUMBER.match(lines[i].strip())
            if m:
                marks.append((i, int(m.group(2)), m.group(1)))
    used = set()
    for s, (i, v, _) in enumerate(marks):
        if v != 1 or i in used:
            continue
        seq = [marks[s]]
        for m in marks[s + 1:]:
            if m[1] == seq[-1][1] + 1 and m[0] - seq[-1][0] <= 8:
                seq.append(m)
            elif m[1] == 1:
                break
        items, ok, cont = [], True, None
        start = i if seq[0][2] is not None else ctx(i, -1)
        if start is None or (seq[0][2] is None and not item_ok(start)):
            ok = False
        for n, (li, val, pre) in enumerate(seq):
            lo = start if n == 0 else (cont if cont is not None else seq[n - 1][0]) + 1
            body = [j for j in prose if lo <= j < li]
            if pre is not None:
                body.append(li)
            if not body or not all(item_ok(j) for j in body):
                ok = False
                break
            parts = [TRAILING_NUMBER.match(lines[j].strip()).group(1) if j == li else lines[j].strip() for j in body]
            cont = None
            nxt = ctx(li, 1)
            if pre is None and not _terminal(lines[body[-1]]) and nxt is not None and item_ok(nxt) and \
                    not (n + 1 < len(seq) and nxt >= seq[n + 1][0]):
                parts.append(lines[nxt].strip())
                cont = nxt
            items.append(parts)
        if not ok:
            for li, _, _ in seq:
                add("detached_number", li, li, 0.5, False)
            continue
        end = max(seq[-1][0], cont if cont is not None else -1)
        used.update(m[0] for m in seq)
        text_ = "\n".join(f"{n + 1}. " + " ".join(p) for n, p in enumerate(items))
        add("number_list", start, end, 0.9, True, {"op": "number_list", "text": text_})
    for i, v, _ in marks:
        if i not in used and i not in taken:
            add("detached_number", i, i, 0.5, False)
    # a sentence cut by a page break: no ending punctuation, next paragraph starts in lower case
    for i, j in zip(prose, prose[1:]):
        if any(kinds[k] != "prose" for k in range(i, j)) or BLOCK_LINE.match(lines[i]) or BLOCK_LINE.match(lines[j]):
            continue
        a_, b_ = view(i), view(j)
        heading = SPACED.search(lines[i]) or re.fullmatch(r"\s*(\*\*|__).*\1\s*", lines[i])   # a label, not half a sentence
        if a_ and b_ and re.match(r"[a-z]", b_) and not _terminal(lines[i]) and not heading:
            add("split_sentence", i, j, 0.99, True, {"op": "replace", "text": lines[i].rstrip() + " " + lines[j].lstrip()})
    # for the AI: letter-spaced type, code-font labels, odd asterisks, repeated lines
    caps = lambda l: any(re.search(r"[^\W\d_]", m.group(2)) and not any(ch.islower() for ch in m.group(2))
                         for m in CODE_SPAN.finditer(l))
    counts = collections.Counter(lines[i].strip() for i in prose if not PLACEHOLDER.fullmatch(lines[i].strip()))
    for i in prose:
        if SPACED.search(lines[i]):
            add("letter_spaced", i, i, 0.5, False)
        elif caps(lines[i]):
            add("code_label", i, i, 0.6, False)
        elif re.sub(r"^\s*[*] ", "", CODE_SPAN.sub("", lines[i])).count("*") % 2:
            add("odd_asterisks", i, i, 0.6, False)
        elif counts[lines[i].strip()] >= 3:
            add("repeated_line", i, i, 0.6, False)
    issues.sort(key=lambda x: x["lines"][0])
    for n, x in enumerate(issues, 1):
        x["id"] = f"i{n}"
    return issues


def _group(issues, text):
    """Merge issues on neighbouring lines (at most one blank line apart) into blocks, so the AI sees each stretch
    once, with the lines just outside it as context. A block allows every op of the issues in it."""
    lines, blocks = text.split("\n"), []
    for x in issues:
        if blocks and x["lines"][0] <= blocks[-1]["lines"][1] + 2:
            b = blocks[-1]
            b["lines"][1] = max(b["lines"][1], x["lines"][1])
            b["types"] = sorted(set(b["types"]) | {x["type"]})
            b["ops"] = sorted(set(b["ops"]) | set(x["ops"]))
            b["context_lines"][1] = x["context_lines"][1]
            b["flagged"] += list(range(x["lines"][0], x["lines"][1] + 1))
            b["after"] = x["after"]
            if "suggested_drop" in x:
                b.setdefault("suggested_drop", []).append(x["suggested_drop"])
        else:
            blocks.append({"types": [x["type"]], "lines": list(x["lines"]), "before": x["before"][:50],
                           "after": x["after"], "ops": list(x["ops"]), "context_lines": list(x["context_lines"]),
                           "flagged": list(range(x["lines"][0], x["lines"][1] + 1)),
                           "safe_autofix": False, **({"suggested_drop": [x["suggested_drop"]]} if "suggested_drop" in x else {})})
    for n, b in enumerate(blocks, 1):
        b["id"] = f"b{n}"
        b["after"] = b["after"][:50]
        b["text"] = "\n".join(l for l in lines[b["lines"][0] - 1:b["lines"][1]] if l.strip())
    return blocks


def _apply(st, edits, issues=None):
    """Apply a batch of edits bottom-up. With issues, every edit must name issue ids and stay inside their lines
    (plus the nonblank line either side). All or nothing: returns the list of errors, empty on success."""
    errors, spans = [], []
    by_id = {x["id"]: x for x in issues or []}
    for n, e in enumerate(edits):
        try:
            a, b = e["lines"]
            assert isinstance(a, int) and isinstance(b, int) and isinstance(e.get("text", ""), str)
            assert isinstance(e.get("drops") or [], list) and all(isinstance(d, str) for d in e.get("drops") or ())
            assert isinstance(e.get("op"), str) and isinstance(e.get("reason") or "", str)
        except (KeyError, TypeError, ValueError, AssertionError, AttributeError):
            errors.append(f"edit {n}: needs lines [first, last] as numbers, text and drops as strings")
            continue
        if issues is not None:
            ids = e.get("issues") or ([e["issue"]] if e.get("issue") else [])
            refs = [by_id.get(i) if isinstance(i, str) else None for i in ids] if isinstance(ids, list) else [None]
            if not ids or None in refs:
                errors.append(f"edit {n}: unknown or missing issue id {ids}")
                continue
            deletes = e.get("op") == "delete" or e.get("drops")   # deletions stay on flagged lines, never context
            allowed = {ln for x in refs for ln in (x["flagged"] if deletes else
                                                     range(x["context_lines"][0], x["context_lines"][1] + 1))}
            outside = [ln for ln in range(a, b + 1) if ln not in allowed and st["text"].split("\n")[ln - 1:ln] != [""]]
            if outside:   # every nonblank line must sit in a named block (or the line either side of it)
                errors.append(f"edit {n}: lines {a}-{b} are outside its issues' lines (line {outside[0]})")
                continue
            if not all(e.get("op") in x["ops"] or x["safe_autofix"] for x in refs):
                errors.append(f"edit {n}: op {e.get('op')!r} is not allowed for {ids}")
                continue
        spans.append((a, b, n, e))
    spans.sort(key=lambda s: -s[0])
    for (a, b, n, _), (a2, b2, n2, _) in zip(spans, spans[1:]):
        if b2 >= a:
            errors.append(f"edits {n2} and {n} overlap")
    if errors:
        return errors
    work = {"text": st["text"], "lmap": list(st["lmap"]), "ledger": list(st["ledger"]), "audit": list(st["audit"])}
    for a, b, n, e in spans:
        err = _edit(work, a, b, e.get("text", ""), e.get("op"), e.get("drops") or (), e.get("reason"))
        if err:
            errors.append(f"edit {n} (lines {a}-{b}): {err}")
    if not errors:
        st.update(work)
    return errors


def autofix(st, passes=3):
    """Apply every issue analyze marks safe_autofix. Returns how many edits were applied."""
    done = 0
    for _ in range(passes):
        found = analyze(st["text"], st.setdefault("nav_openings", []))
        st["nav_openings"] = sorted(set(st["nav_openings"]) | {x["opening"] for x in found if x["type"] == "page_nav"})
        safe = [x for x in found if x["safe_autofix"]]
        if not safe:
            break
        edits = [{**x["fix"], "lines": x["lines"]} for x in safe]
        errors = _apply(st, edits)
        if errors:   # one bad fix never blocks the rest: apply them one at a time, bottom-up, skipping failures
            for e in sorted(edits, key=lambda e: -e["lines"][0]):
                done += not _apply(st, [e])
            break
        done += len(edits)
    return done


def reconcile(st, export):
    """Check the result against the export with the ledger's deletions cut out of it first, so every deletion
    the check still reports is one nobody logged (unexplained). Cutting before the diff, not subtracting after
    it, keeps a moved heading next to a logged deletion from being misread as fragments. Nothing is weakened:
    each logged deletion must be whole words (else it counts as a partial-word drop), and the image gate runs
    on the full export, so a logged deletion can never hide a lost picture."""
    export = export.replace("\r\n", "\n")
    _, a, apos, ab = _stream(export)
    blank, partial, deleted = [False] * len(export), [], []
    for e in st["ledger"]:
        x0, x1 = e["letters"]
        deleted.append({"reason": e["reason"], "text": _show(a, ab, x0, x1)})
        if not _bounded(a, ab, x0, x1):   # exact positions, no sliding onto a lookalike: a cut into a word fails
            partial.append(deleted[-1]["text"])
        for p in sorted({apos[k] for k in range(x0, x1)}):   # blank the letters only: backticks and other
            m = ENTITY.match(export, p) if export[p] == "&" else None   # Markdown stay, so no code span shifts
            end = m.end() if m else p + 1
            while end < len(export) and unicodedata.category(export[end]).startswith("M"):
                end += 1
            blank[p:end] = [True] * (end - p)
    # each blanked run becomes \x01 per character plus one more: never whitespace (a line never turns blank, so
    # inline code never re-pairs), never a letter, and always at least two symbols wide, so the letters either
    # side can never read as one letter-spaced run ("A B [and] C") in which joining them would pass
    out = []
    for i, ch in enumerate(export):
        out.append("\x01" if blank[i] else ch)
        if blank[i] and (i + 1 == len(export) or not blank[i + 1]):
            out.append("\x01")
    r = check("".join(out), st["text"])
    # A second, alignment-free merge test from the letter map: two letters in one word of the result whose export
    # positions have a real (hard) word break between them are merged words. Blanking cannot move run grouping
    # here, because nothing is re-read. Runs only while the map matches the text (every edit keeps it so).
    _, b, _, bb = _stream(st["text"])
    lm = st["lmap"]
    r["letter_map_in_sync"] = len(lm) == len(b) and all(0 <= x < len(a) and a[x] == c for x, c in zip(lm, b))
    if r["letter_map_in_sync"]:   # out of sync never happens through _edit; if it does, the result cannot validate
        for j in range(1, len(b)):
            e1, e2 = lm[j - 1], lm[j]
            if bb[j] is None and e2 != e1 and (e2 < e1 or any(_resolve(ab[k], bb, j) == "hard" for k in range(e1 + 1, e2 + 1))):
                r["merged_words"].append(_show(b, bb, max(0, j - 12), min(len(b), j + 12)))
    r["images"] = image_gate(export, st["text"])   # belt and braces: blanking never touches image tokens today,
    r["partial_word_drops"] += partial              # so this equals the gate on the blanked text, but it cannot drift
    r["ok"] = not r["added_runs"] and not r["partial_word_drops"] and not r["merged_words"] and r["images"]["ok"]
    r["deleted"] = deleted
    return r, r["drop_spans"]


def _new_state(export):
    text, stats = strip(export)
    st = {"version": __version__, "source_sha256": _sha(export), "stage": "stripped", "stats": stats, "text": text,
          "lmap": [], "ledger": [], "audit": [], "issues": []}
    a, b = _stream(export)[1], _stream(text)[1]
    st["lmap"] = list(range(len(a)))
    if a != b:   # strip dropped letters it may drop (an entity inside code font it unwrapped): trace and log them
        lmap = [None] * len(b)
        for i, j, n in difflib.SequenceMatcher(None, a, b, autojunk=False).get_matching_blocks():
            lmap[j:j + n] = range(i, i + n)
        if None in lmap:
            raise ValueError("strip added letters, which it never should; please report this document")
        for x0, n in _rle(sorted(set(range(len(a))) - set(lmap))):
            st["ledger"].append({"letters": [x0, x0 + n], "reason": "removed by strip (entity in code font)"})
        st["lmap"] = lmap
    return st


def _save_state(path, st):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump({**st, "lmap": _rle(st["lmap"])}, f, ensure_ascii=False)
    os.replace(tmp, path)   # a crash leaves the previous state whole


def _load_state(path):
    with open(path, encoding="utf-8") as f:
        st = json.load(f)
    st["lmap"] = _unrle(st["lmap"])
    return st


def _valid_state(st):
    """A state file is used only if every field has the shape this script writes."""
    try:
        return (isinstance(st, dict) and all(k in st for k in ("stage", "text", "lmap", "ledger", "audit", "source_sha256"))
                and isinstance(st["text"], str) and isinstance(st["audit"], list) and isinstance(st["lmap"], list)
                and all(isinstance(x, int) for x in st["lmap"])
                and isinstance(st.get("nav_openings", []), list) and all(isinstance(o, str) for o in st.get("nav_openings", []))
                and all(isinstance(x["letters"][0], int) and isinstance(x["letters"][1], int) and isinstance(x["reason"], str)
                        for x in st["ledger"]))
    except (KeyError, TypeError, IndexError):
        return False


def _host_issues(st):
    """The AI's issues for the current text, always recomputed, so line numbers never go stale."""
    st["issues"] = _group([x for x in analyze(st["text"], st.get("nav_openings", ())) if not x["safe_autofix"]], st["text"])
    return st["issues"]


def _packet(st):
    """What the AI needs to write edits: rev (edits must quote it, so a batch written for an older text is
    refused), the ops per issue type, and the issue blocks."""
    keep = ("id", "types", "lines", "text", "before", "after", "suggested_drop")
    return {"rev": _sha(st["text"])[:12], "ops_by_type": HOST_OPS,
            "issues": [{k: x[k] for k in keep if k in x} for x in st["issues"]]}


def pipeline(export, state_path, final=False):
    """strip -> autofix -> analyze, saving progress after each stage. Returns the status and what the AI needs:
    needs_host_edits (issues to fix with apply-edits), or with final=True (or no issues left) the check result:
    validated, needs_review (a deletion the ledger does not explain) or failed (the check failed)."""
    export = export.replace("\r\n", "\n")
    try:
        st = _load_state(state_path) if os.path.exists(state_path) else None
        assert st is None or _valid_state(st)
        if st:   # every logged range and mapped letter must point inside this export's letters
            n = len(_stream(export)[1])
            assert all(0 <= e["letters"][0] < e["letters"][1] <= n for e in st["ledger"])
            assert all(0 <= x < n for x in st["lmap"])
    except (ValueError, KeyError, TypeError, AttributeError, AssertionError):   # damaged: start again from the export
        st = None
    if not st or st.get("source_sha256") != _sha(export) or st.get("version") != __version__:
        try:
            st = _new_state(export)
        except ValueError as err:
            return {"version": __version__, "status": "failed", "error": str(err)}
        _save_state(state_path, st)
    if st["stage"] == "stripped":
        st["autofixed"] = autofix(st)
        st["stage"] = "autofixed"
        _save_state(state_path, st)
    _host_issues(st)
    out = {"version": __version__, "source_sha256": st["source_sha256"],
           "tokens": {"export": len(export) // 4, "now": len(st["text"]) // 4}, "autofixed": st.get("autofixed", 0),
           "ledger": dict(collections.Counter(e["reason"] for e in st["ledger"]))}
    if st["issues"] and not final:
        st["status"] = "needs_host_edits"
        _save_state(state_path, st)
        return {**out, "status": "needs_host_edits", **_packet(st)}
    r, unexplained = reconcile(st, export)
    st["status"] = "failed" if not r["ok"] else "needs_review" if unexplained or not r["letter_map_in_sync"] else "validated"
    st["clean_sha256"] = _sha(st["text"]) if st["status"] == "validated" else None
    _save_state(state_path, st)
    keep = ("added_runs", "partial_word_drops", "merged_words", "moved_runs", "split_words", "images")
    return {**out, "status": st["status"], "clean_sha256": st["clean_sha256"], "left_for_review": len(st["issues"]),
            "check": {k: r[k] for k in keep}, "unexplained_drops": [d["text"] for d in unexplained],
            "deleted": r["deleted"]}


# ---------------------------------------------------------------- selftest

def selftest():
    src = ("Joe&nbsp;\n\n\ufffd\ufffd **C R A W L I N G**&nbsp;\n\n![][image1]Fathom \\# 1 T O S T A R T&nbsp;   \n\n\n\n"
           "Use \\[ADMIN\\] today. 1\n\n2\n\nW H Y\n\nCon*tract **bold** text\n\n"
           "You're here: a \u2022 @x\n\nYou're here: b \u2022 @x\n\nYou're here: c \u2022 @x\n\n"
           "**D a y 1**\n\nPaste the prompt\n\nsomewhere else.\n\n"
           "`C O N T E N T` then `npm install`\n\n`3`\n\n"
           "[image1]: <data:image/png;base64,iVBORw0KGgo=>\n")
    out, st = strip(src)
    for bad in ("&nbsp;", "\ufffd", "base64", "![]", "\\["):
        assert bad not in out, bad
    assert "[image 1]\nFathom # 1" in out and "[ADMIN]" in out and "\n\n\n" not in out, out
    assert "\n**C R A W L I N G**\n" in out, "broken chars at line start go without leaving a leading space"
    assert "Contract **bold** text" in out, "stray OCR asterisk out, real bold kept"
    assert st["image_definitions"] == 1 and st["image_refs"] == 1 and st["html_entities"] == 3 and st["broken_chars"] == 2, st
    assert st["ocr_asterisks"] == 1, st
    assert st["code_spans_unwrapped"] == 2 and "`npm install`" in out and out.count("`") == 2, st
    wl = worklist(out)
    assert len(wl["letter_spaced"]) == 5 and len(wl["detached_numbers"]) == 3, wl
    assert [len(g["lines"]) for g in wl["repeated_openings"]] == [3], wl["repeated_openings"]
    assert len(wl["split_sentences"]) == 1 and "somewhere" in wl["split_sentences"][0]["text"], wl["split_sentences"]
    assert len(wl["image_lines"]) == 1, wl["image_lines"]

    # GMC-004: real emphasis, math and globs survive; only letter-letter OCR noise goes
    for keep in ("2*3 = 6", "**Fathom**B tier", "B**old** move", "*a* short word", "file*.md", "5 * 3", "Use **bold** and *italic*."):
        assert strip(keep)[0].strip() == keep, keep
    assert strip("Con*tract with the Cli**ent")[0].strip() == "Contract with the Client"
    # GMC-005, 015, 016, 026: fenced code is untouched, including nested, mixed, quoted and listed fences
    for code in ("```js\nconst x = `FOO`;  // a  b &nbsp;\n```",
                 "````md\n```\nx  y &nbsp; ![](data:image/png;base64,AAAA)\n```\n````",
                 "```\n~~~\na  b Con*tract\n```",
                 "~~~\n```\n[image1]: <data:image/png;base64,AAAA>\n~~~",
                 "> ```js\n> const s = \"a  b\";\n> ```",
                 "- ```\n  a  b &nbsp;\n  ```"):
        assert strip("Intro\n\n" + code + "\n\nOutro")[0] == "Intro\n\n" + code + "\n\nOutro\n", code
    assert strip("```\nopen  fence never closed")[0] == "```\nopen  fence never closed\n"
    assert _line_kinds(["> ```", "> code", "after the quote"]) == ["fence", "code", "prose"], "a fence ends with its quote"
    # GMC-031: a fence inside a list item ends when the list item does
    assert _line_kinds(["- ```", "  code", "", "Outside"]) == ["fence", "code", "code", "prose"]
    assert strip("- ```\n  code  x\n\nOutside&nbsp;")[0] == "- ```\n  code  x\n\nOutside\n"
    # GMC-017, 023: inline code is protected from every prose rule, including image rules and double backticks
    for keep in ("Run `a*b` then `x  y` and `a&nbsp;b` now", "Code `![](data:image/png;base64,AAAA)` here", "Say ``a`b*c`` twice"):
        assert strip(keep)[0].strip() == keep, keep
    # GMC-024: a document containing the mask characters, raw or entity-encoded, neither crashes nor swaps text
    o = strip("`x` and &#57344;0&#57345; and \ue0000\ue001")[0]
    assert o.count("`x`") == 1 and o.count("\ue000") == 2, repr(o)
    # GMC-006: a broken char mid-line keeps the word space
    assert strip("hello\ufffd world")[0] == "hello world\n"
    # GMC-007: escapes that stop a line becoming a list, heading or quote stay escaped
    for keep in ("1\\. not a list", "1\\) not a list", "> \\# not a heading", "- \\# not a heading", "\\> not a quote",
                 "# \\#Tag stays escaped", "### \\#Tag stays escaped"):
        assert strip(keep)[0].strip() == keep, keep
    assert strip("mid \\# and \\[x\\]")[0].strip() == "mid # and [x]"
    assert strip("# heading \\# mid-line")[0].strip() == "# heading # mid-line"
    # GMC-008: a normal link definition named like an image survives
    link = "[Manual][image1]\n\n[image1]: https://example.com/manual"
    assert strip(link)[0].strip() == link
    # inline data image and zero-width chars
    o, s2 = strip("See ![](data:image/png;base64,AAAA) here a\u200bb")
    assert o.strip() == "See\n[image 1]\nhere ab" and s2["inline_images"] == 1, (o, s2)
    # worklist: repeated lines, odd asterisks, all-caps code spans, split sentences; GMC-018 lists never split
    w2 = worklist("Same line\n\nSame line\n\nSame line\n\nMatch file*.md.\n\n`CONTENT` Made\n\n`Paste the prompt`\n\n`somewhere else.`\n")
    assert w2["repeated_lines"] == [{"text": "Same line", "count": 3}], w2["repeated_lines"]
    assert len(w2["odd_asterisks"]) == 1 and len(w2["code_spans"]) == 1, w2
    assert len(w2["split_sentences"]) == 1, w2["split_sentences"]
    assert worklist("* Buy flour\n\n* bake bread\n\n1. first\n\n2. second\n")["split_sentences"] == []
    assert worklist("Paste it\n\n```\ncode\n```\n\nsomewhere\n")["split_sentences"] == [], "never pair across a code block"
    assert worklist("Run `a*b` now")["odd_asterisks"] == [], "asterisks inside inline code are not stray"

    # check: strip's own output and a pure rebuild pass, invention fails, deletion is reported, a move is a move
    assert check(src, out)["ok"], check(src, out)
    good = out.replace("**C R A W L I N G**", "## Crawling")
    assert check(src, good)["ok"], check(src, good)
    r = check(src, good.replace("today.", "today, it is free."))
    assert not r["ok"] and "it is free" in r["added_runs"], r
    r = check(src, good.replace("Use [ADMIN] today.", ""))
    assert r["ok"] and "use admin today" in r["inline_drops"], r
    r = check(src, good.replace("Use [ADMIN] today.", "") + "\nUse [ADMIN] today.\n")
    assert r["ok"] and "use admin today" in r["moved_runs"], r
    # GMC-001: short edits, short deleted words, non-ASCII
    assert not check("The plan is paid today.", "The plan is unpaid today.")["ok"]
    assert not check("The plan is unpaid today.", "The plan is paid today.")["ok"], "cutting inside a word fails"
    assert not check("The cat sat.", "The cut sat.")["ok"]
    r = check("This is not free.", "This is free.")
    assert r["ok"] and r["inline_drops"] == ["not"], r
    assert not check("Hello.", "Hello. \u041f\u0440\u0438\u0432\u0435\u0442")["ok"], "non-ASCII invention fails"
    assert not check("Price 100.", "Price 1000.")["ok"], "an added digit fails"
    # GMC-012, 020, 029: merging ordinary words fails; only the inside of letter-spaced type may rejoin
    r = check("go now here", "go nowhere")
    assert not r["ok"] and r["merged_words"], r
    assert not check("now here", "nowhere")["ok"]
    assert not check("go H O M E", "gohome")["ok"], "a spaced run's outer boundary is a real boundary"
    assert not check("GO H O M E", "GOHOME")["ok"], "an all-caps word is not a glued capital"
    assert not check("MetricoolB\nO N U S", "Metricool Bonus")["ok"], "the glue exception never crosses a line"
    assert not check("a, b, c", "abc")["ok"], "comma-separated letters are not letter-spacing"
    assert check("S T A R T W H E R E Y O U A R E", "Start where you are")["ok"]
    assert check("P A R T 1 \u00b7 S T A R T", "Part 1 \u00b7 Start")["ok"]
    # OCR chunks two letters of display type together; rejoining the run is still not a merge
    assert check("C O P Y - P A S TE S T A R TE R P R OM P T", "Copy-paste starter prompt")["ok"]
    assert check("U S E C L A U D E T O WR ITE Y O U R S E Q U E N C E S",
                 "Use Claude to write your sequences")["ok"], "three-letter chunks happen too"
    assert check("C O P Y - P A S TE: N O TE B O O K L M", "Copy-paste: NotebookLM")["ok"], \
        "punctuation can end a run on its chunk"
    assert not check("GO TO H O M E", "GOTOHOME")["ok"], "a chunk outside the run keeps its hard boundary"
    assert not check("go to H O M E", "gotohome")["ok"], "lower-case words are not OCR chunks"
    assert not check("H O M E PA GE", "HOMEPAGE")["ok"], "a run never continues past its last single letter"
    r = check("MetricoolB O N U S", "Metricool Bonus")
    assert r["ok"] and r["split_words"], r
    assert not check("MetricoolB O N U S", "MetricoolBonus")["ok"], "glue without the matching split is a merge"
    assert not check("ChatGPT P R O", "ChatGPTPRO")["ok"], "a real mixed-case name is not glued text"
    # GMC-013: a letter shuffled inside a word is not a move
    assert not check("form", "from")["ok"]
    assert not check("Fill the form.", "Fill the from.")["ok"]
    # GMC-021: a merge inside relocated text fails
    assert not check("now here\n" + "x" * 40, "x" * 40 + "\nnowhere")["ok"]
    # GMC-030: with two identical candidates, the one whose word boundaries agree is the move
    assert check("now here\n" + "x" * 40 + "\nnowhere\n" + "y" * 40, "x" * 40 + "\n" + "y" * 40 + "\nnowhere")["ok"]
    # GMC-022: removing emphasis inside a word is formatting, not a merge
    assert check("un**paid**", "unpaid")["ok"] and check("**Fathom**B", "FathomB")["ok"]
    # GMC-023: inline code is compared exactly as written
    r = check("See `&copy;` here.", "See `\u00a9` here.")
    assert "copy" in r["inline_drops"] + r["dropped_lines"], r
    # GMC-028: an entity that decodes to a line break neither hides nor invents text
    assert check("alpha&#10;bravo", strip("alpha&#10;bravo")[0])["ok"]
    r = check("alpha&#10;bravo", "alpha")
    assert "bravo" in r["inline_drops"] + r["dropped_lines"], r
    # GMC-014, 025, 032: lowercase expansion, accents, entity-encoded marks, Hangul jamo, final sigma
    assert check("\u0130stanbul", "\u0130stanbul")["ok"]
    assert check("\u0130", "")["dropped_lines"] and check("\u0130 x", "x")["inline_drops"], "U+0130 deletion reported, no crash"
    assert not check("cafe", "cafe\u0301")["ok"], "an added accent is a change"
    assert check("caf\u00e9", "cafe\u0301")["ok"], "composed and decomposed forms are the same word"
    assert check("cafe&#769; au lait", strip("cafe&#769; au lait")[0])["ok"], "strip's entity decoding passes check"
    assert check("\u1100\u1161", "\uac00")["ok"], "decomposed Hangul equals the composed syllable"
    assert check("\u039b\u039f\u0393\u039f\u03a3", "\u03bb\u03bf\u03b3\u03bf\u03c2")["ok"], "Greek case change with final sigma"
    # GMC-019: wrapping unchanged text in a language-tagged fence adds no wording
    assert check("hello world", "```text\nhello world\n```")["ok"]
    # GMC-027: a short heading lifted out of page furniture pairs as a move
    r = check("This is TIPS\nFooter text\nuseful.", "This is useful.\n\n## TIPS")
    assert r["ok"] and "tips" in r["moved_runs"], r
    # GMC-002: pairing never rejoins what's left of a deletion; a short run inside a sentence can't hide in one
    _, a, _, ab = _stream("alpha bravo charlie")
    ct, b, bp, bb = _stream("bravo\nalpha charlie")
    moved, unmatched, rest = _pair_moves(a, ab, b, bb, [(0, 17)], [(0, 5), (5, 17)], ct, bp)
    assert moved == [(0, 5, 5)] and unmatched == [(5, 17)] and rest == [(0, 5), (10, 17)], (moved, unmatched, rest)
    ct2, b2, bp2, bb2 = _stream("x bravo y")
    assert _pair_moves(a, ab, b2, bb2, [(0, 17)], [(1, 6)], ct2, bp2)[0] == [], "a short run mid-sentence can't hide in a deletion"
    # GMC-034: a data image written across lines neither crashes check nor shifts lines
    multi = "See ![](" + chr(10) + "data:image/png;base64,AAAA" + chr(10) + ") here"
    assert check(multi, multi)["ok"] and check(multi, strip(multi)[0])["ok"]
    # GMC-003: decoded entities are the source's wording
    assert check("&#119;&#111;&#114;&#100; and caf&eacute;", "word and caf\u00e9")["ok"]
    # CLI exit codes
    with tempfile.TemporaryDirectory() as d:
        sp, gp, bp_ = (os.path.join(d, n) for n in ("s.md", "g.md", "b.md"))
        for p, t in ((sp, "This is free."), (gp, "## This is free."), (bp_, "This is not free.")):
            with open(p, "w", encoding="utf-8") as f:
                f.write(t)
        env = {**os.environ, "PYTHONIOENCODING": "utf-8"}   # explicit, so the child never inherits a cp1252 console
        run = lambda c: subprocess.run([sys.executable, os.path.abspath(__file__), "check", sp, c], env=env,
                                       capture_output=True, text=True, encoding="utf-8", timeout=60).returncode
        assert run(gp) == 0 and run(bp_) == 1, (run(gp), run(bp_))
    print("selftest ok")


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # Windows consoles default to cp1252 and crash on emoji
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", action="version", version=__version__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("strip"); p.add_argument("input"); p.add_argument("-o", "--output", required=True)
    c = sub.add_parser("check"); c.add_argument("source"); c.add_argument("cleaned")
    sub.add_parser("selftest")
    z = sub.add_parser("analyze"); z.add_argument("input")
    q = sub.add_parser("pipeline"); q.add_argument("export"); q.add_argument("--state", required=True)
    q.add_argument("-o", "--output"); q.add_argument("--final", action="store_true")
    e = sub.add_parser("apply-edits"); e.add_argument("edits"); e.add_argument("--state", required=True)
    a = ap.parse_args()
    if a.cmd == "selftest":
        return selftest()
    if a.cmd == "analyze":
        issues = analyze(open(a.input, encoding="utf-8").read().replace("\r\n", "\n"))
        return print(json.dumps({"version": __version__, "issues": issues}, ensure_ascii=False, indent=1))
    if a.cmd == "pipeline":
        r = pipeline(open(a.export, encoding="utf-8").read(), a.state, a.final)
        if r["status"] == "validated" and a.output:
            open(a.output, "w", encoding="utf-8", newline="\n").write(_load_state(a.state)["text"])
        print(json.dumps(r, ensure_ascii=False, separators=(",", ":")))   # compact: the AI reads it, tokens count
        sys.exit(1 if r["status"] in ("failed", "needs_review") else 0)
    if a.cmd == "apply-edits":
        try:
            st = _load_state(a.state)
            edits = json.load(open(a.edits, encoding="utf-8"))
            if not _valid_state(st):
                raise ValueError("the state file is damaged; run pipeline again to rebuild it")
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as err:
            print(json.dumps({"version": __version__, "applied": False, "errors": [f"cannot read: {err}"]}))
            sys.exit(1)
        rev = _sha(st["text"])[:12]
        if not isinstance(edits, dict) or edits.get("rev") != rev:
            errors = [f"stale or missing rev: these edits were written for another version of the text; "
                      f"use the issues from the newest pipeline or apply-edits output (rev {rev})"]
        else:
            batch = edits.get("edits") or []
            ok_shape = isinstance(batch, list) and all(isinstance(e, dict) for e in batch)
            errors = _apply(st, batch, _host_issues(st)) if ok_shape else ["edits must be a list of objects"]
        if not errors:
            st["stage"] = "edited"
            _host_issues(st)   # the next batch is checked against the new line numbers
            _save_state(a.state, st)
        print(json.dumps({"version": __version__, "applied": not errors, "errors": errors, **_packet(st)},
                         ensure_ascii=False, separators=(",", ":")))
        sys.exit(1 if errors else 0)
    if a.cmd == "strip":
        out, st = strip(open(a.input, encoding="utf-8").read())
        open(a.output, "w", encoding="utf-8", newline="\n").write(out)
        print(json.dumps({"version": __version__, "stats": st, "worklist": worklist(out)}, ensure_ascii=False, indent=1))
    else:
        r = check(open(a.source, encoding="utf-8").read(), open(a.cleaned, encoding="utf-8").read())
        print(json.dumps(r, ensure_ascii=False, indent=1))
        sys.exit(0 if r["ok"] else 1)


if __name__ == "__main__":
    main()
