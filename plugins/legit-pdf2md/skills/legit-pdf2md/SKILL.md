---
name: legit-pdf2md
description: Turn a Google Doc, or a PDF stored in Google Drive (including scanned PDFs), into clean Markdown and save it back to the same Drive folder, using the Composio Google Drive connection. Use this whenever someone wants a PDF or Google Doc converted to Markdown for Claude, wants to stop PDFs eating their tokens or filling the context window, has a Markdown file exported from Google Docs full of junk (&nbsp;, base64 image blocks, letter-spaced text like "S T A R T", stray step numbers or asterisks), or asks to "clean up", "fix" or "make readable" a Docs export, even if they never say the word cleanup.
---

# Google Doc or Drive PDF to clean Markdown

## Output contract

Done means all four of these:
1. A new file named `<original title> - clean.md` in the **same Drive folder** as the source.
2. The wording is the source's wording. Nothing reworded, summarized, corrected or added.
3. The wording check (Step 5) passed.
4. A short report to the user: tokens before and after, what was fixed, what could not be recovered, the file link, and "start a new chat and add this file."

If this skill is re-invoked partway through, check which of these already exist and continue from there.

## Why this matters

Google's own Markdown export is the cheapest way to get text out of a PDF, and the only one here that reads scanned pages. But the file it produces is mostly junk. On a real 12-page guide the export was about 19,000 tokens and 78% of it was images stored as base64 text. After cleanup it was about 3,500 tokens. The person using this skill is trying to keep Claude from forgetting their documents, so the cleanup must not quietly change what the document says.

## Step 0: Find the Composio connection

Every Drive step below runs through Composio, which reaches this skill two ways. **Find which one is live before doing anything else.** Do not assume, and do not ask the user to describe their setup when you can look.

**1. MCP connector (Claude Chat, and usually Cowork and Claude Code).** Look for Composio's Google Drive tools in this session: `GOOGLEDRIVE_FIND_FILE` and friends, or a `run_composio_tool` / `COMPOSIO_SEARCH_TOOLS` wrapper. If they are there, use them and skip to Step 1. This is the connection the setup guide teaches, so it is the one most people will have.

Through the connector the Drive tools this skill names are **not called directly**: pass each slug and its arguments to `COMPOSIO_MULTI_EXECUTE_TOOL`, or call `run_composio_tool(slug, args, account=...)` inside `COMPOSIO_REMOTE_WORKBENCH`. The arguments are the same. `COMPOSIO_SEARCH_TOOLS` will also offer its own plan for a PDF (download it and parse with `pdfplumber`). **Ignore that plan and follow this skill:** `pdfplumber` has no OCR, so a scanned PDF comes back empty, and its output is not the Docs export the cleaner is built for.

**2. CLI (Claude Code, and Cowork when it has a shell).** If no Composio tools are in the session, try the CLI:

```bash
composio whoami                 # JSON with the account email = the CLI is installed and signed in
composio connections list       # JSON keyed by toolkit slug
```

In `connections list`, find `googledrive` and read the `status` of each entry. Then call tools as `composio execute GOOGLEDRIVE_FIND_FILE -d '{ ... }'`. The tool names and arguments are identical to the MCP ones, so the rest of this skill is unchanged.

- **`ACTIVE` is the only status that works.** `EXPIRED` appears exactly like a live connection in a plain listing and fails on the first call. Check the word, not the presence of the key.
- **If `command not found` on Windows**, the CLI is often installed inside WSL rather than on the Windows PATH. Try `wsl.exe -e bash -lc 'composio whoami'` before concluding it is missing.

**3. Neither.** Say so plainly, name which of the two you looked for, and give them the choice:
- **Connect it.** About five minutes, once: the setup guide that came with this skill walks through the MCP connector, or `composio link googledrive` from a shell. Then re-invoke this skill and it runs end to end.
- **Skip the connection this time.** They do the Drive steps by hand (upload the PDF to Drive, open it with Google Docs, File > Download > Markdown), hand you the `.md`, and you start at Step 3. The cleanup script needs no connection, no API key and no network.

Never guess a path and let it fail at the first Drive call; a 401 or an empty tool list four steps in reads to the user as a broken skill.

**Two accounts on one toolkit is normal and is not a failure.** `connections list` shows one entry per connected account, and Composio refuses Drive calls until you name one: pass `--account <word_id>` on the CLI, or `account` on the MCP call. Confirm the choice with `GOOGLEDRIVE_GET_ABOUT` before any write. Step 1 covers what to do when the account is wrong. The connector and the CLI can list different accounts for the same toolkit (one real setup: four through the connector, two through the CLI). The connector marks one account `is_default`; start there.

## Step 1: Find the file

- Get the Drive file ID from the link (the part after `/d/`), or search by name with `GOOGLEDRIVE_FIND_FILE`.
- Call `GOOGLEDRIVE_GET_FILE_METADATA` for its type and parent folder ID, and **ask for the fields
  by name**: `{"fileId": "<id>", "fields": "id,name,mimeType,parents,driveId"}`. Without `fields` the
  tool answers with `kind, id, name, mimeType` only, and `parents` is silently missing. Keep the
  folder ID for Step 6; that ID is the only thing that puts the clean file back where the source
  lives. If `parents` still does not come back, say so and ask where to save rather than guessing a
  folder.
- **If several Google accounts are connected** (Step 0), pass the account on each call: `account` on an MCP call, `run_composio_tool(..., account=...)` in the workbench, `--account <word_id>` on the CLI. Choose the account that owns or can see the file, and confirm it with `GOOGLEDRIVE_GET_ABOUT` before any write.
- **If a call returns 404 "File not found"**, call `GOOGLEDRIVE_GET_ABOUT` before doubting the ID. The Composio connection is often signed in to a different Google account than the one that owns the file, and Drive answers a wrong account with the same 404 as a wrong ID. Tell the user which account the connection uses.

## Step 2: Get a Google Doc, then export it as Markdown

**If the file is a PDF**, convert it with `GOOGLEDRIVE_COPY_FILE_ADVANCED`:
- `fileId`: the PDF, `mimeType`: `application/vnd.google-apps.document`, `ocrLanguage`: `en` (or the document's language), `supportsAllDrives`: true, `name`: `<title> - temp`, `parents`: `["root"]`.
- The copy goes in the user's private My Drive root on purpose. Shared folders often carry public links, and this temporary Doc holds the full document text.
- Google reads scanned pages here too (OCR). This is the step that makes scans work.

**Export** with `GOOGLEDRIVE_EXPORT_GOOGLE_WORKSPACE_FILE` (`fileId`, `mimeType: text/markdown`). It returns a temporary download link at `data.file.s3url` that expires after an hour, so fetch it straight away. `GOOGLEDRIVE_DOWNLOAD_FILE` with `mime_type: text/markdown` is the fallback.

**If you made a temporary Doc**, move it to the trash once the export is downloaded: `GOOGLEDRIVE_TRASH_FILE` with `file_id` (snake case; this tool rejects `fileId`). Read its metadata again and confirm `trashed: true`. Trash is recoverable for 30 days. Only ever trash a Doc this skill created, and never delete permanently.

Where the download and the script run matters, because the raw export is the expensive part. Use the first option that works:
1. **Claude Code:** download the link to a local file and run the script locally.
2. **Composio remote workbench** (`COMPOSIO_REMOTE_WORKBENCH`, in the chat app): fetch the link inside the workbench and run the script there. Get the script from this skill's public repo, save it in the sandbox and run it with the sandbox's own Python:
   `https://raw.githubusercontent.com/joeoliveimpact/legit-pdf2md/main/plugins/legit-pdf2md/skills/legit-pdf2md/scripts/clean_gdoc_md.py`
   No local Python is needed, and the raw export never enters the conversation.
3. **Code execution in the chat app:** fetch and run the script in the sandbox, if it can reach the link.
4. **Last resort:** read the export into the chat and clean it there. Tell the user this chat will be heavy and that the clean file is what goes into their next chat.

## Step 3: Strip the junk (script)

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/legit-pdf2md/scripts/clean_gdoc_md.py" strip export.md -o clean.md
```

`${CLAUDE_PLUGIN_ROOT}` is set for an installed plugin. If it is empty (the skill was copied in by
hand, or the shell does not expand it), use the base directory this skill was loaded from, or find
the file once with `find ~/.claude -name clean_gdoc_md.py` and use that absolute path for both this
step and Step 5. Never fall back to cleaning the Markdown by hand: the script and its check are what
make the wording guarantee true.

**In the chat app** there is no `${CLAUDE_PLUGIN_ROOT}` and usually no local Python. Run Steps 3 and 5 in the Composio workbench with the script fetched from the repo (option 2 above).

`python3` is the name that exists on macOS and most Linux boxes; on Windows it is usually `python`.
Use whichever the shell answers to, the same one for Step 5. The script needs nothing but the
standard library, any version from 3.8 up.

It works outside fenced code blocks only; code blocks (including ones inside quotes and lists) and inline code are never touched. It removes base64 images (leaving `[image N]` placeholders), `&nbsp;` and other entities, broken characters, Google's backslash escapes, the code-font backticks the Drive API export wraps around letter-spaced text and bare step numbers, asterisks that OCR scatters between letters, trailing spaces and extra blank lines. It never changes wording. It prints JSON with `stats` and a `worklist`.

## Step 4: Rebuild the structure (judgment)

A script cannot do this part, because the export has lost information that only reading can restore. Start from the worklist: it names the lines that need attention. If you see the same pattern on a line it missed, fix that too. Make targeted edits by line; retyping the whole document costs far more and is where wording drifts.

**Letter-spaced text** (`letter_spaced`). Display type from a designed PDF comes out as single letters: `S T A R T W H E R E Y O U A R E`, or a short `W H Y`. The spaces between words are gone, so read it and rejoin it: `Start where you are`.
- Part and section titles become `##`, sub-labels `###` or bold. Give the document title `#` even if a part label happens to come before it.
- Use sentence case for headings. Case is styling, not wording.
- When a line mixes a spaced title with normal text, split them: the title becomes the heading, the text stays below it.

**Page furniture** (`repeated_lines`, `repeated_openings`). A PDF repeats its header and footer on every page, and the export repeats them too. Some are identical; others change a few words per page but open the same way ("You're here: ...") or end with the same handle. Remove them. Keep a line that repeats because it is real content, like a label that opens each section. Keep the author's name once and their handle once, where each first appears.

**Detached numbers** (`detached_numbers`). Step numbers get pulled out of their list and land on their own line, at the end of the previous sentence, or in the middle of a sentence that crosses a page break. Rebuild them as a numbered list (`1.`, `2.`) and rejoin any sentence they cut. Leave a blank line after the last item: without it, the next heading or label renders as part of the final step. If you cannot tell which step a number belongs to, keep the sentences whole and drop the stray number rather than guess.

**Sentences split by page breaks** (`split_sentences`). A line that stops mid-sentence, followed by a paragraph that starts in lowercase, is one sentence the page break cut. Join them.

**Unpaired asterisks** (`odd_asterisks`). Decide in context. Remove one only when it is clearly OCR noise; a wildcard like `file*.md`, a multiplication sign, and real bold or italics all stay.

**Scrambled order.** Page layout sometimes exports out of reading order: table cells in the wrong sequence, problem titles grouped apart from their fixes. Do not reorder it. Guessing which piece belongs where can change what the document says, and the check cannot tell a correct move from a wrong one. Leave it in place and name each spot in the report so the user can fix it in seconds. One exception: a heading that landed inside a sentence may be moved out so the sentence reads whole. Put the moved heading on its own line: the check reports that as `moved_runs`, not added text, and a short heading only counts as a move when it stands alone.

**Tables.** If a table came out as loose lines and its cells still read in the right order, you may rebuild it as a Markdown table. If the order is scrambled, treat it as scrambled order above.

**Images** (`image_lines`). Keep each `[image N]` on its own line where it sat. Do not describe the image.

**Code-font labels** (`code_spans`). The Drive API export puts display labels in code font, like `` `CONTENT` ``. Remove the backticks from labels and headings; keep them on anything that is real code, a command or a file name.

**Copy-paste prompts and folder trees** may go in code fences. Inside a fence, remove leftover escapes like `1\.`, because fences show backslashes literally.

**Do not** fix typos, reword, or add an intro or summary. The user's words are the data.

## Step 5: Check the wording

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/legit-pdf2md/scripts/clean_gdoc_md.py" check export.md clean.md
```

It compares wording word by word, in any language, ignoring spacing, case, Markdown, code-fence lines and removed junk. It does not compare punctuation, which is why Step 3 never touches code. Exit code 1 means it failed.

Run it on the **rebuilt** file. On Step 3's raw output it can fail on purpose: a word glued to letter-spaced type (`MetricoolB O N U S`) reads as a merge until Step 4 splits it. That is the worklist doing its job, not a bug in the cleaner.
- `added_runs` must be empty. Anything listed, even one letter or digit, is text the source never had. Remove it and check again.
- `partial_word_drops` must be empty. Each is a deletion that cut into a word, which changes the word. Restore it.
- `merged_words` must be empty. Two separate words were joined into one ("now here" became "nowhere"). Split them again. Rejoining letter-spaced type is not a merge, including when OCR chunked two or three letters together inside the run (`C O P Y - P A S TE`, `T O WR ITE`). If a rejoined heading is still reported, the run's first or last piece is an ordinary word rather than display type: look at that one word, and leave the rest of the heading joined.
- `split_words` are single words the rebuild split in two. Most are words the export glued together, like "MetricoolBONUS"; keep those, undo any other.
- `inline_drops` are whole words deleted from a line that otherwise survives. Each must be page furniture you removed on purpose, like a handle stuck to a title. A deleted "not" or "no" flips the meaning: put it back.
- `dropped_lines` are whole lines removed. They should all be page furniture.
- `moved_runs` lists text that changed place. Each one needs a line in the report.

## Step 6: Save it back to Drive

Call `GOOGLEDRIVE_CREATE_FILE_FROM_TEXT` with `file_name` `<original title> - clean.md`, `text_content` the clean Markdown, `mime_type` `text/markdown`, and `parent_id` the folder ID from Step 1.

## Step 7: Report

Keep it short:
- Estimated tokens before and after (from `stats`).
- What was fixed, using the `stats` counts plus how many lines you edited.
- **What could not be recovered**, every time: link addresses (only the link text survives the export), any scrambled spots you left in place, and whether a temporary Doc was made and trashed.
- The check result.
- The file link, and: "Start a new chat and add this file instead of the PDF." For a local file with no Drive link, say where the clean file was saved.

## Known limits

- The wording check compares letters and digits, not punctuation. That is why Step 3 never touches code; a changed symbol elsewhere in the text is not caught.
- Letter-spaced type is recognized by pattern: three or more single characters in a row, separated by plain spaces, with two- or three-letter OCR chunks allowed between them as long as the run still starts on a single character and is mostly single characters. Unusual spacing may need a closer look at the `split_words` and `merged_words` lists.
- A run may end on one such chunk (`P A S TE:`), so a real two- or three-letter capital word sitting immediately after display type could be absorbed into it without the check objecting. Leading words are never absorbed.
- Indented code blocks (four spaces, no fence) are not detected. Google's export uses fences, so this rarely matters.
- Link addresses do not survive Google's export; only the link text does.

## Tools reference

| Step | Composio tool | Note |
|---|---|---|
| Find | `GOOGLEDRIVE_FIND_FILE`, `GOOGLEDRIVE_GET_FILE_METADATA` | `fileId`, plus `fields` for `parents` |
| Wrong account? | `GOOGLEDRIVE_GET_ABOUT` | run on any 404 |
| PDF to Doc | `GOOGLEDRIVE_COPY_FILE_ADVANCED` | `fileId`, `ocrLanguage` |
| Export | `GOOGLEDRIVE_EXPORT_GOOGLE_WORKSPACE_FILE` | link expires in 1 hour |
| Clean up temp Doc | `GOOGLEDRIVE_TRASH_FILE` | `file_id`, not `fileId` |
| Run a tool via the connector | `COMPOSIO_MULTI_EXECUTE_TOOL` | pass `tool_slug`, `arguments`, `account` |
| Run script remotely | `COMPOSIO_REMOTE_WORKBENCH` | chat app; script from the repo raw URL |
| Save | `GOOGLEDRIVE_CREATE_FILE_FROM_TEXT` | `parent_id` |

Parameter casing differs between these tools; when a call fails validation, read that tool's schema rather than assuming (`--get-schema` on the CLI). Every tool name above works unchanged through the Composio MCP connection and through the CLI (`composio execute <TOOL> -d '{...}'`), which is why Step 0 only has to decide which one is live.
