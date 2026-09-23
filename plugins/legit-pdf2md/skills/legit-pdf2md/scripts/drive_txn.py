"""Drive steps for legit-pdf2md on the Composio connector: one run's copy, export, save and cleanup.

Runs inside COMPOSIO_REMOTE_WORKBENCH, where run_composio_tool is preloaded and /mnt/files persists between
calls. Pass run_composio_tool in as `call`. Each source file gets its own journal, and every id this run
creates goes into it before anything else happens, so cleanup trashes exactly the temporary Doc this run made
and nothing else, and only after the clean file was saved, read back and matched the text that passed the
check. Standard library + requests.

  txn = Txn(run_composio_tool, "me@example.com", file_id)
  txn.open()                          # metadata, kept in the journal
  txn.export("export.md")             # a PDF is copied to a temporary Doc (OCR) in My Drive first
  txn.save(text, clean_sha256, name)  # save beside the source, read back, compare hashes
  txn.cleanup()                       # trash the temporary Doc, confirm it is trashed

A later cell builds Txn with the same file id and carries on from the journal (test mode included).
"""
import hashlib, json, os, re

DOC = "application/vnd.google-apps.document"
JOURNALS = "/mnt/files/legit-pdf2md"


class DriveError(Exception):
    pass


def sha(text):
    return hashlib.sha256(text.replace("\r\n", "\n").encode("utf-8")).hexdigest()


def _find(data, key):
    """The first value under key anywhere in a tool response (Composio nests download links a level down)."""
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


def _no_room(err):
    """A save refused because this account may not add files to the folder. Rate limits, quotas and missing
    files are other failures: those stop the run instead of saving somewhere else."""
    e = str(err).lower()
    return ("permission" in e or "cannot add" in e) and not any(w in e for w in ("rate limit", "quota", "not found"))


def _fetch(url):
    import requests
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    return r.content.decode("utf-8")


class Txn:
    def __init__(self, call, account, source, test_folder=None, journals=JOURNALS, fetch=_fetch):
        self.call, self.account, self.source, self.fetch = call, account, source, fetch
        self.path = os.path.join(journals, "txn-" + re.sub(r"[^\w-]", "_", source) + ".json")
        self.j = json.load(open(self.path, encoding="utf-8")) if os.path.exists(self.path) else {}
        live = {} if self._finished() else self.j   # a finished run pins nothing on the next one
        if test_folder and live.get("test_folder") not in (None, test_folder):
            raise DriveError(f"this run is in test mode for folder {live['test_folder']}, not {test_folder}")
        if account and live.get("account") not in (None, account):   # one run, one Google account
            raise DriveError(f"this run uses the account {live['account']}, not {account}")
        self.test_folder = test_folder or live.get("test_folder")   # a later cell cannot drop test mode
        self.account = account or live.get("account")

    def _finished(self):
        return bool(self.j.get("saved_ok") and (self.j.get("temp_trashed") or not self.j.get("temp_doc")))

    def _save_journal(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path + ".tmp", "w", encoding="utf-8") as f:
            json.dump(self.j, f)
        os.replace(self.path + ".tmp", self.path)

    def _run(self, slug, args):
        r, err = self.call(slug, args, account=self.account) if self.account else self.call(slug, args)
        data = r.get("data") if isinstance(r, dict) else None
        if err or not data:
            raise DriveError(f"{slug}: {err or (r.get('error') if isinstance(r, dict) else r) or 'no data'}")
        return data

    def open(self):
        """The source's metadata. An unfinished run carries on from its journal (a verified save whose temp Doc
        is not trashed yet is unfinished: cleanup still has to run). Only a finished run starts a new one."""
        meta = self._run("GOOGLEDRIVE_GET_FILE_METADATA", {"fileId": self.source, "supportsAllDrives": True,
                         "fields": "id,name,mimeType,parents,driveId,modifiedTime"})
        if not self.j or self._finished():
            self.j = {k: v for k, v in (("test_folder", self.test_folder), ("account", self.account)) if v}
        self.j["source"] = meta
        self._save_journal()
        return meta

    def export(self, path, ocr_language="en"):
        """Write the source's Markdown export to path. A PDF becomes a temporary Doc first (Google's OCR reads
        scanned pages, in ocr_language), made in the user's private My Drive root and logged before it is used."""
        src = self.j["source"]
        doc = src["id"]
        if src["mimeType"] != DOC:
            if not self.j.get("temp_doc"):
                name = (src["name"][:-4] if src["name"].lower().endswith(".pdf") else src["name"]) + " - temp"
                if self.j.get("copy_started"):   # a crash between a copy and its log: that Doc may exist
                    self.j["possible_orphan"] = f"'{self.j['copy_started']}' in My Drive (a copy whose id was lost)"
                self.j["copy_started"] = name
                self._save_journal()
                data = self._run("GOOGLEDRIVE_COPY_FILE_ADVANCED", {"fileId": doc, "mimeType": DOC, "ocrLanguage": ocr_language,
                                 "supportsAllDrives": True, "name": name, "parents": ["root"]})
                if not data.get("id"):
                    raise DriveError(f"the copy returned no id, so the temporary Doc cannot be tracked; look for "
                                     f"'{name}' in My Drive and trash it by hand")
                self.j["temp_doc"] = data["id"]
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
        if self.j.get("saved_ok"):   # run again after a verified save (a re-run cell): never a second file
            if self.j["saved"].get("sha256") != clean_sha256:
                raise DriveError(f"this run already saved a different text as {self.j['saved']['id']}; not saved again")
            return self.j["saved"]
        parent = (self.j["source"].get("parents") or [None])[0]
        if self.test_folder and parent != self.test_folder:
            raise DriveError(f"test mode: the source is not in the test folder {self.test_folder}; not saved")
        args = {"file_name": name, "text_content": text, "mime_type": "text/markdown"}
        if parent:
            where = "beside the source"
            try:
                data = self._run("GOOGLEDRIVE_CREATE_FILE_FROM_TEXT", {**args, "parent_id": parent})
            except DriveError as e:
                if self.test_folder or not _no_room(e):
                    raise
                data = self._run("GOOGLEDRIVE_CREATE_FILE_FROM_TEXT", args)
                where = "My Drive root (no permission to add files to the source's folder)"
        else:
            data = self._run("GOOGLEDRIVE_CREATE_FILE_FROM_TEXT", args)
            where = "My Drive root (Drive shows this account no folder for the source)"
        if not data.get("id"):
            raise DriveError("the save returned no file id; check Drive before running again")
        self.j.update(saved={"id": data["id"], "name": name, "where": where, "sha256": clean_sha256}, saved_ok=False)
        self._save_journal()
        url = _find(self._run("GOOGLEDRIVE_DOWNLOAD_FILE", {"fileId": data["id"]}), "s3url")
        if not url:
            raise DriveError(f"read-back of {data['id']} returned no download link; the temporary Doc is kept")
        if sha(self.fetch(url)) != clean_sha256:
            raise DriveError(f"read-back of {data['id']} does not match the checked text; the temporary Doc is kept")
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
        if doc in (self.source, self.j["source"]["id"]):
            raise DriveError("refusing to trash the source file")
        self._run("GOOGLEDRIVE_TRASH_FILE", {"file_id": doc, "supportsAllDrives": True})
        meta = self._run("GOOGLEDRIVE_GET_FILE_METADATA", {"fileId": doc, "fields": "trashed", "supportsAllDrives": True})
        if meta.get("trashed") is not True:
            raise DriveError(f"trashed {doc}, but Drive does not report it trashed")
        self.j["temp_trashed"] = True
        self._save_journal()
        return {"temp_doc": doc, "trashed": True}
