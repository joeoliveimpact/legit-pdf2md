# Runtime: the Composio CLI

For an AI with a shell (Claude Code, or Cowork with one). Drive calls run as `composio execute` on the user's machine; only the script runs in Composio's workbench.

## Ground rules

- **Windows, CLI inside WSL** (`composio` "not found" or "is not recognized", but `wsl.exe -e bash -lc 'composio whoami'` answers): run **every** composio command, and the small `python3` helpers below, inside WSL. Short arguments can go inline (`-d "{ }"`); anything with quotes in it goes in a JSON file in a folder with no spaces, passed by its WSL path: `-d @/mnt/c/Users/<you>/work/args.json`. Write JSON files with a tool or a script, never by hand-escaping. The helpers' single quotes collide with `bash -lc '...'`, so write the commands into a `.sh` file in that folder (with a tool) with LF line endings, starting with `cd /mnt/c/Users/<you>/work`, and run `wsl.exe -e bash -l /mnt/c/Users/<you>/work/step.sh` (from Git Bash, prefix `MSYS_NO_PATHCONV=1`, or it rewrites the `/mnt/c` path).
- **Accounts.** `composio connections list` has one entry per connected account; only `ACTIVE` works. With several, pass `--account <word_id>` (from that listing; an alias works too) on every Drive call, confirm with `GOOGLEDRIVE_GET_ABOUT` before any write, and use that one account for the whole run.
- **Never call Drive tools from inside the workbench on this path.** A workbench started from the CLI ignores the connection's account: in testing, a read went to a different Google account of the same user, and naming the account there is refused. Every Drive step below runs as `composio execute` outside it.
- **Every workbench call is a fresh sandbox.** Nothing carries over, so each cell fetches the script and the export itself and rebuilds the run from scratch. That is safe: `pipeline` on the same export always produces the same text and the same `rev`, so edits written against one cell's packet apply in the next. Exporting the same unedited Doc (the temporary Doc, or the source Doc) again gives the same text, so the same `rev` too; only a new OCR copy of a PDF can differ.
- **The output of a workbench call** is JSON; the cell's printed text is in `data.stdout`, errors in `data.error`.
- Parameter casing differs between tools (`fileId` here, `file_id` there). When a call fails validation, read its schema: `composio execute <TOOL> --get-schema`.

**How to send a cell:** write the Python to `cell.py`, then wrap it and run it:

```bash
python3 -c 'import json; json.dump({"code_to_execute": open("cell.py").read()}, open("cell.json", "w"))'
composio execute COMPOSIO_REMOTE_WORKBENCH -d @cell.json > out.json
python3 -c 'import json; o = json.load(open("out.json", encoding="utf-8")); print("\n".join(l for l in (o["data"]["stdout"] or o["data"]["error"]).splitlines() if not l.startswith("SAVE_JSON ")))'
```

## Drive steps (outside the workbench)

1. Metadata, with `fields` (SKILL.md Step 1). Keep `id`, `name`, `mimeType`, `modifiedTime` and the first of `parents`. The reuse key for this version of the file is `legit-pdf2md reuse: source <id> modified <modifiedTime>` (no `modifiedTime`: no key, and no reuse). The clean name is `<title> - clean.md`, where a PDF's title loses `.pdf` (SKILL.md Step 5). **Look for an earlier clean file first:** `GOOGLEDRIVE_FIND_FILE` with `q: "name contains '<clean name without .md>' and '<folder id>' in parents and trashed = false"`, `fields: "files(id,name,description)"`, `supportsAllDrives: true`, `includeItemsFromAllDrives: true`, then the same with `'root'` for the folder id (a save that fell back to My Drive root is there). If one has exactly the reuse key as its `description`, this version was already cleaned: report that file and stop, with no copy made. Keep the names that are exactly the clean name, or it with ` (N)` before `.md` (the search also returns lookalikes): step 1 of the save needs them.
2. A PDF: first count its pages. Google converts only the first 80, silently. `GOOGLEDRIVE_DOWNLOAD_FILE` with `fileId` = the PDF gives a link (`data.downloaded_file_content.s3url`); in a workbench cell, fetch `drive_txn.py` from the script URL and print `drive_txn.pdf_pages(requests.get("<link>", timeout=120).content)`. Over 80: stop, and tell the user to split it into parts of 80 pages or fewer. Then `GOOGLEDRIVE_COPY_FILE_ADVANCED` with `fileId`, `mimeType: application/vnd.google-apps.document`, `ocrLanguage` (`en`, or the document's language), `supportsAllDrives: true`, `name: "<title without .pdf> - temp"`, `parents: ["root"]`, `description: "legit-pdf2md temp: source <id> modified <modifiedTime>"`. **Write the returned id down in your reply** so it survives the session. If you lose it, find it again: `GOOGLEDRIVE_FIND_FILE` with `q: "name = '<title without .pdf> - temp' and 'root' in parents and trashed = false"` and `fields: "files(id,name,description)"`, and take only the file whose `description` is exactly that stamp. Nothing matches: no copy of this version exists, so make one as above. A Google Doc source needs no copy.
3. Export: `GOOGLEDRIVE_EXPORT_GOOGLE_WORKSPACE_FILE` with `fileId` (the temporary Doc, or the source Doc) and `mimeType: text/markdown`. The download link is `data.file.s3url`; it expires in an hour. When it has, export the **same** Doc again and carry on with the new link: the text and the `rev` are the same, so keep `BATCHES`. Never make a second copy for it.

## Cell A: pipeline

```python
import json, subprocess, sys, requests
BASE, EXPORT = "<script URL from SKILL.md, ending in scripts/>", "<export link>"
for url, path in ((BASE + "clean_gdoc_md.py", "clean_gdoc_md.py"), (EXPORT, "export.md")):
    got = requests.get(url, timeout=60); got.raise_for_status()   # an expired link must stop the run here
    open(path, "w", encoding="utf-8").write(got.content.decode("utf-8"))
p = subprocess.run([sys.executable, "clean_gdoc_md.py", "pipeline", "export.md", "--state", "state.json"],
                   capture_output=True, text=True)
print(p.stdout or p.stderr)
```

If it already says `validated`, run cell B with `BATCHES = []` and `FINAL = True`.

## Cell B: edits, final check, save payload

Keep every edit batch you write. Cell B replays all of them, in order, on a fresh run:

```python
import json, subprocess, sys, requests
BASE, EXPORT = "<script URL>", "<export link>"
TITLE, MIME, PARENT = "<source name>", "<source mimeType>", "<source folder id>"
BATCHES = [ {"rev": "<rev>", "edits": [ ... ]} ]
FINAL = False   # True once no block you mean to change is left
for url, path in ((BASE + "clean_gdoc_md.py", "clean_gdoc_md.py"), (EXPORT, "export.md")):
    got = requests.get(url, timeout=60); got.raise_for_status()
    open(path, "w", encoding="utf-8").write(got.content.decode("utf-8"))
def run(*a):
    p = subprocess.run([sys.executable, "clean_gdoc_md.py", *a], capture_output=True, text=True)
    if not p.stdout:
        raise RuntimeError(p.stderr[-2000:])   # the script crashed: a real error
    return json.loads(p.stdout)
def main():   # plain returns: a stopped cell must not read as a failed one
    out = run("pipeline", "export.md", "--state", "state.json")
    for b in BATCHES:
        json.dump(b, open("edits.json", "w", encoding="utf-8"), ensure_ascii=False)
        out = run("apply-edits", "edits.json", "--state", "state.json")
        if not out["applied"]:
            break
    if not FINAL or not out.get("applied", True):
        return print(json.dumps(out, ensure_ascii=False))   # errors, or the next packet
    r = run("pipeline", "export.md", "--state", "state.json", "--final", "-o", "clean.md")
    print(json.dumps({k: r.get(k) for k in ("status", "error", "clean_sha256", "tokens", "autofixed", "left_for_review",
                                             "unexplained_drops", "deleted", "check")}, ensure_ascii=False))
    if r["status"] == "validated":
        from clean_gdoc_md import clean_name
        print("SAVE_JSON " + json.dumps({"file_name": clean_name(TITLE, MIME), "text_content": open("clean.md", encoding="utf-8").read(),
                                         "mime_type": "text/markdown", "parent_id": PARENT}, ensure_ascii=False))
main()
```

With `FINAL = False` the cell prints the newest packet (new `rev`, new line numbers) for your next batch. If a batch is refused, it prints the errors and the packet for the text before that batch: fix the batch and run again. Set `FINAL = True` when you are done editing. Lost your batches? `BATCHES = []` prints the first packet again.

## Save, verify, clean up (outside the workbench)

1. **Never copy the document by hand.** Pull the payload out of cell B's output with a script:
   `python3 -c 'import json; s = json.load(open("out.json", encoding="utf-8"))["data"]["stdout"]; l = [x for x in s.splitlines() if x.startswith("SAVE_JSON ")][0]; open("save.json", "w", encoding="utf-8").write(l[10:])'`
   **Never overwrite:** if step 1's search showed a file already named `file_name` in the folder, change `file_name` in `save.json` to `<title> - clean (2).md` (or the next free number) with the same one-liner approach, never by retyping the text. Then `composio execute GOOGLEDRIVE_CREATE_FILE_FROM_TEXT -d @save.json` (add `--account`). Keep the returned `data.id`. If the error says the account lacks **permission** to add files to the folder, remove `parent_id` from `save.json`, save again (My Drive root), and say so in the report. Any other error (rate limit, quota, not found): stop and report it; do not save somewhere else.
2. Read it back: `GOOGLEDRIVE_DOWNLOAD_FILE` with `fileId` = the saved id; the link is `data.downloaded_file_content.s3url`. Hash it the same way the script does:
   `python3 -c 'import hashlib, sys, urllib.request; print(hashlib.sha256(urllib.request.urlopen(sys.argv[1]).read().replace(b"\r\n", b"\n")).hexdigest())' "<link>"`
   It must equal `clean_sha256`. If it does not, stop: report the saved file's id, and keep the temporary Doc.
3. Stamp the reuse key: `GOOGLEDRIVE_UPDATE_FILE_PUT` with `fileId` = the saved id and `description` = the reuse key from step 1. If it fails, the save still stands; say that next time's shortcut is lost. (Its reply does not show the description; read the file's metadata if you need to confirm it.)
4. Only after a match, and only for a PDF source: `GOOGLEDRIVE_TRASH_FILE` with `file_id` (snake case; this tool rejects `fileId`) = the temporary Doc id you wrote down, then `GOOGLEDRIVE_GET_FILE_METADATA` with `fields: "trashed"` must say `true`. Never trash anything else.
