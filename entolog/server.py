"""Local annotation server. Standard library only: no framework, no build step,
nothing to install on a field laptop. Binds 127.0.0.1 and requires a per-run token."""

from __future__ import annotations

import json
import mimetypes
import os
import re
import secrets
import shutil
import subprocess
import sqlite3
import threading
import urllib.parse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import db, entry, export, records
from . import profile as P

def _app_html() -> str:
    """Read the UI out of the package, which also works from a zipapp bundle."""
    try:
        from importlib.resources import files
        return files("entolog").joinpath("web/app.html").read_text(encoding="utf-8")
    except Exception:
        return (Path(__file__).parent / "web" / "app.html").read_text(encoding="utf-8")

DIRECT = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


class Ctx:
    def __init__(self, dbpath: Path, token: str):
        self.dbpath = Path(dbpath)
        self.token = token
        self.cache = self.dbpath.parent / ".entolog-cache"
        self.cache.mkdir(exist_ok=True)
        self._local = threading.local()

    @property
    def cx(self) -> sqlite3.Connection:
        cx = getattr(self._local, "cx", None)
        if cx is None:
            cx = self._local.cx = db.connect(self.dbpath)
        return cx


def _pillow_jpeg(src: Path, dst: Path, max_side: int) -> bool:
    try:
        from PIL import Image, ImageOps
    except ImportError:
        return False
    try:
        with Image.open(src) as im:
            im = ImageOps.exif_transpose(im)
            im.thumbnail((max_side, max_side))
            im.convert("RGB").save(dst, "JPEG", quality=88, optimize=True)
        return True
    except Exception:
        return False


def _exiftool_preview(src: Path, dst: Path) -> bool:
    exe = shutil.which("exiftool")
    if not exe:
        return False
    for tag in ("-JpgFromRaw", "-PreviewImage", "-ThumbnailImage"):
        try:
            out = subprocess.run([exe, "-b", tag, str(src)], capture_output=True,
                                 timeout=30).stdout
        except Exception:
            return False
        if out[:2] == b"\xff\xd8":
            dst.write_bytes(out)
            return True
    return False


def image_bytes(ctx: Ctx, row, size: str) -> tuple[bytes | None, str, Path | None]:
    """(inline bytes, content-type, path to send) for one photo at one size."""
    src = Path(row["path"])
    if not src.exists():
        return None, "", None
    if size == "thumb":
        if row["thumb_offset"] and row["thumb_length"]:
            with open(src, "rb") as fh:                 # camera's own thumbnail: free
                fh.seek(row["thumb_offset"])
                data = fh.read(row["thumb_length"])
            if data[:2] == b"\xff\xd8":
                return data, "image/jpeg", None
        cached = ctx.cache / f"{row['fingerprint']}-t.jpg"
        if cached.exists() or _pillow_jpeg(src, cached, 400):
            return None, "image/jpeg", cached
    if src.suffix.lower() in DIRECT and size == "full":
        return None, mimetypes.guess_type(src.name)[0] or "image/jpeg", src
    cached = ctx.cache / f"{row['fingerprint']}-{'t' if size == 'thumb' else 'f'}.jpg"
    if cached.exists():
        return None, "image/jpeg", cached
    side = 400 if size == "thumb" else 2200
    if _pillow_jpeg(src, cached, side) or _exiftool_preview(src, cached):
        return None, "image/jpeg", cached
    return None, mimetypes.guess_type(src.name)[0] or "application/octet-stream", src


def list_photos(cx, flt="all", q="", limit=5000, prof=None):
    return records.list_photos(cx, prof or P.active(cx), flt, q, limit)


def save_record(cx, pid: int, fields: dict, apply_group=False) -> list:
    """Kept for callers that just want to write fields and get the ids back."""
    ids, _errors = records.save(cx, P.active(cx), pid, fields, apply_group=apply_group)
    return ids


class Handler(BaseHTTPRequestHandler):
    ctx: Ctx = None  # type: ignore
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    # --- plumbing -------------------------------------------------------
    def _send(self, code, body=b"", ctype="application/json", extra=None):
        if isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        # The token rides in the query string on first load, so no outbound link
        # may carry a referrer.
        self.send_header("Referrer-Policy", "no-referrer")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, default=str))

    def _file(self, path: Path, ctype: str):
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "private, max-age=600")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def _authed(self, qs) -> bool:
        token = qs.get("t", [""])[0]
        if not token:
            m = re.search(r"entolog=([A-Za-z0-9_-]+)", self.headers.get("Cookie", "") or "")
            token = m.group(1) if m else ""
        return secrets.compare_digest(token, self.ctx.token)

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        try:
            return json.loads(self.rfile.read(n) or b"{}")
        except json.JSONDecodeError:
            return {}

    # --- routes ---------------------------------------------------------
    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(u.query)
        if not self._authed(qs):
            return self._send(HTTPStatus.FORBIDDEN, "bad or missing token", "text/plain")
        cx, path = self.ctx.cx, u.path

        if path in ("/", "/index.html"):
            html = _app_html()
            return self._send(200, html, "text/html; charset=utf-8",
                              {"Set-Cookie": f"entolog={self.ctx.token}; Path=/; SameSite=Strict; HttpOnly"})
        if path == "/api/state":
            prof = P.active(cx)
            return self._json({
                **records.counts(cx, prof), "profile": prof,
                "recorded_by": db.get_meta(cx, "recorded_by", ""),
                "db": str(self.ctx.dbpath), "token": self.ctx.token,
                "summary": export.summary(cx, prof),
            })
        if path == "/api/photos":
            return self._json(list_photos(cx, qs.get("filter", ["all"])[0],
                                          qs.get("q", [""])[0]))
        if path == "/api/current":
            row = entry.get_current(cx)
            if row is None:
                return self._json({"id": None})
            return self._json({"id": row["id"], "filename": row["filename"],
                               "line": entry.status_line(cx, P.active(cx), row)})
        if path == "/api/suggest":
            return self._json(records.suggest(cx, qs.get("field", [""])[0],
                                              qs.get("q", [""])[0]))
        m = re.fullmatch(r"/img/(\d+)", path)
        if m:
            row = cx.execute("SELECT * FROM photos WHERE id=?", (int(m.group(1)),)).fetchone()
            if not row:
                return self._send(404, "no such photo", "text/plain")
            size = qs.get("size", ["full"])[0]
            data, ctype, fpath = image_bytes(self.ctx, row, size)
            if data is not None:
                return self._send(200, data, ctype, {"Cache-Control": "private, max-age=600"})
            if fpath is None:
                return self._send(410, "file missing on disk", "text/plain")
            return self._file(fpath, ctype)
        if path == "/api/export":
            fmt = qs.get("fmt", ["csv"])[0]
            allrows = qs.get("all", ["0"])[0] == "1"
            try:
                text = export.render(cx, fmt, only_determined=not allrows)
            except ValueError as e:
                return self._send(400, str(e), "text/plain")
            ext = {"dwc": "csv", "full": "csv", "md": "md"}.get(fmt, fmt)
            return self._send(200, text, "text/plain; charset=utf-8",
                              {"Content-Disposition": f'attachment; filename="records-{fmt}.{ext}"'})
        return self._send(404, "not found", "text/plain")

    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(u.query)
        if not self._authed(qs):
            return self._send(HTTPStatus.FORBIDDEN, "bad or missing token", "text/plain")
        cx, body = self.ctx.cx, self._body()
        m = re.fullmatch(r"/api/record/(\d+)", u.path)
        if m:
            fields = body.get("values", {k: v for k, v in body.items()
                                          if k != "apply_group"})
            ids, errors = records.save(cx, P.active(cx), int(m.group(1)), fields,
                                       apply_group=bool(body.get("apply_group")))
            return self._json({"saved": ids, "errors": errors,
                               **records.counts(cx, P.active(cx))})
        if u.path == "/api/profile":
            try:
                prof = P.set_active(cx, body.get("profile"), force=bool(body.get("force")))
            except P.ProfileError as e:
                return self._send(400, str(e), "text/plain")
            return self._json({"profile": prof})
        if u.path == "/api/current":
            try:
                row = entry.set_current(cx, str(body.get("target", "")))
            except LookupError as e:
                return self._send(404, str(e), "text/plain")
            return self._json({"id": row["id"], "filename": row["filename"]})
        if u.path == "/api/meta":
            for k, v in body.items():
                db.set_meta(cx, k, v)
            return self._json({"ok": True})
        if u.path == "/api/terms/import":
            n = records.import_terms(cx, body.get("field", ""),
                                     (body.get("names") or "").splitlines())
            return self._json({"imported": n})
        return self._send(404, "not found", "text/plain")

    do_HEAD = do_GET


def serve(dbpath, host="127.0.0.1", port=8731) -> tuple[ThreadingHTTPServer, str]:
    token = os.environ.get("ENTOLOG_TOKEN") or secrets.token_urlsafe(16)
    Handler.ctx = Ctx(Path(dbpath), token)
    for p in range(port, port + 20):
        try:
            httpd = ThreadingHTTPServer((host, p), Handler)
            break
        except OSError:
            continue
    else:
        raise SystemExit(f"no free port in {port}-{port + 19}")
    return httpd, f"http://{host}:{httpd.server_address[1]}/?t={token}"
