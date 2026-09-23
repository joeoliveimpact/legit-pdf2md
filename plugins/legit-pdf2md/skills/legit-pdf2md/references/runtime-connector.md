# Runtime: the Composio connector (MCP)

For Claude chat, Cowork, Claude Code and ChatGPT with Composio connected as a connector. Proven end to end on a 12-page PDF (09.23.26): three workbench cells, validated, saved beside the source, read back, temporary Doc trashed.

## Ground rules

- **Call the Drive tools by their known names; skip Composio's tool search.** One broad search returns about 138,000 characters and still missed the conversion tool. `COMPOSIO_SEARCH_TOOLS` also proposes its own plan for a PDF (download it, parse with `pdfplumber`): ignore it. `pdfplumber` has no OCR, so a scanned PDF comes back empty, and its output is not the export the script is built for.
- **Outside the workbench** (Step 1's lookups), Drive tools run through `COMPOSIO_MULTI_EXECUTE_TOOL`: `{"tools": [{"tool_slug": "GOOGLEDRIVE_GET_FILE_METADATA", "arguments": {...}, "account": "<alias or account id>"}], "sync_response_to_workbench": false}`. `account` goes on each tool item.
- **Inside the workbench**, `run_composio_tool(slug, arguments, account=...)` is preloaded and returns `(result, error)`: `result["data"]` holds the answer, `error` is empty on success. Files under `/mnt/files` persist between calls on this path, which is what lets the three cells below share one run.
- **Accounts.** List them with `COMPOSIO_MANAGE_CONNECTIONS` (`{"toolkits": [{"name": "googledrive", "action": "list"}]}`). With one `ACTIVE` account, name none (`ACCOUNT = None`). With several, Composio refuses Drive calls until you name one: use its alias or account id (in the workbench the account's email works too). Start from the one marked `is_default`. The whole run uses one account: the journal keeps it, and a later cell naming another is refused.
- **Never use the workbench's `invoke_llm` helper.** You write the edits and the report yourself; a second model inside the sandbox would be judging wording nobody checks.
- **The first call of each tool in a sandbox prints its response schema** to the cell output. That is Composio's logging, not an error.
- **ChatGPT**: the same Composio tools appear through its Composio connector and everything below is identical. Use Composio for Drive even if ChatGPT's own Google Drive connection is also on.

## Cell 1: fetch, check the account, export, pipeline

Fill in the file id, the account (`None` without quotes when only one is ACTIVE) and the OCR language. Use the script URL from SKILL.md.

```python
import json, os, subprocess, sys, requests
W = "/mnt/files/legit-pdf2md"; os.makedirs(W, exist_ok=True)
BASE = "<script URL from SKILL.md, ending in scripts/>"
FILE, ACCOUNT, OCR = "<file id>", None, "en"
for f in ("clean_gdoc_md.py", "drive_txn.py"):
    got = requests.get(BASE + f, timeout=60); got.raise_for_status()
    open(f"{W}/{f}", "w", encoding="utf-8").write(got.text)
sys.path.insert(0, W)
import drive_txn
about, err = run_composio_tool("GOOGLEDRIVE_GET_ABOUT", {}, account=ACCOUNT) if ACCOUNT else run_composio_tool("GOOGLEDRIVE_GET_ABOUT", {})
print("signed in as:", json.dumps((about or {}).get("data", {}).get("user", {}).get("emailAddress")), err or "")
txn = drive_txn.Txn(run_composio_tool, ACCOUNT, FILE)
src = txn.open()
print(json.dumps({"name": src["name"], "mimeType": src["mimeType"], "journal": {k: v for k, v in txn.j.items() if k != "source"}}))
txn.export(f"{W}/export-{FILE}.md", OCR)
r = subprocess.run([sys.executable, f"{W}/clean_gdoc_md.py", "pipeline", f"{W}/export-{FILE}.md",
                    "--state", f"{W}/state-{FILE}.json"], capture_output=True, text=True)
print(r.stdout or r.stderr)
```

`drive_txn` makes the temporary Doc for a PDF in My Drive root and writes its id to the run's journal before using it, so running this cell again, or a re-invoked skill, never makes a second one. The output is the packet (SKILL.md Step 2). If it already says `validated`, skip to cell 3.

## Cell 2: apply your edits

Paste your edits as a Python literal (keeps quotes and backslashes intact). Repeat this cell until no block you mean to change is left; each run prints the next packet.

```python
import json, subprocess, sys
W, FILE = "/mnt/files/legit-pdf2md", "<file id>"
EDITS = {"rev": "<rev>", "edits": [ ... ]}
json.dump(EDITS, open(f"{W}/edits.json", "w", encoding="utf-8"), ensure_ascii=False)
r = subprocess.run([sys.executable, f"{W}/clean_gdoc_md.py", "apply-edits", f"{W}/edits.json",
                    "--state", f"{W}/state-{FILE}.json"], capture_output=True, text=True)
print(r.stdout or r.stderr)
```

## Cell 3: final check, save, verify, clean up

```python
import json, subprocess, sys
W, FILE, ACCOUNT = "/mnt/files/legit-pdf2md", "<file id>", None
sys.path.insert(0, W)
import drive_txn, clean_gdoc_md
out = subprocess.run([sys.executable, f"{W}/clean_gdoc_md.py", "pipeline", f"{W}/export-{FILE}.md", "--state",
                      f"{W}/state-{FILE}.json", "--final", "-o", f"{W}/clean-{FILE}.md"], capture_output=True, text=True)
r = json.loads(out.stdout) if out.stdout else {"status": "failed", "error": out.stderr[-2000:]}
print(json.dumps({k: r.get(k) for k in ("status", "error", "tokens", "autofixed", "left_for_review",
                                         "unexplained_drops", "deleted", "check")}, ensure_ascii=False))
if r["status"] == "validated":
    txn = drive_txn.Txn(run_composio_tool, ACCOUNT, FILE)
    src = txn.j["source"]
    text = open(f"{W}/clean-{FILE}.md", encoding="utf-8").read()
    print(txn.save(text, r["clean_sha256"], clean_gdoc_md.clean_name(src["name"], src["mimeType"])))
    print(txn.cleanup())
```

- `save` refuses text that is not the text the check passed, saves beside the source, downloads it again and compares sha256. It returns where the file went: `beside the source`, or My Drive root with the reason (no permission to add files to the folder, or no folder visible to this account). Put that in the report. Run again after a verified save, it returns the same file: it never saves twice.
- `cleanup` trashes only this run's temporary Doc, only after a verified save, and confirms Drive reports it trashed. For a Google Doc source there is nothing to trash.
- Any `DriveError` stops the run with a plain reason. Report it. A failed read-back names the saved file's id; the temporary Doc stays.

The link to the saved file is `https://drive.google.com/file/d/<saved id>/view`.

## Resuming a run

Cell 1 prints the journal. Its fields say where the run is:
- `temp_doc`: the temporary Doc exists (PDF sources). No `temp_doc` on a PDF: cell 1 has not got past the copy.
- `saved` with `saved_ok: true`: the clean file is saved and verified. `saved_ok: false`: the save was made but its read-back failed; report the id and stop.
- `temp_trashed: true`: cleanup is done; the run is finished.
- `possible_orphan`: an earlier attempt may have made a temporary Doc whose id was lost. Tell the user its name so they can trash it (it holds the document's text).

To pick up the edits, run `pipeline` without `--final` (cell 1's last command, or on its own): it resumes from the state file and prints the current packet. Every cell is safe to run again. Only a finished run (`temp_trashed`, or a Doc source with `saved_ok`) starts over, and that is a new run.
