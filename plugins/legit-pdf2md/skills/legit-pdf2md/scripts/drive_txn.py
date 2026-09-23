"""Drive steps for legit-pdf2md on the Composio connector: one run's copy, export, save and cleanup.

Runs inside COMPOSIO_REMOTE_WORKBENCH, where run_composio_tool is preloaded and /mnt/files persists between
calls. Pass run_composio_tool in as `call`. Every id this run creates goes into its journal before anything
else happens, so cleanup trashes exactly the temporary Doc this run made and nothing else, and only after the
clean file was saved, read back and matched the text that passed the check. Standard library + requests.

  txn = Txn(run_composio_tool, account="me@example.com")
  txn.open(file_id)                   # metadata, kept in the journal
  txn.export("export.md")             # a PDF is copied to a temporary Doc (OCR) in My Drive first
  txn.save(text, clean_sha256, name)  # save beside the source, read back, compare hashes
  txn.cleanup()                       # trash the temporary Doc, confirm it is trashed
"""
import hashlib, json, os

DOC = "application/vnd.google-apps.document"
JOURNAL = "/mnt/files/legit-pdf2md/txn.json"
NO_ROOM = ("insufficient", "permission", "forbidden", "403", "cannot add", "not have")   # can't save beside it


class DriveError(Exception):
    pass


def sha(text):
    return hashlib.sha256(text.replace("\r\n", "\n").encode("utf-8")).hexdigest()


def _find(data, key):
    """The first value under key anywhere in a tool response (Composio nests links a few levels down)."""
    if isinstance(data, dict):
        if data.get(key):
            return data[key]
        data = list(data.values())
    if isinstance(data, list):
        for v in data:
            hit = _find(v, key)
            if hit:
                return hit
    return None


def _fetch(url):
    import requests
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    return r.content.decode("utf-8")


class Txn:
    def __init__(self, call, account=None, journal=JOURNAL, test_folder=None, fetch=_fetch):
        self.call, self.account, self.path, self.test_folder, self.fetch = call, account, journal, test_folder, fetch
        self.j = json.load(open(journal, encoding="utf-8")) if os.path.exists(journal) else {}

    def _save_journal(self):
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        with open(self.path + ".tmp", "w", encoding="utf-8") as f:
            json.dump(self.j, f)
        os.replace(self.path + ".tmp", self.path)

    def _run(self, slug, args):
        r, err = self.call(slug, args, account=self.account) if self.account else self.call(slug, args)
        data = r.get("data") if isinstance(r, dict) else None
        if err or not data:
            raise DriveError(f"{slug}: {err or (r.get('error') if isinstance(r, dict) else r) or 'no data'}")
        return data

    def open(self, file_id):
        """The source's metadata. A new source, or the same one after a finished run, starts a new journal (an
        earlier temp Doc that was never trashed is reported, not trashed: it may belong to a run still going)."""
        meta = self._run("GOOGLEDRIVE_GET_FILE_METADATA", {"fileId": file_id, "supportsAllDrives": True,
                         "fields": "id,name,mimeType,parents,driveId,modifiedTime"})
        if self.j.get("source", {}).get("id") != file_id or self.j.get("saved_ok"):
            left = self.j.get("temp_doc") if not self.j.get("temp_trashed") else None
            self.j = {"source": meta, **({"left_from_earlier_run": left} if left else {})}
            self._save_journal()
        return meta

    def export(self, path):
        """Write the source's Markdown export to path. A PDF becomes a temporary Doc first (Google's OCR reads
        scanned pages), made in the user's private My Drive root and logged before it is used."""
        src = self.j["source"]
        doc = src["id"]
        if src["mimeType"] != DOC:
            if not self.j.get("temp_doc"):
                name = src["name"][:-4] if src["name"].lower().endswith(".pdf") else src["name"]
                data = self._run("GOOGLEDRIVE_COPY_FILE_ADVANCED", {"fileId": doc, "mimeType": DOC, "ocrLanguage": "en",
                                 "supportsAllDrives": True, "name": f"{name} - temp", "parents": ["root"]})
                self.j["temp_doc"] = _find(data, "id")
                if not self.j["temp_doc"]:
                    raise DriveError("the copy returned no id, so the temporary Doc cannot be tracked; look for "
                                     f"'{name} - temp' in My Drive and trash it by hand")
                self._save_journal()
            doc = self.j["temp_doc"]
        url = _find(self._run("GOOGLEDRIVE_EXPORT_GOOGLE_WORKSPACE_FILE", {"fileId": doc, "mimeType": "text/markdown"}), "s3url")
        if not url:
            raise DriveError("the export returned no download link")
        text = self.fetch(url)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        self.j["export_sha256"] = sha(text)
        self._save_journal()
        return path

    def save(self, text, clean_sha256, name):
        """Save beside the source, read it back and compare. Returns where it went. Raises, and leaves the
        temporary Doc alone, if the text is not the checked text or the read-back differs."""
        if sha(text) != clean_sha256:
            raise DriveError("this text is not the text that passed the check (hash differs); not saved")
        parent = (self.j["source"].get("parents") or [None])[0]
        if self.test_folder and parent != self.test_folder:
            raise DriveError(f"test mode: the source is not in the test folder {self.test_folder}; not saved")
        where = "beside the source"
        try:
            data = self._run("GOOGLEDRIVE_CREATE_FILE_FROM_TEXT", {"file_name": name, "text_content": text,
                             "mime_type": "text/markdown", **({"parent_id": parent} if parent else {})})
        except DriveError as e:
            if self.test_folder or not parent or not any(w in str(e).lower() for w in NO_ROOM):
                raise
            data = self._run("GOOGLEDRIVE_CREATE_FILE_FROM_TEXT", {"file_name": name, "text_content": text,
                             "mime_type": "text/markdown"})
            where = "My Drive root (no permission to add files to the source's folder)"
        saved = _find(data, "id")
        if not saved:
            raise DriveError("the save returned no file id; check Drive before running again")
        self.j.update(saved={"id": saved, "name": name, "where": where}, saved_ok=False)
        self._save_journal()
        url = _find(self._run("GOOGLEDRIVE_DOWNLOAD_FILE", {"fileId": saved}), "s3url")
        back = self.fetch(url) if url else ""
        if sha(back) != clean_sha256:
            raise DriveError(f"read-back of {saved} does not match the checked text; the temporary Doc is kept")
        self.j["saved_ok"] = True
        self._save_journal()
        return self.j["saved"]

    def cleanup(self):
        """Trash this run's temporary Doc, only after a verified save, and confirm it is trashed."""
        doc = self.j.get("temp_doc")
        if not doc or self.j.get("temp_trashed"):
            return {"temp_doc": doc, "trashed": bool(doc)}
        if not self.j.get("saved_ok"):
            raise DriveError("the clean file has not been saved and verified; the temporary Doc stays")
        if doc == self.j["source"]["id"]:
            raise DriveError("refusing to trash the source file")
        self._run("GOOGLEDRIVE_TRASH_FILE", {"file_id": doc, "supportsAllDrives": True})
        meta = self._run("GOOGLEDRIVE_GET_FILE_METADATA", {"fileId": doc, "fields": "trashed", "supportsAllDrives": True})
        if meta.get("trashed") is not True:
            raise DriveError(f"trashed {doc}, but Drive does not report it trashed")
        self.j["temp_trashed"] = True
        self._save_journal()
        return {"temp_doc": doc, "trashed": True}
