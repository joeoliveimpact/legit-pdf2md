---
name: legit-pdf2md
description: Turn a Google Doc, or a PDF stored in Google Drive (including scanned PDFs), into clean Markdown and save it back to the same Drive folder, using the Composio Google Drive connection. Use this whenever someone wants a PDF or Google Doc converted to Markdown for Claude or ChatGPT, wants to stop PDFs eating their tokens or filling the context window, has a Markdown file exported from Google Docs full of junk (&nbsp;, base64 image blocks, letter-spaced text like "S T A R T", stray step numbers or asterisks), or asks to "clean up", "fix" or "make readable" a Docs export, even if they never say the word cleanup.
---

# Google Doc or Drive PDF to clean Markdown

This is version 0.2.0 of the skill.

## Output contract

Done means all five:
1. A new file `<original title> - clean.md` in the **same Drive folder** as the source (Step 5 has the naming rule, the one fallback, and re-runs: an unchanged source reuses its earlier clean file, and nothing is ever overwritten). For a local `.md` the user handed you: `<file name> - clean.md` beside it.
2. The wording is the source's wording. Nothing reworded, summarized, corrected or added.
3. `pipeline --final` returned `status: validated`.
4. The saved file was read back and its sha256 equals the pipeline's `clean_sha256`, and only then was the temporary Doc (if one was made) trashed.
5. A short report (Step 6).

**Re-invoked partway through?** (A long session can drop this file from context; reloading it is right.) Do not start over. Composio can replace its sandbox between any two calls, so the record of a run lives in this chat, on every path: the file id, the account, the temporary Doc id, and every edit batch you have written. Keep all four in your replies as you go. With them, the runtime file's later steps rebuild the run and continue. Never make a second temporary Doc for a run that already has one.

## Why this matters

Google's own Markdown export is the cheapest way to get text out of a PDF, and the only one here that reads scanned pages. But the file is mostly junk: a real 12-page guide exported at about 19,400 tokens, 78% of it pictures stored as base64 text, and cleans to about 3,700. (A scanned PDF exports no pictures, so it starts far smaller and the saving is smaller.) The person is trying to stop their AI forgetting their documents, so the cleanup must never quietly change what the document says. A script does everything that is certain, you (the AI) decide only what needs reading, and a check proves nothing was lost.

## How the work is split

- **The script** (`clean_gdoc_md.py pipeline`) strips the junk, makes every fix that cannot change wording, logs every deletion by position, and hands you a small packet: only the lines that need judgment.
- **You** write edits for those lines (Step 3). You never retype the document.
- **The check** (`pipeline --final`) compares the result with the export letter by letter and picture by picture. It is what makes the promise true, so never clean by hand when the script cannot run: stop and say so.

The script and the Drive helper are fetched from this skill's public repo into Composio's workbench (a remote Python sandbox), so the user needs no Python and no coding setup. Always fetch from this URL; never use a copy of the repo already in the sandbox, which can be an older version:
`https://raw.githubusercontent.com/joeoliveimpact/legit-pdf2md/legit-pdf2md--v0.2.0-rc2/plugins/legit-pdf2md/skills/legit-pdf2md/scripts/` + `clean_gdoc_md.py` or `drive_txn.py`

## Step 0: Find the Composio connection

Look before asking; never make the user describe their setup. (Handed a local `.md`? Skip to the local route in Step 2.)

1. **Connector (MCP)**: Claude chat, Cowork, Claude Code, ChatGPT. Composio's meta-tools are in the session (`COMPOSIO_MULTI_EXECUTE_TOOL`, `COMPOSIO_REMOTE_WORKBENCH`, `COMPOSIO_MANAGE_CONNECTIONS`). Check Drive: `COMPOSIO_MANAGE_CONNECTIONS` with `{"toolkits": [{"name": "googledrive", "action": "list"}]}` must show an `ACTIVE` account. Then follow **`references/runtime-connector.md`**.
2. **CLI**: Claude Code or any AI with a shell. `composio whoami` answers with an email (on Windows try `wsl.exe -e bash -lc 'composio whoami'` before concluding it is missing), and `composio connections list` shows `googledrive` with status `ACTIVE`. Then follow **`references/runtime-cli.md`**.
3. **Neither**: say which two you looked for, then offer: connect it (about five minutes, once: the "Connect Google Drive" section of this plugin's README), or do the Drive part by hand (upload the PDF, open it with Google Docs, File > Download > Markdown) and take the local route. The local route needs Python on this machine; Composio needs none, because its workbench brings its own.

`ACTIVE` is the only status that works; `EXPIRED` looks identical in a plain listing. Several accounts on the toolkit is normal: name one on every call (the reference file says how) and confirm it with `GOOGLEDRIVE_GET_ABOUT` before any write. The connector marks one account `is_default`; start there.

Use only Composio for Drive. If the app also has its own Google Drive integration, leave it out of this run: two integrations can be signed in to different accounts.

## Step 1: Find the file

- The file ID is the part of the link after `/d/`, or search by name with `GOOGLEDRIVE_FIND_FILE`. On the connector the start cell reads the metadata itself: call it yourself only to find the file or the account.
- Metadata must ask for the fields by name, or `parents` silently goes missing: `{"fileId": "<id>", "fields": "id,name,mimeType,parents,driveId,modifiedTime", "supportsAllDrives": true}`. The parent folder is the only thing that puts the clean file back beside its source.
- **404 "File not found"**: call `GOOGLEDRIVE_GET_ABOUT` before doubting the ID. The connection is often signed in to a different Google account than the one that owns the file, and Drive answers a wrong account with the same 404 as a wrong ID. With several ACTIVE accounts, try the others; otherwise tell the user which account the connection uses. Once one account finds the file, use only that account for the whole run.

## Step 2: Export and run the pipeline

A PDF is first copied to a temporary Google Doc in the user's private **My Drive root** (never the shared folder, which may carry a public link), with the document's OCR language (`en` unless it is in another language). That copy is where Google reads scanned pages. Google converts only a PDF's first 80 pages, without saying so, so a longer PDF stops before the copy: tell the user to split it into parts of 80 pages or fewer and run each part. **On the connector, `drive_txn.py` makes this copy in the start cell: never make it yourself**, or it is a second copy nobody trashes. On the CLI you make it. Either way, write its id into your reply at once. The Doc (or the temporary copy) is exported as `text/markdown`, and the export goes straight into the workbench: its download link expires in an hour, and the raw export (the expensive part) never enters the conversation.

Then, in the workbench: `clean_gdoc_md.py pipeline export.md --state state.json`. It prints compact JSON:
- `status: needs_host_edits` with a packet: `rev`, `ops_by_type`, and `issues`, a list of blocks. Each block has an `id` (`b3`), `types`, its `lines`, its `text` with every line numbered (`171| Make a free account.`), the whole lines just `before` and `after` it (with their numbers), and sometimes `suggested_drop` or `suggested_list` (both are lists). Go to Step 3.
- No issues left: it runs the final check itself. Go to Step 4.

The runtime files have the exact cells for Drive. **Local route** (the user handed you an exported `.md`, no Composio): run the same commands with this session's own Python (`python3`; `py -3` on Windows, where `python` is often a Microsoft Store shortcut that prints "Python was not found") and the script in this skill's `scripts/` folder (inside the directory this skill was loaded from), keeping the state and edits files in a temporary folder. No Python anywhere: say so and stop. Save the result beside the user's file (in a chat app, where it offers the user downloads) named by Step 5's rule (`Guide.md` → `Guide - clean.md`), never over an existing file (take `(2)`, then `(3)`), and check the saved file's sha256 equals `clean_sha256`.

## Step 3: Write the edits (judgment)

Read each block and write edits for it. Send them all in one file:

```json
{"rev": "<rev from the newest packet>", "edits": [
  {"issue": "b5", "op": "replace", "lines": [45, 45], "text": "## Part 1 · Start where you are"},
  {"issue": "b18", "op": "number_list", "lines": [171, 177], "text": "1. Make a free account.\n2. Connect it."},
  {"issue": "b38", "op": "replace", "lines": [392, 392], "text": "<the line without the nav text>",
   "drops": ["You're here: troubleshooting • Next: the stack"], "reason": "page navigation"}]}
```

then `clean_gdoc_md.py apply-edits edits.json --state state.json`. It is all or nothing: any error and nothing changes, the errors say why, fix them and send again. Every successful batch returns a **new packet with a new `rev`, new line numbers and new block ids**; a next batch must use those. Leave a block alone if nothing in it needs changing.

**The rules the script enforces.** Letters and digits must stay exactly the same and in the same order. Case, spacing, punctuation and Markdown are yours. The exceptions each need their op:
- `replace`: new text for the lines. To remove page furniture from a line, list the exact removed text in `drops` with a `reason`.
- `delete`: remove whole lines of page furniture, with a `reason`.
- `number_list`: rebuild a numbered list; only the stand-alone step numbers may move, each to the start of its own item, in order.
- `move_heading`: a letter-spaced heading that landed inside a sentence moves out whole, onto its own line (`"text": "<heading>\n\n<the sentence rejoined>"` over the block's lines).
An edit may cover a block's lines plus the line either side; deletions (`delete`, `drops`) only work on the lines that were flagged, so a real sentence sitting between two flagged lines cannot be removed. Only use ops listed for the block's types in `ops_by_type`.

**What to do with each type:**
- `letter_spaced`: display type came out as single letters (`S T A R T W H E R E Y O U A R E`, `W H Y`). Rejoin the words: `Start where you are`. Part and section titles become `##`, sub-labels `###` or bold; the document title gets `#`. Sentence case. A line mixing a spaced title with normal text: title as the heading, text below it. A word glued to spaced type (`MetricoolB O N U S`) splits: `### Metricool` then `Bonus · not in the reel`.
- `number_list` with `suggested_list`: the script's proposed list, with its own `lines`. **Check it against the text, do not rubber-stamp it.** It can be wrong when the numbers are real content (`final score: 1 / 2 / 3`, `Chapter 3`), when the numbers sit before their items rather than after, or when the run is broken (1, 1, 2). If it is right, send it as a `number_list` edit with its `lines` and `text`. If not, write the right list, or leave the numbers where they are.
- `detached_number`: a step number pulled out of its list. Rebuild the list, or if you cannot tell which step it belongs to, keep the sentences whole and drop the stray number (`drops` + `reason`) rather than guess. Leave a blank line after a list's last item.
- `repeated_line`, `page_nav_attached`: page furniture repeated on every page. Remove it: a whole `repeated_line` with `delete`; the navigation text stuck to a real line with `replace` + `drops` (the block's `suggested_drop` is the text to drop). Keep a line that repeats because it is real content, and keep the author's name and handle once where they first appear.
- `code_label`: the export put display labels in code font (`` `CONTENT` ``). Remove the backticks from labels and headings; keep them on real code, commands and file names.
- `odd_asterisks`: remove one only when it is clearly OCR noise; a wildcard, a multiplication sign, real bold or italics stay.

**Never**: fix a typo, reword, add an intro or summary, describe an image, or reorder content. Keep every `[image N]` line where it is. When layout scrambled the order (table cells, titles apart from their fixes), leave it and name the spot in the report; the check cannot tell a right move from a wrong one.

## Step 4: The final check

`clean_gdoc_md.py pipeline export.md --state state.json --final -o clean.md` (it writes `clean.md` only when validated). Always validate this way, never with the older standalone `check`: a correctly moved heading can fail that one.
- `validated`: go to Step 5 (on the connector, after this read, with `SAVE = True`). `left_for_review` counts blocks you chose to leave; that is allowed. Read `deleted` (every removal, with its reason): anything there that is real content, put back before saving.
- `needs_review`: `unexplained_drops` lists text that was removed without a logged reason. Put it back or log it (`drops`/`delete` with a reason), then run the final check again. The file is not saved until this passes.
- `failed`: read `check`. `added_runs` is text the source never had; `partial_word_drops` cut into a word; `merged_words` joined two words ("now here" became "nowhere"; rejoining letter-spaced type is not a merge, even with OCR chunks like `P A S TE`, so if a rejoined heading is listed, its first or last piece is an ordinary word: keep that word separate); `images` must show `ok: true` (every picture present, in order, none invented). Fix with more edits and check again. `moved_runs` and `split_words` do not fail it; mention moved text in the report.

## Step 5: Save, verify, clean up

Name: `<original title> - clean.md`, where a PDF's title loses a trailing `.pdf` (any case) and nothing else is ever cut (`Guide.pdf` → `Guide - clean.md`; `Notes 09.11.26` → `Notes 09.11.26 - clean.md`). The script's `clean_name(title, mime_type)` applies this rule; use it rather than typing the name. A local `Guide.md` becomes `Guide - clean.md` beside it.

**Re-runs.** Every clean file saved to Drive carries a reuse key in its description: the source's id and last-modified time. Before any work, look for it (the runtime file says how): if this exact version of the source was cleaned before, report that file and stop. If the source changed, or another file already has the name, save `<title> - clean (2).md` (then `(3)`): never overwrite.

Save in the source's folder, read the file back, and compare its sha256 with `clean_sha256`. Only when they match, trash the temporary Doc this run made and confirm it reads `trashed: true`. Trash is recoverable for 30 days; never delete permanently, and never trash anything this run did not create. If the account may not add files to the source's folder, the clean file goes to My Drive root and the report says so. If a read-back does not match, stop: keep the temporary Doc and report the saved file's id so the user can check it. The runtime file has the exact calls (on the connector, `drive_txn.py` does all of this).

## Step 6: Report

A re-run that found this version already cleaned reports only that and the file's link. Otherwise keep it short:
- Tokens before and after (`tokens`), the automatic fixes (`autofixed`), and how many edits you made.
- The check result: validated.
- **What could not be recovered**, every time: link addresses (only link text survives Google's export), pictures listed under `kept_in_code`, scrambled spots you left in place, blocks you left for review, and whether a temporary Doc was made and trashed.
- Where the file went (the link, or the local path, and the fallback if one was used), and: "Start a new chat and add this file instead of the original."

## References

In the `references/` folder next to this file. This file's own link is `https://raw.githubusercontent.com/joeoliveimpact/legit-pdf2md/legit-pdf2md--v0.2.0-rc2/plugins/legit-pdf2md/skills/legit-pdf2md/SKILL.md`; replace `SKILL.md` at its end with `references/<name>`. If your own fetch cannot open a link and no GitHub connector can read it, fetch it in `COMPOSIO_REMOTE_WORKBENCH` and read the output: `import requests; print(requests.get("<link>", timeout=60).text)`.
- `references/runtime-connector.md`: the connector path (Claude chat, Cowork, Code, ChatGPT), cell by cell.
- `references/runtime-cli.md`: the CLI path, including Windows with the CLI inside WSL.
- `references/tools-and-limits.md`: every Composio tool with its parameter-casing traps, and the known limits of the script and the check. Open it when a call fails validation or a result is not explained above.
- `references/modes.md`: optional link and layout modes (coming in a later version).
