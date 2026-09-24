# Runtime: the Composio connector (MCP)

For Claude chat, Cowork, Claude Code and ChatGPT with Composio connected as a connector. Proven end to end on a 12-page PDF (09.23.26): validated, saved beside the source, read back, temporary Doc trashed.

## Ground rules

- **Call the Drive tools by their known names; skip Composio's tool search.** One broad search returns about 138,000 characters and still missed the conversion tool. `COMPOSIO_SEARCH_TOOLS` also proposes its own plan for a PDF (download it, parse with `pdfplumber`): ignore it. `pdfplumber` has no OCR, so a scanned PDF comes back empty, and its output is not the export the script is built for.
- **Use the script and instructions from the URL in SKILL.md, never a copy already sitting in the sandbox** (an old clone of the repo can be there from an earlier run). The v0.2.0 flow uses `pipeline` and `apply-edits`; if what you are following says `strip` then `check`, you have an old copy. If your own web fetch cannot open the raw link, reading the same repository path at the same version through a GitHub connector is fine for SKILL.md and these references; with neither, fetch the file inside the workbench and print it (`print(requests.get(URL, timeout=60).text)`). The cells still fetch the scripts from the raw URL inside the workbench.
- **Outside the workbench** (Step 1's lookups), Drive tools run through `COMPOSIO_MULTI_EXECUTE_TOOL`: `{"tools": [{"tool_slug": "GOOGLEDRIVE_GET_FILE_METADATA", "arguments": {...}, "account": "<alias or account id>"}], "sync_response_to_workbench": false}`. `account` goes on each tool item.
- **Inside the workbench**, `run_composio_tool(slug, arguments, account=...)` is preloaded and returns `(result, error)`: `result["data"]` holds the answer, `error` is empty on success.
- **The sandbox can be replaced between any two cells, with `/mnt/files` empty** (seen three times in one afternoon). So nothing may depend on files from an earlier cell. What survives is what you keep in the chat: the **temporary Doc id** the start cell prints, and **every edit batch** you have written. The continue cell rebuilds everything else from those.
- **Accounts.** List them with `COMPOSIO_MANAGE_CONNECTIONS` (`{"toolkits": [{"name": "googledrive", "action": "list"}]}`). With one `ACTIVE` account, name none (`ACCOUNT = None`). With several, Composio refuses Drive calls until you name one: use its alias or account id (in the workbench the account's email works too). Start from the one marked `is_default`, and use the same account, written the same way, in every cell.
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
import importlib, drive_txn, clean_gdoc_md
importlib.reload(drive_txn); importlib.reload(clean_gdoc_md)   # a kept kernel can hold an older copy
about, err = run_composio_tool("GOOGLEDRIVE_GET_ABOUT", {}, account=ACCOUNT) if ACCOUNT else run_composio_tool("GOOGLEDRIVE_GET_ABOUT", {})
print("signed in as:", json.dumps((about or {}).get("data", {}).get("user", {}).get("emailAddress")), err or "")
txn = drive_txn.Txn(run_composio_tool, ACCOUNT, FILE)
src = txn.open()
hit = txn.reusable(clean_gdoc_md.clean_name(src["name"], src["mimeType"]))
if hit:   # this exact version of the source was cleaned before: nothing to do
    print("REUSED", json.dumps(hit), txn.j.get("saved_ok") and txn.cleanup(), "LEFTOVERS", txn.temps() + txn.j.get("leftovers", []))
else:
    try:
        txn.export(f"{W}/export-{FILE}.md", OCR)
    finally:   # printed even if the export fails after the copy
        print(json.dumps({"name": src["name"], "mimeType": src["mimeType"], "TEMP_DOC": txn.j.get("temp_doc"),
                          "LEFTOVERS": txn.j.get("leftovers")}))
    r = subprocess.run([sys.executable, f"{W}/clean_gdoc_md.py", "pipeline", f"{W}/export-{FILE}.md",
                        "--state", f"{W}/state-{FILE}.json"], capture_output=True, text=True)
    print(r.stdout or r.stderr)
```

If it prints `REUSED`, this skill already cleaned this exact version of the file (the clean file's Drive description carries the source's id and last-modified time): report that file and its link, and stop. No temporary Doc was made; if `LEFTOVERS` lists any, tell the user as below.

**Write `TEMP_DOC` into your reply straight away** (for a PDF; a Google Doc source has none). It holds the document's full text until it is trashed. The copy is also stamped in its Drive description with the source's id and version, so a later cell can find it again, but the id in the chat is the direct record. `LEFTOVERS` lists temporary Docs from an earlier run on this file (an older version, or a duplicate copy): they are not this run's and are never trashed by it, so tell the user they are in My Drive (named `<title without .pdf> - temp`) and can be trashed. The rest of the output is the packet (SKILL.md Step 2). If the packet already says `validated`, run the continue cell with `BATCHES = []` and `FINAL = True`, then `SAVE = True`.

## Continue cell: edits, final check, save, clean up

Every cell after the start cell is this one. It is self-contained: it rebuilds the run from the temporary Doc and replays every batch you have written, in order, so it works in a fresh sandbox. Keep all batches in `BATCHES`, oldest first. **Paste the whole cell every time, with every value filled in; never rely on variables left from an earlier cell.** The kernel can be shared with another run in the same account, which can change them.

```python
import json, os, subprocess, sys, requests
W = "/mnt/files/legit-pdf2md"; os.makedirs(W, exist_ok=True)
BASE = "<script URL from SKILL.md, ending in scripts/>"
FILE, ACCOUNT, OCR = "<file id>", None, "en"
TEMP = None   # a PDF: the TEMP_DOC id from the start cell, in quotes. A Google Doc source: None, no quotes
BATCHES = [ {"rev": "<rev>", "edits": [ ... ]} ]
FINAL = False   # True once no block you mean to change is left: runs the final check
SAVE = False    # True only after you have read the final check's `deleted`: saves, reads back, cleans up
for f in ("clean_gdoc_md.py", "drive_txn.py"):
    got = requests.get(BASE + f, timeout=60); got.raise_for_status()
    open(f"{W}/{f}", "w", encoding="utf-8").write(got.text)
sys.path.insert(0, W)
import importlib, drive_txn, clean_gdoc_md
importlib.reload(drive_txn); importlib.reload(clean_gdoc_md)   # a kept kernel can hold an older copy
EXPORT, STATE, CLEAN = f"{W}/export-{FILE}.md", f"{W}/state-{FILE}.json", f"{W}/clean-{FILE}.md"
txn = drive_txn.Txn(run_composio_tool, ACCOUNT, FILE, temp_doc=TEMP)
src = txn.open()
txn.export(EXPORT, OCR, copy=False)   # never makes a new temporary Doc; the same Doc exports the same text
if os.path.exists(STATE):
    os.remove(STATE)
def run(*a):
    p = subprocess.run([sys.executable, f"{W}/clean_gdoc_md.py", *a], capture_output=True, text=True)
    if not p.stdout:
        raise RuntimeError(p.stderr[-2000:])   # the script crashed: a real error
    return json.loads(p.stdout)
def main():   # plain returns: a stopped cell must not read as a failed one
    out = run("pipeline", EXPORT, "--state", STATE)
    for b in BATCHES:
        json.dump(b, open(f"{W}/edits-{FILE}.json", "w", encoding="utf-8"), ensure_ascii=False)
        out = run("apply-edits", f"{W}/edits-{FILE}.json", "--state", STATE)
        if not out["applied"]:
            break
    if not FINAL or not out.get("applied", True):
        return print(json.dumps(out, ensure_ascii=False))   # errors, or the next packet
    r = run("pipeline", EXPORT, "--state", STATE, "--final", "-o", CLEAN)
    print(json.dumps({k: r.get(k) for k in ("status", "error", "clean_sha256", "tokens", "autofixed", "left_for_review",
                                             "unexplained_drops", "deleted", "check")}, ensure_ascii=False))
    if r["status"] == "validated" and SAVE:
        text = open(CLEAN, encoding="utf-8").read()
        print(txn.save(text, r["clean_sha256"], clean_gdoc_md.clean_name(src["name"], src["mimeType"])))
        print(txn.cleanup())
main()
```

- With `FINAL = False` the cell prints the newest packet (new `rev`, new line numbers, new block ids) for your next batch. A refused batch prints its errors and the packet for the text before it: fix that batch and run again.
- With `FINAL = True` it runs the final check and prints it. Read `deleted` (SKILL.md Step 4); if anything there is real content, put it back with another batch. When it is right, run the cell again with `SAVE = True` as well: only then is anything written to Drive.
- `save` refuses text that is not the text the check passed, then saves beside the source, downloads it again and compares sha256. It returns where the file went: `beside the source`, or My Drive root with the reason (no permission to add files to the folder, or no folder visible to this account). Put that in the report. Before saving it looks for an identical file already in the folder, so running this cell again, even in a new sandbox, never saves twice. If another file already has the name, it saves `<title> - clean (2).md` (then `(3)`, and so on): it never overwrites. After the read-back matches, it writes the reuse key into the file's description (`reuse_key: true`); if Drive refuses that, the save still stands and only next time's shortcut is lost.
- `cleanup` trashes only this run's temporary Doc, only after a verified save, and confirms Drive reports it trashed. For a Google Doc source there is nothing to trash.
- Any `DriveError` stops with a plain reason; report it. "No temporary Doc for this version" means neither `TEMP` nor a search of My Drive found this run's copy: run the start cell again. "In the trash" means this run finished if its clean file was saved. "The source changed since this run started" means the PDF was edited mid-run: start over with the start cell, then continue with its new `TEMP_DOC` and `BATCHES = []` (the old temporary Doc is reported as a leftover). A Google Doc source edited mid-run shows up instead as a refused batch (a new `rev`): write the edits again from the packet it prints. A failed read-back names the saved file's id, and the temporary Doc stays. "This PDF has N pages" means it is over Google's 80-page limit: nothing was copied; tell the user to split it and run each part.

The link to the saved file is `https://drive.google.com/file/d/<saved id>/view`.

## Resuming after a context reset

Everything you need is in the chat: the file id, the account, `TEMP_DOC`, and your batches. Run the continue cell with them (`FINAL = False` prints the current packet). If `TEMP_DOC` is lost from the chat as well, run it with `TEMP = None`: it finds this run's temporary Doc in My Drive by the stamp in its description, and never makes a second one. If your batches are lost, `BATCHES = []` prints the first packet again; write the edits again from it.
