"""Dependency-free EXIF reader.

Parses the TIFF/EXIF block out of JPEG (APP1), TIFF-family raws (DNG/NEF/CR2/ARW),
PNG (eXIf chunk) and WebP (EXIF chunk) using nothing but the standard library, so
this runs on a bare Python install in the field. HEIC/HEIF and anything unparsed
falls back to `exiftool` when it happens to be installed.

Returns a flat dict with the handful of things a species record needs:
datetime_original, gps lat/lon/alt, orientation, camera, lens, and the offsets of
the embedded thumbnail so the UI can page through photos without decoding them.
"""

from __future__ import annotations

import json
import shutil
import struct
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

# TIFF field type -> (struct code, byte size)
_TYPES = {
    1: ("B", 1), 2: ("s", 1), 3: ("H", 2), 4: ("I", 4), 5: ("II", 8),
    6: ("b", 1), 7: ("s", 1), 8: ("h", 2), 9: ("i", 4), 10: ("ii", 8),
    11: ("f", 4), 12: ("d", 8),
}

_EXIF_IFD = 0x8769
_GPS_IFD = 0x8825

_IFD0 = {0x010F: "make", 0x0110: "model", 0x0112: "orientation",
         0x0132: "datetime", 0x013B: "artist", 0x8298: "copyright",
         0x011A: "x_resolution", 0x0131: "software"}
_EXIF = {0x9003: "datetime_original", 0x9004: "datetime_digitized",
         0x9011: "offset_time_original", 0x9010: "offset_time",
         0x9291: "subsec_time_original", 0xA002: "pixel_x", 0xA003: "pixel_y",
         0x829A: "exposure_time", 0x829D: "f_number", 0x8827: "iso",
         0x920A: "focal_length", 0xA434: "lens_model", 0xA433: "lens_make",
         0x9286: "user_comment", 0xA420: "image_uid"}
_GPS = {1: "lat_ref", 2: "lat", 3: "lon_ref", 4: "lon", 5: "alt_ref", 6: "alt",
        7: "gps_time", 29: "gps_datestamp", 27: "gps_method", 31: "gps_hpos_error"}


class _Tiff:
    def __init__(self, buf: bytes, base: int = 0):
        self.buf = buf
        self.base = base
        bo = buf[base:base + 2]
        if bo == b"II":
            self.e = "<"
        elif bo == b"MM":
            self.e = ">"
        else:
            raise ValueError("not a TIFF header")
        magic, self.first = struct.unpack_from(self.e + "HI", buf, base + 2)
        if magic not in (42, 0x4F52, 0x5352, 85):  # 42 standard, others Olympus/Panasonic RAW
            raise ValueError("bad TIFF magic %r" % magic)

    def read_ifd(self, off: int) -> tuple[dict, int]:
        """Return {tag: value} for the IFD at `off` plus the next-IFD offset."""
        buf, e, base = self.buf, self.e, self.base
        p = base + off
        if p + 2 > len(buf):
            return {}, 0
        (count,) = struct.unpack_from(e + "H", buf, p)
        p += 2
        out: dict[int, object] = {}
        for _ in range(count):
            if p + 12 > len(buf):
                break
            tag, typ, n = struct.unpack_from(e + "HHI", buf, p)
            try:
                out[tag] = self._value(typ, n, p + 8)
            except Exception:
                pass
            p += 12
        nxt = 0
        if p + 4 <= len(buf):
            (nxt,) = struct.unpack_from(e + "I", buf, p)
        return out, nxt

    def _value(self, typ: int, n: int, vp: int):
        if typ not in _TYPES:
            return None
        code, size = _TYPES[typ]
        total = size * n
        if total > 4:
            (off,) = struct.unpack_from(self.e + "I", self.buf, vp)
            vp = self.base + off
        if vp < 0 or vp + total > len(self.buf):
            return None
        raw = self.buf[vp:vp + total]
        if typ in (2, 7):  # ASCII / UNDEFINED
            if typ == 2:
                return raw.split(b"\0", 1)[0].decode("utf-8", "replace").strip()
            return raw
        if typ in (5, 10):  # (S)RATIONAL
            c = "iI" [typ == 5]
            vals = []
            for i in range(n):
                num, den = struct.unpack_from(self.e + c + c, raw, i * 8)
                vals.append(num / den if den else 0.0)
            return vals[0] if n == 1 else vals
        vals = list(struct.unpack_from(self.e + code * n, raw, 0))
        return vals[0] if n == 1 else vals


def _find_tiff(data: bytes) -> tuple[bytes, int] | None:
    """Locate the TIFF block inside a container. Returns (buffer, offset)."""
    if data[:2] in (b"II", b"MM") and len(data) > 8:
        return data, 0
    if data[:2] == b"\xff\xd8":  # JPEG
        p = 2
        while p + 4 <= len(data):
            if data[p] != 0xFF:
                p += 1
                continue
            marker = data[p + 1]
            if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
                p += 2
                continue
            if marker == 0xDA:  # start of scan, EXIF cannot follow
                break
            (seg,) = struct.unpack_from(">H", data, p + 2)
            body = p + 4
            if marker == 0xE1 and data[body:body + 6] == b"Exif\0\0":
                return data, body + 6
            p = p + 2 + seg
        return None
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        p = 8
        while p + 8 <= len(data):
            (ln,) = struct.unpack_from(">I", data, p)
            typ = data[p + 4:p + 8]
            if typ == b"eXIf":
                return data, p + 8
            if typ == b"IEND":
                break
            p += 12 + ln
        return None
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        p = 12
        while p + 8 <= len(data):
            typ = data[p:p + 4]
            (ln,) = struct.unpack_from("<I", data, p + 4)
            if typ == b"EXIF":
                s = p + 8
                if data[s:s + 6] == b"Exif\0\0":
                    s += 6
                return data, s
            p += 8 + ln + (ln & 1)
        return None
    return None


def _dms(v, ref) -> float | None:
    if not isinstance(v, (list, tuple)) or len(v) < 3:
        return None
    deg = v[0] + v[1] / 60.0 + v[2] / 3600.0
    if ref in ("S", "W"):
        deg = -deg
    return round(deg, 7)


def _ts(s, subsec=None, offset=None) -> str | None:
    """EXIF '2026:08:24 07:41:03' -> ISO 8601, keeping sub-seconds and UTC offset."""
    if not s or not isinstance(s, str):
        return None
    s = s.strip().rstrip("\0")
    for fmt in ("%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y:%m:%d %H:%M"):
        try:
            dt = datetime.strptime(s, fmt)
            break
        except ValueError:
            continue
    else:
        return None
    out = dt.strftime("%Y-%m-%dT%H:%M:%S")
    if subsec:
        d = "".join(ch for ch in str(subsec) if ch.isdigit())[:3]
        if d:
            # Always three digits: datetime.fromisoformat before 3.11 accepts
            # only three or six, and a one digit fraction would break the parse.
            out += "." + d.ljust(3, "0")
    if offset and isinstance(offset, str) and len(offset.strip()) >= 6:
        out += offset.strip()[:6]
    return out


def _exiftool(path: Path) -> dict:
    exe = shutil.which("exiftool")
    if not exe:
        return {}
    try:
        raw = subprocess.run(
            [exe, "-j", "-n", "-DateTimeOriginal", "-CreateDate", "-GPSLatitude",
             "-GPSLongitude", "-GPSAltitude", "-Orientation", "-Make", "-Model",
             "-LensModel", "-ImageWidth", "-ImageHeight", str(path)],
            capture_output=True, timeout=20, check=False).stdout
        tags = json.loads(raw)[0]
    except Exception:
        return {}
    out = {
        "datetime_original": _ts((tags.get("DateTimeOriginal") or tags.get("CreateDate") or "").replace("-", ":", 2)),
        "lat": tags.get("GPSLatitude"), "lon": tags.get("GPSLongitude"),
        "altitude": tags.get("GPSAltitude"), "orientation": tags.get("Orientation") or 1,
        "camera": " ".join(str(tags.get(k, "")) for k in ("Make", "Model")).strip() or None,
        "lens": tags.get("LensModel"),
        "width": tags.get("ImageWidth"), "height": tags.get("ImageHeight"),
        "source": "exiftool",
    }
    return {k: v for k, v in out.items() if v not in (None, "")}


def read(path: str | Path, head: int = 512 * 1024) -> dict:
    """Extract the record-relevant EXIF fields from one image file."""
    path = Path(path)
    out: dict[str, object] = {"source": "builtin"}
    try:
        with open(path, "rb") as fh:
            data = fh.read(head)
    except OSError:
        return _exiftool(path)

    found = _find_tiff(data)
    if not found:
        return _exiftool(path) or out
    buf, base = found
    try:
        t = _Tiff(buf, base)
        ifd0, next_off = t.read_ifd(t.first)
    except Exception:
        return _exiftool(path) or out

    tags: dict[str, object] = {}
    for tag, val in ifd0.items():
        if tag in _IFD0:
            tags[_IFD0[tag]] = val
    for ptr, table in ((_EXIF_IFD, _EXIF), (_GPS_IFD, _GPS)):
        off = ifd0.get(ptr)
        if isinstance(off, int):
            try:
                sub, _ = t.read_ifd(off)
            except Exception:
                continue
            for tag, val in sub.items():
                if tag in table:
                    tags[table[tag]] = val

    out["datetime_original"] = (
        _ts(tags.get("datetime_original"), tags.get("subsec_time_original"),
            tags.get("offset_time_original") or tags.get("offset_time"))
        or _ts(tags.get("datetime_digitized")) or _ts(tags.get("datetime")))

    lat = _dms(tags.get("lat"), tags.get("lat_ref"))
    lon = _dms(tags.get("lon"), tags.get("lon_ref"))
    if lat is not None and lon is not None and not (lat == 0 and lon == 0):
        out["lat"], out["lon"] = lat, lon
        alt = tags.get("alt")
        if isinstance(alt, (int, float)):
            out["altitude"] = round(-alt if tags.get("alt_ref") == 1 else alt, 1)
        err = tags.get("gps_hpos_error")
        if isinstance(err, (int, float)) and err > 0:
            out["gps_accuracy_m"] = round(err, 1)
        # GPS clock is UTC and never drifts; keep it as a cross-check on camera time
        gt, gd = tags.get("gps_time"), tags.get("gps_datestamp")
        if isinstance(gt, (list, tuple)) and len(gt) == 3 and isinstance(gd, str):
            try:
                d = datetime.strptime(gd.strip(), "%Y:%m:%d").replace(tzinfo=timezone.utc)
                d += timedelta(hours=gt[0], minutes=gt[1], seconds=gt[2])
                out["gps_datetime_utc"] = d.strftime("%Y-%m-%dT%H:%M:%SZ")
            except Exception:
                pass

    orient = tags.get("orientation")
    out["orientation"] = orient if isinstance(orient, int) and 1 <= orient <= 8 else 1
    cam = " ".join(str(tags.get(k, "")).strip() for k in ("make", "model")).split()
    if cam:  # "NIKON CORPORATION NIKON D850" -> "NIKON CORPORATION D850"
        seen, parts = set(), []
        for w in cam:
            if w.lower() not in seen:
                seen.add(w.lower())
                parts.append(w)
        out["camera"] = " ".join(parts)
    if tags.get("lens_model"):
        out["lens"] = str(tags["lens_model"]).strip()
    for src, dst in (("pixel_x", "width"), ("pixel_y", "height")):
        if isinstance(tags.get(src), int):
            out[dst] = tags[src]
    for src, dst in (("f_number", "f_number"), ("focal_length", "focal_length_mm"),
                     ("exposure_time", "exposure_s")):
        if isinstance(tags.get(src), (int, float)):
            out[dst] = round(float(tags[src]), 4)
    iso = tags.get("iso")
    if isinstance(iso, (int, list)):
        out["iso"] = iso[0] if isinstance(iso, list) else iso

    # IFD1 holds the camera's own thumbnail: free, instant previews.
    if next_off:
        try:
            ifd1, _ = t.read_ifd(next_off)
            off, ln = ifd1.get(0x0201), ifd1.get(0x0202)
            if isinstance(off, int) and isinstance(ln, int) and 0 < ln < 2_000_000:
                out["thumb_offset"] = base + off
                out["thumb_length"] = ln
        except Exception:
            pass

    if not out.get("datetime_original") or "lat" not in out:
        for k, v in _exiftool(path).items():
            out.setdefault(k, v)
            if k in ("datetime_original", "lat", "lon") and not out.get(k):
                out[k] = v
    return out
