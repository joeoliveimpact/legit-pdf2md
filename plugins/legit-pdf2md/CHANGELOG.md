# Changelog

## 0.1.0 - 2026-09-22

First public release.

- Converts a Drive PDF (scans included, via Google's own OCR) or a Google Doc to Markdown and saves it back to the same folder.
- Strips what a Docs export leaves behind: base64 image blocks, HTML entities, Google's backslash escapes, code-font backticks around letter-spaced text, stray OCR asterisks. Fenced code blocks and inline code are never touched.
- Rebuilds structure by reading, then runs a wording check that fails if anything was invented, cut or merged.
- Finds your Composio Google Drive connection over MCP or the CLI, and tells you plainly when there is neither.
