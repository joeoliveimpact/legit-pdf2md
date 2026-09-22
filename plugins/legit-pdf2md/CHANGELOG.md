# Changelog

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
