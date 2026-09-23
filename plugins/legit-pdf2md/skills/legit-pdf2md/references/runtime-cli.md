# Runtime: the Composio CLI

For an AI with a shell (Claude Code, or Cowork with one). Drive calls run as `composio execute` on the user's machine; only the script runs in Composio's workbench.

## Ground rules

- **Windows, CLI inside WSL** (`composio` "not found" or "is not recognized", but `wsl.exe -e bash -lc 'composio whoami'` answers): run **every** composio command that way. Arguments go as a double-quoted object: `wsl.exe -e bash -lc 'composio execute GOOGLEDRIVE_GET_ABOUT -d "{ }"'`. For anything longer or with quotes in it (a workbench cell, a title with an apostrophe), write the JSON to a file in a folder with no spaces and pass its WSL path: `-d @/mnt/c/Users/<you>/cell.json`.
- **Accounts.** `composio connections list` has one entry per connected account; only `ACTIVE` works. With several, pass `--account <word_id>` (from that listing; an alias works too) on every Drive call, and confirm with `GOOGLEDRIVE_GET_ABOUT` before any write.
- **Never call Drive tools from inside the workbench on this path.** A workbench started from the CLI ignores the connection's account: in testing, a read went to a different Google account of the same user, and naming the account there is refused. Every Drive step below runs as `composio execute` outside it.
- **Every workbench call is a fresh sandbox.** Nothing carries over, so each cell fetches the script and the export itself and rebuilds the run from scratch. That is safe: `pipeline` on the same export always produces the same text and the same `rev`, so edits written against one cell's packet apply in the next.
- Parameter casing differs between tools (`fileId` here, `file_id` there). When a call fails validation, read its schema: `composio execute <TOOL> --get-schema`.

## Drive steps (outside the workbench)

1. Metadata, with `fields` (SKILL.md Step 1).
2. A PDF: `GOOGLEDRIVE_COPY_FILE_ADVANCED` with `fileId`, `mimeType: application/vnd.google-apps.document`, `ocrLanguage`, `supportsAllDrives: true`, `name: "<title> - temp"`, `parents: ["root"]`. **Write the returned id down in your reply** so it survives the session. If you ever lose it, do not guess: leave the Doc, and tell the user its name so they can trash it.
3. Export: `GOOGLEDRIVE_EXPORT_GOOGLE_WORKSPACE_FILE` with `fileId` (the temporary Doc, or the source Doc) and `mimeType: text/markdown`. The download link is `data.file.s3url`; it expires in an hour (export again if it has).

## Cell A: pipeline

Run with `composio execute COMPOSIO_REMOTE_WORKBENCH -d @cell.json`, where `cell.json` is `{"code_to_execute": "<the code>"}`:

```python
import json, subprocess, sys, requests
BASE, EXPORT = "<script URL from SKILL.md, ending in scripts/>", "<export link>"
open("clean_gdoc_md.py", "w", encoding="utf-8").write(requests.get(BASE + "clean_gdoc_md.py", timeout=60).text)
open("export.md", "w", encoding="utf-8").write(requests.get(EXPORT, timeout=60).content.decode("utf-8"))
run = lambda *a: subprocess.run([sys.executable, "clean_gdoc_md.py", *a], capture_output=True, text=True).stdout
print(run("pipeline", "export.md", "--state", "state.json"))
```

## Cell B: edits, final check, save payload

Keep every edit batch you write. Cell B replays all of them, in order, on a fresh run:

```python
import hashlib, json, subprocess, sys, requests
BASE, EXPORT = "<script URL>", "<export link>"
NAME, PARENT = "<clean file name>", "<source folder id>"
BATCHES = [ {"rev": "<rev>", "edits": [ ... ]} ]
FINAL = False   # True once no block you mean to change is left
open("clean_gdoc_md.py", "w", encoding="utf-8").write(requests.get(BASE + "clean_gdoc_md.py", timeout=60).text)
open("export.md", "w", encoding="utf-8").write(requests.get(EXPORT, timeout=60).content.decode("utf-8"))
run = lambda *a: subprocess.run([sys.executable, "clean_gdoc_md.py", *a], capture_output=True, text=True).stdout
run("pipeline", "export.md", "--state", "state.json")
for b in BATCHES:
    json.dump(b, open("edits.json", "w", encoding="utf-8"), ensure_ascii=False)
    out = json.loads(run("apply-edits", "edits.json", "--state", "state.json"))
    if not out["applied"] or not FINAL and b is BATCHES[-1]:
        print(json.dumps(out, ensure_ascii=False)); raise SystemExit   # errors, or the next packet
r = json.loads(run("pipeline", "export.md", "--state", "state.json", "--final", "-o", "clean.md"))
print(json.dumps({k: r.get(k) for k in ("status", "clean_sha256", "tokens", "autofixed", "left_for_review", "unexplained_drops", "check")}))
if r["status"] == "validated":
    print("SAVE_JSON " + json.dumps({"file_name": NAME, "text_content": open("clean.md", encoding="utf-8").read(),
                                     "mime_type": "text/markdown", "parent_id": PARENT}, ensure_ascii=False))
```

With `FINAL = False` the cell prints the newest packet (new `rev`, new line numbers) for your next batch. If a batch is refused, it prints the errors and the packet for the text before that batch: fix the batch and run again. Set `FINAL = True` when you are done editing.

## Save, verify, clean up (outside the workbench)

1. Copy the `SAVE_JSON` object exactly into `save.json` and run `composio execute GOOGLEDRIVE_CREATE_FILE_FROM_TEXT -d @save.json`. Keep the returned `data.id`. If the folder refuses the write because the account lacks permission, drop `parent_id`, save again (My Drive root), and say so in the report. Any other error: stop and report it.
2. Read it back: `GOOGLEDRIVE_DOWNLOAD_FILE` with `fileId` = the saved id; the link is `data.downloaded_file_content.s3url`. Hash it with line endings normalized: `curl -s "<link>" | tr -d '\r' | sha256sum` (in WSL on Windows). It must equal `clean_sha256`. If it does not, stop: report the saved file's id, and keep the temporary Doc.
3. Only after a match: `GOOGLEDRIVE_TRASH_FILE` with `file_id` (snake case; this tool rejects `fileId`) = the temporary Doc id you wrote down, then `GOOGLEDRIVE_GET_FILE_METADATA` with `fields: "trashed"` must say `true`. Never trash anything else.
