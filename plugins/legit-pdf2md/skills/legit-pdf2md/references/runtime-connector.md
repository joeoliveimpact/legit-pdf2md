# Runtime: the Composio connector (MCP)

For Claude chat, Cowork, Claude Code and ChatGPT with Composio connected as a connector. Proven end to end on a 12-page PDF (09.23.26): validated, saved beside the source, read back, temporary Doc trashed.

## Ground rules

- **Call the Drive tools by their known names; skip Composio's tool search.** One broad search returns about 138,000 characters and still missed the conversion tool. `COMPOSIO_SEARCH_TOOLS` also proposes its own plan for a PDF (download it, parse with `pdfplumber`): ignore it. `pdfplumber` has no OCR, so a scanned PDF comes back empty, and its output is not the export the script is built for.
- **Use the script and instructions from the URL in SKILL.md, never a copy already sitting in the sandbox** (an old clone of the repo can be there from an earlier run). The v0.2.0 flow uses `pipeline` and `apply-edits`; if what you are following says `strip` then `check`, you have an old copy. If your own web fetch cannot open the raw link, reading the same repository path at the same version through a GitHub connector is fine for SKILL.md and these references; the cells still fetch the scripts from the raw URL inside the workbench.
- **Outside the workbench** (Step 1's lookups), Drive tools run through `COMPOSIO_MULTI_EXECUTE_TOOL`: `{"tools": [{"tool_slug": "GOOGLEDRIVE_GET_FILE_METADATA", "arguments": {...}, "account": "<alias or account id>"}], "sync_response_to_workbench": false}`. `account` goes on each tool item.
- **Inside the workbench**, `run_composio_tool(slug, arguments, account=...)` is preloaded and returns `(result, error)`: `result["data"]` holds the answer, `error` is empty on success.
- **The sandbox can be replaced between any two cells, with `/mnt/files` empty** (seen three times in one afternoon). So nothing may depend on files from an earlier cell. What survives is what you keep in the chat: the **temporary Doc id** the start cell prints, and **every edit batch** you have written. The continue cell rebuilds everything else from those.
- **Accounts.** List them with `COMPOSIO_MANAGE_CONNECTIONS` (`{"toolkits": [{"name": "googledrive", "action": "list"}]}`). With one `ACTIVE` account, name none (`ACCOUNT = None`). With several, Composio refuses Drive calls until you name one: use its alias or account id (in the workbench the account's email works too). Start from the one marked `is_default`, and use the same account in every cell.
- **Never use the workbench's `invoke_llm` helper.** You write the edits and the report yourself; a second model inside the sandbox would be judging wording nobody checks.
- **The first call of each tool in a sandbox prints its response schema** to the cell output. That is Composio's logging, not an error.
- **ChatGPT**: the same Composio tools appear through its Composio connector and everything below is identical. Use Composio for Drive even if ChatGPT's own Google Drive connection is also on.

## Start cell: check the account, export, pipeline

Run once per document. Fill in the file id, the account (`None` without quotes when only one is ACTIVE) and the OCR language.

```python
import json, os, subprocess, sys, requests
W = "/mnt/files/legit-pdf2md"; os.makedirs(W, exist_ok=True)
BASE = "<script URL from SKILL.md, ending in scripts/>"
FILE, ACCOUNT, OCR = "<file id>", None, "en"
for f in ("clean_gdoc_md.py", "drive_txn.py"):
    got = requests.get(BASE + f, timeout=60); got.raise_for_status()
    open(f"{W}/{f}", "w", encoding="utf-8").write(got.text)
sys.path.insert(0, W)
import drive_txn, clean_gdoc_md
about, err = run_composio_tool("GOOGLEDRIVE_GET_ABOUT", {}, account=ACCOUNT) if ACCOUNT else run_composio_tool("GOOGLEDRIVE_GET_ABOUT", {})
print("signed in as:", json.dumps((about or {}).get("data", {}).get("user", {}).get("emailAddress")), err or "")
txn = drive_txn.Txn(run_composio_tool, ACCOUNT, FILE)
src = txn.open()
hit = txn.reusable(clean_gdoc_md.clean_name(src["name"], src["mimeType"]))
if hit:   # this exact version of the source was cleaned before: nothing to do
    print("REUSED", json.dumps(hit)); raise SystemExit
txn.export(f"{W}/export-{FILE}.md", OCR)
print(json.dumps({"name": src["name"], "mimeType": src["mimeType"], "TEMP_DOC": txn.j.get("temp_doc")}))
r = subprocess.run([sys.executable, f"{W}/clean_gdoc_md.py", "pipeline", f"{W}/export-{FILE}.md",
                    "--state", f"{W}/state-{FILE}.json"], capture_output=True, text=True)
print(r.stdout or r.stderr)
```

If it prints `REUSED`, this skill already cleaned this exact version of the file (the clean file's Drive description carries the source's id and last-modified time): report that file and its link, and stop. No temporary Doc was made.

**Write `TEMP_DOC` into your reply straight away** (for a PDF; a Google Doc source has none). It is the only record of the temporary Doc that survives a sandbox reset, and it holds the document's full text until it is trashed. The rest of the output is the packet (SKILL.md Step 2).

## Continue cell: edits, final check, save, clean up

Every cell after the start cell is this one. It is self-contained: it rebuilds the run from the temporary Doc and replays every batch you have written, in order, so it works in a fresh sandbox. Keep all batches in `BATCHES`, oldest first.

```python
import json, os, subprocess, sys, requests
W = "/mnt/files/legit-pdf2md"; os.makedirs(W, exist_ok=True)
BASE = "<script URL from SKILL.md, ending in scripts/>"
FILE, ACCOUNT, OCR = "<file id>", None, "en"
TEMP = "<TEMP_DOC from the start cell, or None for a Google Doc source>"
BATCHES = [ {"rev": "<rev>", "edits": [ ... ]} ]
FINAL = False   # True once no block you mean to change is left
for f in ("clean_gdoc_md.py", "drive_txn.py"):
    got = requests.get(BASE + f, timeout=60); got.raise_for_status()
    open(f"{W}/{f}", "w", encoding="utf-8").write(got.text)
sys.path.insert(0, W)
import drive_txn, clean_gdoc_md
EXPORT, STATE, CLEAN = f"{W}/export-{FILE}.md", f"{W}/state-{FILE}.json", f"{W}/clean-{FILE}.md"
txn = drive_txn.Txn(run_composio_tool, ACCOUNT, FILE, temp_doc=TEMP)
src = txn.open()
if not os.path.exists(EXPORT):
    txn.export(EXPORT, OCR, copy=False)   # never makes a new temporary Doc
if os.path.exists(STATE):
    os.remove(STATE)
def run(*a):
    p = subprocess.run([sys.executable, f"{W}/clean_gdoc_md.py", *a], capture_output=True, text=True)
    if not p.stdout:
        print(p.stderr); raise SystemExit
    return json.loads(p.stdout)
out = run("pipeline", EXPORT, "--state", STATE)
for b in BATCHES:
    json.dump(b, open(f"{W}/edits.json", "w", encoding="utf-8"), ensure_ascii=False)
    out = run("apply-edits", f"{W}/edits.json", "--state", STATE)
    if not out["applied"]:
        break
if not FINAL or not out.get("applied", True):
    print(json.dumps(out, ensure_ascii=False)); raise SystemExit   # errors, or the next packet
r = run("pipeline", EXPORT, "--state", STATE, "--final", "-o", CLEAN)
print(json.dumps({k: r.get(k) for k in ("status", "error", "tokens", "autofixed", "left_for_review",
                                         "unexplained_drops", "deleted", "check")}, ensure_ascii=False))
if r["status"] == "validated":
    text = open(CLEAN, encoding="utf-8").read()
    print(txn.save(text, r["clean_sha256"], clean_gdoc_md.clean_name(src["name"], src["mimeType"])))
    print(txn.cleanup())
```

- With `FINAL = False` the cell prints the newest packet (new `rev`, new line numbers) for your next batch. A refused batch prints its errors and the packet for the text before it: fix that batch and run again.
- `save` refuses text that is not the text the check passed, then saves beside the source, downloads it again and compares sha256. It returns where the file went: `beside the source`, or My Drive root with the reason (no permission to add files to the folder, or no folder visible to this account). Put that in the report. Before saving it looks for an identical file already in the folder, so running this cell again, even in a new sandbox, never saves twice. If another file already has the name, it saves `<title> - clean (2).md` (then `(3)`, and so on): it never overwrites. After the read-back matches, it writes the reuse key into the file's description (`reuse_key: true`); if Drive refuses that, the save still stands and only next time's shortcut is lost.
- `cleanup` trashes only this run's temporary Doc, only after a verified save, and confirms Drive reports it trashed. For a Google Doc source there is nothing to trash.
- Any `DriveError` stops with a plain reason; report it. "No temporary Doc id" means `TEMP` is missing: put back the id from the start cell. "Already trashed" means this run finished. A failed read-back names the saved file's id, and the temporary Doc stays.

The link to the saved file is `https://drive.google.com/file/d/<saved id>/view`.

## Resuming after a context reset

Everything you need is in the chat: the file id, the account, `TEMP_DOC`, and your batches. Run the continue cell with them (`FINAL = False` prints the current packet). If `TEMP_DOC` is lost from the chat as well, do not run the start cell again, since that would make a second copy: tell the user a Doc named `<title> - temp` is in their My Drive holding the document's text, and that they can trash it.
