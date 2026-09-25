# Changelog

## 0.2.0 - 2026-09-25

**A script does everything that is certain, the AI decides only what needs reading, and nothing is saved until a check proves no word or picture was lost.** Built from Joe's ChatGPT run of 0.1.3 (it worked, slowly) and its 87-section report, then hardened by independent checker rounds and live runs in Claude and ChatGPT.

- **One pipeline instead of hand cleanup.** `pipeline` strips the junk, makes every fix that cannot change a word (page navigation, repeated handles, `S t e p 1`, code-font runs, sentences a page break cut), and hands the AI a small packet of only the lines that need judgment, each line numbered. On a real 12-page guide: 43 blocks, about 3,700 tokens, instead of the whole document.
- **The AI edits by line, and the script refuses any edit that changes a word.** `apply-edits` takes a batch of edits (replace, delete, rebuild a numbered list, move a heading out of a sentence), all or nothing, tied to the packet it was written for.
- **Every deletion is logged with its reason.** The final check fails if anything was invented or merged or a picture went missing, and anything removed without a logged reason blocks the save.
- **Numbered lists are confirmed by the AI, not rebuilt blindly.** The script proposes each list; real numbers ("score: 1 / 2 / 3"), numbers before their items and broken runs can make a wrong one, so the AI checks it against the text.
- **The saved file is proven.** It is downloaded again and matched, fingerprint for fingerprint, against the text that passed the check. Only then is the temporary Doc trashed, and only the one this run made.
- **Runs survive Composio resetting its sandbox,** which happens between calls without warning. The temporary Doc's id and the edits live in the chat, and every step rebuilds from them, so a reset never makes a second copy or a second save. The temporary Doc is stamped with the file and version it came from: a lost id is found again, another file's copy is never taken, and on the connector a PDF edited mid-run is never cleaned from its old copy.
- **Re-runs reuse.** The clean file carries a reuse key (the source's id and last-modified time). Run it again on an unchanged file and you get the clean file back with no work done; if the file changed, the new one is `(2)`. Nothing is ever overwritten.
- **Works through the connector (Claude and ChatGPT) and the CLI (including Windows with Composio in WSL),** with a guide for each in `references/`. Proven end to end on both, and in ChatGPT.
- **An expired download link stops the run** instead of being cleaned as if it were the document.
- **A PDF over 80 pages stops before anything is copied.** Google converts only the first 80 pages and says nothing; the skill counts the pages first and asks for the PDF in parts.
- **Words run together across table cells are caught.** Google's export glues neighbouring cells (`ClaudeChat only`, `Metricool20 posts`), and a letters-only check cannot see a missing space. They now go to the AI as `glued_words`, which may only add the space back. Real names written that way (`YouTube`, `HubSpot`) are left alone. Found in the ChatGPT integration test.
- **Plain requests start it.** "Turn this PDF into markdown" with a Drive link picks this skill in Claude without naming it (tested headless). In ChatGPT, mention `@legit-pdf2md`: there the plain sentence lets ChatGPT use its own PDF tools.

## 0.1.4 - 2026-09-22

**No picture goes missing without the check saying so.** Found by running 0.1.3 in ChatGPT on a real 12-page guide: 5 of its 9 pictures vanished from the clean file and the wording check still passed.

- **Pictures inside code formatting are kept.** Google's export sometimes wraps pictures in code formatting (`` `![][image6]![][image7]` ``). The cleaner used to leave those alone and delete the picture data, so the pictures disappeared. Code formatting that holds nothing but pictures now becomes placeholders. On the same guide: 9 of 9 pictures kept, where 0.1.3 kept 4.
- **Each `[image N]` gets its own line**, so two pictures side by side are two placeholders, not one line. In list items, headings, quotes and tables they stay where they were. The line break is a single one, so the page renders the same, and an indented line keeps its indent.
- **The check now counts pictures.** It reads them straight from the export, separately from the cleaner, and fails (`images.ok: false`, exit 1) if one is missing, invented or out of order. A picture the export put inside code next to text is listed under `kept_in_code` for the report.
- **Every deletion the check reports comes with its position** (`drop_spans`): the letter range and the character range in the export (line breaks counted as one), with the deleted words in full.
- **`.pdf` is removed from a PDF's name only.** The clean file of `Guide.pdf` is `Guide - clean.md` (a 0.1.3 run in ChatGPT saved `Guide.pdf - clean.md`), and a dated title like `Notes 09.11.26` keeps every part.
- **The script has a version.** `clean_gdoc_md.py --version` prints it, and every JSON result carries it.
- **Tests run on every change.** A fixture suite (`tests/run_fixtures.py`, standard library only) and the selftest run on GitHub for every pull request, including a check that the version matches in all 7 places it is written.

## 0.1.3 - 2026-09-22

**The cleanup now always runs in Composio.** Every path (Claude chat, Cowork, Claude Code, ChatGPT; the MCP connector or the CLI) runs the script in Composio's remote workbench. Nothing runs on your computer, so no Python and no coding setup are needed anywhere, and the Windows "Python was not found" problem is gone.

- **Each workbench step is self-contained.** On the CLI every workbench call is a fresh sandbox, so files do not carry over. Steps 3 and 5 now fetch the export and the script themselves, and Step 5 passes the rebuilt text in.
- **Local Python is only used for a file you exported by hand**, which the workbench cannot see.
- Proven end to end through the CLI on a real 12-page PDF: 19,354 tokens in, 3,903 out after strip; the wording check passed on the rebuild and failed, as it should, on a copy with one invented word.

## 0.1.2 - 2026-09-22

- **Windows: use `py -3`.** On Windows, `python` and `python3` are often Microsoft Store shortcuts that print "Python was not found" and run nothing. SKILL.md and the README now say to use the `py` launcher there, and what that message means when it appears.
- **The tools table and the known limits moved to `references/tools-and-limits.md`.** SKILL.md is read in full every time the skill runs; these two sections are only needed when a call fails validation or the wording check reports something unexpected. SKILL.md points to the file and says when to open it.

Six more from a cold read of Steps 0 and 3 under four setups (Windows with the CLI in WSL, the MCP connector, the chat app, no Composio at all):

- **Windows with the CLI in WSL now works past Step 0.** The skill showed the WSL wrapper for `whoami` only. It now says every composio command runs that way, with a quoting form tested on a live CLI, and that the export downloads on the Windows side where `py -3` can read it.
- **The connector path checks Drive is `ACTIVE` before Step 1**, the same as the CLI path already did, so a dead connection fails at the check and not four steps in.
- **`--account` says where its value comes from**: the `word_id` in `connections list`, or an alias.
- **The script path fallback no longer doubles a folder.** "The base directory this skill was loaded from" already ends in `skills/legit-pdf2md`; the skill now names `scripts/clean_gdoc_md.py` inside it.
- **No more hand-cleaning fallback.** The last-resort option said to clean the export in chat, which contradicted the rule that the script and its check are what keep your wording intact. With nowhere to run the script, the skill now stops and says so.
- **A hand-exported `.md` skips straight to Step 3** and the clean file is saved beside it, instead of the skill hunting for a Drive connection it does not need. The workbench path now says how to run the script there and where to keep the files between steps.

## 0.1.1 - 2026-09-22

Five fixes found by running v0.1.0 end to end on a second machine, against a real 12-page PDF.

- **The script is now called by its installed path.** Steps 3 and 5 said `python scripts/clean_gdoc_md.py`, which does not exist from the working directory of an installed plugin. They now use `${CLAUDE_PLUGIN_ROOT}`, with a fallback and a note that cleaning by hand is never the answer.
- **Step 1 now asks Drive for `parents`.** `GOOGLEDRIVE_GET_FILE_METADATA` returns `kind, id, name, mimeType` only unless `fields` is passed, so the parent folder came back missing and the clean file could not be saved beside its source.
- **The commands say `python3`.** Stock macOS has no `python` on PATH at all, so the first command in the skill could fail before anything ran. SKILL.md and the README now use `python3` and name the Windows spelling.
- **A heading whose own text starts with a hash keeps its escape.** `# \#Tag` used to unescape to the doubled marker `# # Tag`, which reads as junk the cleaner missed. Escapes at a heading's start are now protected the same way they already were at a line's start; mid-line escapes are untouched.
- **The wording check no longer rejects correctly rejoined headings.** OCR chunks two or three letters of display type together (`C O P Y - P A S TE`, `T O WR ITE`). The letter-spaced exemption only recognised runs of single characters, so rejoining such a heading was reported as a merge: 23 of them on a 12-page guide, against a gate that says merges must be empty. Runs now allow those chunks while still starting on a single character and staying mostly single characters, so `GO H O M E` and `H O M E PA GE` remain merges. `strip` output is byte-identical; only `check` changed.

Five more from a second run, this time through the Composio MCP connector (the path the README teaches), end to end on a 12-page guide: 19,419 tokens in, 3,936 out, wording check passed.

- **Connector tools go through an executor.** The connector exposes `COMPOSIO_MULTI_EXECUTE_TOOL`, not the Drive tools by name. Step 0 now says to pass each slug through it, or through `run_composio_tool` in the workbench.
- **The chat app runs the cleaner from this repo.** Steps 3 and 5 fetch the script from the public repo into the Composio workbench, so no local Python and no `${CLAUDE_PLUGIN_ROOT}` are needed there. Proven on Python 3.13 in the sandbox.
- **Composio's own PDF plan is overruled.** Its search tool suggests `pdfplumber`, which has no OCR and would return a scanned PDF empty. The skill now says to follow its own steps.
- **The connector's default account is the starting point.** The connector and the CLI can list different accounts for the same toolkit; the connector marks one `is_default`.
- **Step 5 says when a failure is expected.** `check` on raw Step 3 output can flag a word glued to letter-spaced type until Step 4 splits it.

## 0.1.0 - 2026-09-22

First public release.

- Converts a Drive PDF (scans included, via Google's own OCR) or a Google Doc to Markdown and saves it back to the same folder.
- Strips what a Docs export leaves behind: base64 image blocks, HTML entities, Google's backslash escapes, code-font backticks around letter-spaced text, stray OCR asterisks. Fenced code blocks and inline code are never touched.
- Rebuilds structure by reading, then runs a wording check that fails if anything was invented, cut or merged.
- Finds your Composio Google Drive connection over MCP or the CLI, and tells you plainly when there is neither.
