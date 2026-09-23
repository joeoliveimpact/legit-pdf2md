# Tools reference and known limits

Read this when a Composio call fails validation, when you need a tool's name for a step, or when the pipeline reports something `SKILL.md` does not explain.

## Tools reference

| Step | Composio tool | Note |
|---|---|---|
| Find | `GOOGLEDRIVE_FIND_FILE`, `GOOGLEDRIVE_GET_FILE_METADATA` | `fileId`, plus `fields` for `parents` |
| Wrong account? | `GOOGLEDRIVE_GET_ABOUT` | run on any 404 |
| PDF to Doc | `GOOGLEDRIVE_COPY_FILE_ADVANCED` | `fileId`, `mimeType`, `ocrLanguage`, `parents: ["root"]` |
| Export | `GOOGLEDRIVE_EXPORT_GOOGLE_WORKSPACE_FILE` | `fileId`, `mimeType: text/markdown`; link at `data.file.s3url`, expires in 1 hour |
| Save | `GOOGLEDRIVE_CREATE_FILE_FROM_TEXT` | `file_name`, `text_content`, `mime_type`, `parent_id` |
| Read back | `GOOGLEDRIVE_DOWNLOAD_FILE` | `fileId`; link at `data.downloaded_file_content.s3url` |
| Clean up temp Doc | `GOOGLEDRIVE_TRASH_FILE` | `file_id`, not `fileId` |
| Run a tool via the connector | `COMPOSIO_MULTI_EXECUTE_TOOL` | `tools: [{tool_slug, arguments}]`, plus `account` |
| Run the script | `COMPOSIO_REMOTE_WORKBENCH` | `code_to_execute` |

Parameter casing differs between these tools; when a call fails validation, read that tool's schema rather than assuming (`--get-schema` on the CLI). Every `GOOGLEDRIVE_*` tool works unchanged through the connector and through the CLI.

## The script's commands

`clean_gdoc_md.py pipeline EXPORT --state STATE [--final] [-o OUT]`, `apply-edits EDITS --state STATE`, `--version`, `selftest`. The older `strip` and `check` still work for flows written for 0.1.x; do not validate a pipeline result with standalone `check` (a correctly moved heading can fail it). Exit code 1 means `failed` or `needs_review` (pipeline) or a refused batch (apply-edits).

## Known limits

**Wording check**
- It compares letters and digits, not punctuation. That is why fenced code is never touched; a changed symbol elsewhere is not caught.
- Letter-spaced type is recognised by pattern: three or more single characters separated by plain spaces, with two- or three-letter OCR chunks allowed inside the run. A real two- or three-letter capital word right after display type can be absorbed into it without the check objecting. Leading words are never absorbed.
- Indented code blocks (four spaces, no fence) are not detected. Google's export uses fences, so this rarely matters.
- An entity-encoded combining mark (`&#769;`) or `&amp;ample` can give a false `needs_review` or `failed`. It fails safe: nothing is saved.
- Link addresses do not survive Google's export; only the link text does.

**Edits and the drop ledger**
- Every deletion is logged and shown in `deleted`, so nothing disappears silently, but a logged deletion is only as right as its reason. Read `deleted` before reporting.
- A block allows every op of every issue in it. When a list merges into a letter-spaced block, its item lines accept `delete`, `drops` and a heading moved across the list. All of it is logged (`deleted`, `moved_runs`), never silent.
- `rev` guards against stale batches, not against a batch copied onto a new rev; the scope and letter checks still apply to it.
- A `drops` entry matches its first occurrence on the lines; one that lands inside a word fails safe (`partial_word_drops`).
- Autofix can join lines inside a multi-line inline code span (letters unchanged). Dropping every letter of an inline code span leaves empty backticks.
- `kept_in_code` (informational) can differ between runs on the same export; the image verdict never does.

**Numbered lists** (the AI confirms them; autofix never builds one)
- A suggested list can be wrong while every letter stays in order: real trailing numbers read as steps (`final score: 1 / 2 / 3`), numbers placed before their items (shifts every item by one), a broken run (1, 1, 2) merging the next line into item 1. The check passes all of these, which is why SKILL.md says to check each suggestion against the text.
- An AI can still move a real trailing number (`Chapter 3. 4`) into list position.

**Drive**
- Composio can replace its workbench sandbox between any two calls, with `/mnt/files` empty. A run survives it only through what is kept in the chat: the temporary Doc id and the edit batches. If both the sandbox and that id are lost, the temporary Doc stays in My Drive and the user is told its name.
- Two runs on the same source file at the same moment in one sandbox share one journal. Run one at a time per file.
- The same Google Doc exports byte for byte the same every time, but two OCR copies of the same PDF can export slightly differently. So a re-run on an unchanged PDF can give a slightly different clean file; a byte-identical one already in the folder is reused, never saved twice.
- On the CLI, the temporary Doc's id lives only in the conversation. If it is lost, the Doc is left in My Drive and the user is told its name.
- A save whose read-back does not match leaves that file in Drive; the report names it.
