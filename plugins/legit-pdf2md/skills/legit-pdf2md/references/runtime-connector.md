# Runtime: the Composio connector (MCP)

For Claude chat, Cowork, Claude Code and ChatGPT with Composio connected as a connector. Proven end to end on a 12-page PDF (09.23.26): three workbench cells, validated, saved beside the source, read back, temporary Doc trashed.

## Ground rules

- **Call the Drive tools by their known names; skip Composio's tool search.** One broad search returns about 138,000 characters and still missed the conversion tool. `COMPOSIO_SEARCH_TOOLS` also proposes its own plan for a PDF (download it, parse with `pdfplumber`): ignore it. `pdfplumber` has no OCR, so a scanned PDF comes back empty, and its output is not the export the script is built for.
- **Outside the workbench**, Drive tools run through `COMPOSIO_MULTI_EXECUTE_TOOL`: `{"tools": [{"tool_slug": "GOOGLEDRIVE_GET_FILE_METADATA", "arguments": {...}}]}`, plus the account (below).
- **Inside the workbench**, `run_composio_tool(slug, arguments, account=...)` is preloaded and returns `(result, error)`: `result["data"]` holds the answer, `error` is empty on success. Files under `/mnt/files` persist between calls on this path, which is what lets the three cells below share one run.
- **Accounts.** List them with `COMPOSIO_MANAGE_CONNECTIONS` (`{"toolkits": [{"name": "googledrive", "action": "list"}]}`). With more than one `ACTIVE`, Composio refuses Drive calls until you name one: pass its email, id or alias as `account`. If naming one returns a 400, retry without it. Start from the one marked `is_default`, and confirm with `GOOGLEDRIVE_GET_ABOUT` before any write.
- **Never use the workbench's `invoke_llm` helper.** You write the edits and the report yourself; a second model inside the sandbox would be judging wording nobody checks.
- **The first call of each tool in a sandbox prints its response schema** to the cell output. That is Composio's logging, not an error.
- **ChatGPT**: the same Composio tools appear through its Composio connector and everything below is identical. Use Composio for Drive even if ChatGPT's own Google Drive connection is also on.

## Cell 1: fetch, export, pipeline

Fill in the file id and the account (or `None` when only one account is ACTIVE). Use the script URL from SKILL.md.

```python
import json, os, subprocess, sys, requests
W = "/mnt/files/legit-pdf2md"; os.makedirs(W, exist_ok=True)
BASE = "<script URL from SKILL.md, ending in scripts/>"
FILE, ACCOUNT = "<file id>", "<account email or id, or None>"
for f in ("clean_gdoc_md.py", "drive_txn.py"):
    open(f"{W}/{f}", "w", encoding="utf-8").write(requests.get(BASE + f, timeout=60).text)
sys.path.insert(0, W)
import drive_txn
txn = drive_txn.Txn(run_composio_tool, ACCOUNT, FILE)
print(json.dumps({k: txn.open()[k] for k in ("name", "mimeType")}))
txn.export(f"{W}/export-{FILE}.md")
r = subprocess.run([sys.executable, f"{W}/clean_gdoc_md.py", "pipeline", f"{W}/export-{FILE}.md",
                    "--state", f"{W}/state-{FILE}.json"], capture_output=True, text=True)
print(r.stdout or r.stderr)
```

`drive_txn` makes the temporary Doc for a PDF in My Drive root and writes its id to the run's journal before using it, so a re-invoked skill or a later cell never makes a second one. The output is the packet (SKILL.md Step 2). If it already says `validated`, skip to cell 3.

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
W, FILE, ACCOUNT = "/mnt/files/legit-pdf2md", "<file id>", "<account email or id, or None>"
sys.path.insert(0, W)
import drive_txn, clean_gdoc_md
r = json.loads(subprocess.run([sys.executable, f"{W}/clean_gdoc_md.py", "pipeline", f"{W}/export-{FILE}.md",
                               "--state", f"{W}/state-{FILE}.json", "--final", "-o", f"{W}/clean-{FILE}.md"],
                              capture_output=True, text=True).stdout)
print(json.dumps({k: r.get(k) for k in ("status", "tokens", "autofixed", "left_for_review", "unexplained_drops", "check")}))
if r["status"] == "validated":
    txn = drive_txn.Txn(run_composio_tool, ACCOUNT, FILE)
    src = txn.j["source"]
    text = open(f"{W}/clean-{FILE}.md", encoding="utf-8").read()
    print(txn.save(text, r["clean_sha256"], clean_gdoc_md.clean_name(src["name"], src["mimeType"])))
    print(txn.cleanup())
```

- `save` refuses text that is not the text the check passed, saves beside the source, downloads it again and compares sha256. It returns where the file went: `beside the source`, or My Drive root with the reason (no permission to add files to the folder, or no folder visible to this account). Put that in the report.
- `cleanup` trashes only this run's temporary Doc, only after a verified save, and confirms Drive reports it trashed. For a Google Doc source there is nothing to trash.
- Any `DriveError` stops the run with a plain reason. Report it. A failed read-back names the saved file's id; the temporary Doc stays.
- If the journal records `possible_orphan` or `left_from_earlier_run`, tell the user the named temporary Doc may still be in their My Drive (it holds the document's text) and that they can trash it.

The link to the saved file is `https://drive.google.com/file/d/<saved id>/view`.
