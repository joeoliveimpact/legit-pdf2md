"""Drive steps for legit-pdf2md on the Composio connector: one run's copy, export, save and cleanup.

Runs inside COMPOSIO_REMOTE_WORKBENCH, where run_composio_tool is preloaded. Pass run_composio_tool in as
`call`. Each source file gets its own journal on /mnt/files, and every id this run creates goes into it before
anything else happens, so cleanup trashes exactly the temporary Doc this run made and nothing else, and only
after the clean file was saved, read back and matched the text that passed the check. Standard library + requests.

  txn = Txn(run_composio_tool, "me@example.com", file_id)
  txn.open()                          # metadata and this run's state: always first, in every cell
  txn.export("export.md")             # a PDF is copied to a temporary Doc (OCR) in My Drive first
  txn.save(text, clean_sha256, name)  # save beside the source, read back, compare hashes
  txn.cleanup()                       # trash the temporary Doc, confirm it is trashed

A run belongs to one version of the source (its modifiedTime when the run started). The temporary Doc carries
that in its description, stamped by the copy call itself, so it can be proven to be this run's: the stamp names
the source's id and version. Composio can hand a later cell a fresh sandbox with /mnt/files empty (seen
09.23.26), so the journal is only a cache: the id printed by the first cell (`temp_doc=`), or a search of My
Drive root for the stamp, rebuilds it. A journal or temporary Doc from an older version of the source is never
continued; it is reported under `leftovers`. A save first looks for an identical file already in the folder, so
a reset between save and cleanup never saves twice.
"""
import hashlib, json, os, re

DOC = "application/vnd.google-apps.document"
JOURNALS = "/mnt/files/legit-pdf2md"
REUSE = "legit-pdf2md reuse:"   # the clean file's Drive description: the source id and modified time it came from
TEMP = "legit-pdf2md temp:"     # the temporary Doc's Drive description: the same, for the run that made it


class DriveError(Exception):
    pass


class NoRoom(DriveError):
    """The save was refused because this account may not add files to the folder."""


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


def _q(s):
    """A string inside a Drive query: backslash first, then the quote."""
    return s.replace("\\", "\\\\").replace("'", "\\'")


def temp_name(title):
    """The temporary Doc's name: the source's title without a trailing .pdf, plus " - temp"."""
    return (title[:-4] if title.lower().endswith(".pdf") else title) + " - temp"


MAX_PAGES = 80   # Google converts only a PDF's first 80 pages to a Doc, silently (measured 09.24.26: 100 in, 80 out)


def pdf_pages(data):
    """A PDF's page count, or None when it cannot be read. pypdf (in Composio's workbench) follows incremental
    updates and object streams; without it, a standard-library read of the page tree (/Type /Pages ... /Count N),
    opening compressed object streams only when the raw file shows none. That fallback can misread a PDF edited
    after it was made, or a page tree with a dictionary nested inside it."""
    try:
        import io, pypdf
        return len(pypdf.PdfReader(io.BytesIO(data)).pages)
    except Exception:   # not installed, or a file pypdf cannot read: the fallback below
        pass
    import zlib

    def counts(blob):   # the /Count inside the same dictionary as each /Type /Pages
        out = []
        for m in re.finditer(rb"/Type\s*/Pages\b", blob):
            a, b = blob.rfind(b"<<", 0, m.start()), blob.find(b">>", m.end())
            out += [int(c) for c in re.findall(rb"/Count\s+(\d+)", blob[max(a, 0):b if b > 0 else m.end() + 300])]
        return out
    found = counts(data)
    if not found:
        for m in re.finditer(rb"/Type\s*/ObjStm\b", data):
            s = re.compile(rb"stream\r?\n").search(data, m.end())
            if s:
                try:
                    found += counts(zlib.decompressobj().decompress(data[s.end():s.end() + 2_000_000]))
                except zlib.error:
                    pass
    return max(found) if found else None


def _fetch(url, raw=False):
    import requests
    r = requests.get(url, timeout=120)
    r.raise_for_status()
    return r.content if raw else r.content.decode("utf-8")


class Txn:
    def __init__(self, call, account, source, test_folder=None, temp_doc=None, journals=JOURNALS, fetch=_fetch):
        self.call, self.source, self.fetch, self.adopt, self.test_folder = call, source, fetch, temp_doc, test_folder
        self.given_account = account
        self.path = os.path.join(journals, "txn-" + re.sub(r"[^\w-]", "_", source) + ".json")
        self.j = json.load(open(self.path, encoding="utf-8")) if os.path.exists(self.path) else {}
        self.account = account or ({} if self._finished() else self.j).get("account")   # for open()'s first read
        self.opened = False

    def _finished(self):
        return bool(self.j.get("saved_ok") and (self.j.get("temp_trashed") or not self.j.get("temp_doc")))

    def _save_journal(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path + ".tmp", "w", encoding="utf-8") as f:
            json.dump(self.j, f)
        os.replace(self.path + ".tmp", self.path)

    def _need_open(self):
        if not self.opened:
            raise DriveError("call open() first: it checks this run's account, test folder and temporary Doc")

    def _run(self, slug, args):
        r, err = self.call(slug, args, account=self.account) if self.account else self.call(slug, args)
        data = r.get("data") if isinstance(r, dict) else None
        if err or not data:
            raise DriveError(f"{slug}: {err or (r.get('error') if isinstance(r, dict) else r) or 'no data'}")
        return data

    def open(self):
        """The source's metadata, and this run's state. An unfinished run on the same version of the source
        carries on from its journal (a verified save whose temporary Doc is not trashed yet is unfinished: cleanup
        still has to run). A finished run, or one started on an older version of the source, starts a new one."""
        meta = self._run("GOOGLEDRIVE_GET_FILE_METADATA", {"fileId": self.source, "supportsAllDrives": True,
                         "fields": "id,name,mimeType,parents,driveId,modifiedTime"})
        old, version = self.j, meta.get("modifiedTime")
        live = bool(old) and not self._finished() and old.get("version") == version
        j = old if live else {"version": version}   # an older version's temporary Doc is found by export, as a leftover
        for key, given, what in (("test_folder", self.test_folder, "is in test mode for folder"),
                                 ("account", self.given_account, "uses the account"),   # one run, one account
                                 ("temp_doc", self.adopt, "has the temporary Doc")):
            if given and j.get(key) not in (None, given):
                raise DriveError(f"this run {what} {j[key]}, not {given}")
        self.test_folder = self.test_folder or j.get("test_folder")   # a later cell cannot drop test mode
        self.account = self.given_account or j.get("account")
        j.update({k: v for k, v in (("test_folder", self.test_folder), ("account", self.account)) if v})
        j["source"] = meta
        if self.adopt and meta["mimeType"] == DOC:
            raise DriveError("a Google Doc source has no temporary Doc: pass temp_doc=None (TEMP = None)")
        if self.adopt and not j.get("temp_doc"):   # the sandbox was reset: take back the id from the chat
            self._check_temp(self.adopt, meta, j)
            j["temp_doc"] = self.adopt
        self.j, self.opened = j, True
        self._save_journal()
        return meta

    def temp_stamp(self, j=None, any_version=False):
        """The temporary Doc's description; any_version=True gives the part every version shares."""
        j = j or self.j
        base = f"{TEMP} source {j['source']['id']} modified "
        return base if any_version else base + str(j.get("version"))

    def _check_temp(self, doc, meta, j):
        """Adopt doc only if it is an untrashed Google Doc, named as this run names its copy, stamped from this
        source, and never the source itself. A stamp from an older version means the source changed mid-run."""
        t = self._run("GOOGLEDRIVE_GET_FILE_METADATA", {"fileId": doc, "supportsAllDrives": True,
                      "fields": "id,name,mimeType,trashed,description"})
        want, stamp = temp_name(meta["name"]), self.temp_stamp(j)
        desc = t.get("description") or ""
        if doc == meta["id"] or t.get("mimeType") != DOC or t.get("name") != want or \
                not desc.startswith(self.temp_stamp(j, any_version=True)):
            raise DriveError(f"{doc} is not this run's temporary Doc (expected a Google Doc named '{want}' "
                             f"made by legit-pdf2md from this file)")
        if t.get("trashed"):
            raise DriveError(f"the temporary Doc {doc} is in the trash: if this run's clean file was saved, the run "
                             f"finished; if not, run the start cell again")
        if desc != stamp:
            raise DriveError(f"the source changed since this run started: the temporary Doc {doc} holds an older "
                             f"version. Run the start cell again for the current version; {doc} is left in My "
                             f"Drive for the user to trash")

    def temps(self):
        """This version's temporary Docs in My Drive root, found by their stamp (the id was lost). Extra ones, and
        ones from older versions of the source, go to leftovers for the report; nothing here is trashed."""
        name, stamp = temp_name(self.j["source"]["name"]), self.temp_stamp()
        found = self._run("GOOGLEDRIVE_FIND_FILE", {"q": f"name = '{_q(name)}' and 'root' in parents and "
                          f"mimeType = '{DOC}' and trashed = false", "fields": "files(id,name,description)", "pageSize": 1000})
        ours = [f for f in found.get("files") or [] if (f.get("description") or "").startswith(self.temp_stamp(any_version=True))]
        mine = [f["id"] for f in ours if f["description"] == stamp]
        extra = mine[1:] + [f["id"] for f in ours if f["description"] != stamp]
        if extra:
            self.j["leftovers"] = sorted(set(self.j.get("leftovers", []) + extra))
        return mine[:1]

    def export(self, path, ocr_language="en", copy=True):
        """Write the source's Markdown export to path. A PDF becomes a temporary Doc first (Google's OCR reads
        scanned pages, in ocr_language), made in the user's private My Drive root, stamped, and logged before it
        is used. If the run has no id for it, one made earlier for this version is found by its stamp first.
        copy=False (every cell after the first) never makes one: without a temporary Doc it stops."""
        self._need_open()
        src = self.j["source"]
        doc = src["id"]
        if src["mimeType"] != DOC:
            if not self.j.get("temp_doc"):
                found = self.temps()
                if found:
                    self.j["temp_doc"] = found[0]
                elif not copy:
                    raise DriveError("no temporary Doc for this version of the source: run the start cell again")
                else:   # a long PDF would lose its tail with no error: stop before any copy is made
                    try:   # a count that cannot be read never blocks the run
                        url = _find(self._run("GOOGLEDRIVE_DOWNLOAD_FILE", {"fileId": doc}), "s3url")
                        pages = pdf_pages(self.fetch(url, raw=True)) if url else None
                    except Exception:
                        pages = None
                    self.j["pages"] = pages
                    if pages and pages > MAX_PAGES:
                        raise DriveError(f"this PDF has {pages} pages, and Google converts only the first {MAX_PAGES} to "
                                         f"text, without saying so. Split it into parts of {MAX_PAGES} pages or fewer "
                                         f"and run each part; nothing was copied")
                    data = self._run("GOOGLEDRIVE_COPY_FILE_ADVANCED", {"fileId": doc, "mimeType": DOC,
                                     "ocrLanguage": ocr_language, "supportsAllDrives": True, "name": temp_name(src["name"]),
                                     "parents": ["root"], "description": self.temp_stamp()})
                    if not data.get("id"):
                        raise DriveError("the copy returned no id; run the start cell again: it finds the copy by "
                                         "its description instead of making another")
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
        self._need_open()
        if sha(text) != clean_sha256:
            raise DriveError("this text is not the text that passed the check (hash differs); not saved")
        if self.j.get("saved_ok"):   # run again after a verified save (a re-run cell): never a second file
            if self.j["saved"].get("sha256") != clean_sha256:
                raise DriveError(f"this run already saved a different text as {self.j['saved']['id']}; not saved again")
            return self.j["saved"]
        parent = (self.j["source"].get("parents") or [None])[0]
        if self.test_folder and parent != self.test_folder:
            raise DriveError(f"test mode: the source is not in the test folder {self.test_folder}; not saved")
        mine = f"{REUSE} source {self.j['source']['id']} "

        def put(folder, extra):
            files = self._candidates(name, folder)
            for f in files:   # an identical file of ours already there (a reset after the save) is this run's save
                desc = f.get("description") or ""   # blank (a reset before the key) or our key; never a user's note
                if (not desc or desc.startswith(mine)) and self._content_is(f["id"], clean_sha256):
                    return {"id": f["id"], "name": f["name"], "reused": True}
            taken, final, n = {f["name"] for f in files}, name, 2
            while final in taken:   # never overwrite: another file has the name, so "<title> - clean (2).md"
                final = f"{name[:-3]} ({n}).md"
                n += 1
            try:
                return {**self._run("GOOGLEDRIVE_CREATE_FILE_FROM_TEXT", {"text_content": text, "mime_type": "text/markdown",
                                    "file_name": final, **extra}), "name": final}
            except DriveError as e:   # only the create call's refusal can send the file somewhere else
                if _no_room(e):
                    raise NoRoom(str(e)) from e
                raise
        if parent:
            where = "beside the source"
            try:
                data = put(parent, {"parent_id": parent})
            except NoRoom:
                if self.test_folder:
                    raise
                data = put("root", {})
                where = "My Drive root (no permission to add files to the source's folder)"
        else:
            data = put("root", {})
            where = "My Drive root (Drive shows this account no folder for the source)"
        if not data.get("id"):
            raise DriveError("the save returned no file id; check Drive before running again")
        self.j.update(saved={"id": data["id"], "name": data["name"], "where": where, "sha256": clean_sha256}, saved_ok=False)
        self._save_journal()
        if not data.get("reused"):   # a reused file was already read back and matched by _content_is
            url = _find(self._run("GOOGLEDRIVE_DOWNLOAD_FILE", {"fileId": data["id"]}), "s3url")
            if not url:
                raise DriveError(f"read-back of {data['id']} returned no download link; the temporary Doc is kept")
            if sha(self.fetch(url)) != clean_sha256:
                raise DriveError(f"read-back of {data['id']} does not match the checked text; the temporary Doc is kept")
        self.j["saved_ok"] = True
        self.j["saved"]["reuse_key"] = False
        self._save_journal()
        if self.reuse_key():   # a later run on this unchanged source finds this file and does no work
            try:
                self._run("GOOGLEDRIVE_UPDATE_FILE_PUT", {"fileId": data["id"], "description": self.reuse_key()})
                self.j["saved"]["reuse_key"] = True
                self._save_journal()
            except Exception:   # the save stands; only the shortcut for next time is lost
                pass
        return self.j["saved"]

    def reuse_key(self):
        """The key for the version this run started on; None when Drive gave no modified time."""
        v = self.j.get("version")
        return f"{REUSE} source {self.j['source']['id']} modified {v}" if v else None

    def reusable(self, name):
        """A clean file this skill already made from this exact version of the source (same id and modified
        time), found by the key in its description: {"id", "name", "where"}, or None. Call after open()."""
        self._need_open()
        key = self.reuse_key()
        parent = (self.j["source"].get("parents") or [None])[0]
        for folder, where in ((parent, "beside the source"), ("root", "My Drive root")):
            if folder and key:
                for f in self._candidates(name, folder):
                    if f.get("description") == key:
                        return {"id": f["id"], "name": f["name"], "where": where}
        return None

    def _candidates(self, name, folder):
        """Files in folder named name, or name with a " (N)" before .md."""
        stem = name[:-3] if name.endswith(".md") else name
        found = self._run("GOOGLEDRIVE_FIND_FILE", {"q": f"name contains '{_q(stem)}' and '{folder}' in parents and trashed = false",
                          "fields": "files(id,name,description)", "pageSize": 1000, "supportsAllDrives": True,
                          "includeItemsFromAllDrives": True})
        pat = re.compile(re.escape(stem) + r"( \(\d+\))?\.md")
        return [f for f in found.get("files") or [] if pat.fullmatch(f.get("name", ""))]

    def _content_is(self, file_id, want):
        url = _find(self._run("GOOGLEDRIVE_DOWNLOAD_FILE", {"fileId": file_id}), "s3url")
        return bool(url) and sha(self.fetch(url)) == want

    def cleanup(self):
        """Trash this run's temporary Doc, only after a verified save, and confirm it is trashed."""
        self._need_open()
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
