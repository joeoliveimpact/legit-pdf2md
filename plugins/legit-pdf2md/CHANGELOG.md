# Changelog

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
