"""Build small JPEGs carrying real EXIF, so the tests need no camera and no Pillow."""
import struct


def _tiff(dt="2026:06:14 09:30:00", lat=(51, 45, 7.2), lon=(1, 15, 27.6),
          lat_ref="N", lon_ref="W", orientation=6, model="TESTCAM 1", gps=True):
    e = "<"
    data = bytearray()          # pool for values longer than four bytes
    DATA_BASE = [0]             # filled in once the IFD sizes are known

    def stash(b: bytes) -> int:
        off = DATA_BASE[0] + len(data)
        data.extend(b)
        if len(data) % 2:
            data.append(0)
        return off

    def entry(tag, typ, count, payload: bytes):
        if len(payload) <= 4:
            payload = payload.ljust(4, b"\0")
        else:
            payload = struct.pack(e + "I", stash(payload))
        return struct.pack(e + "HHI", tag, typ, count) + payload

    def rationals(vals):
        out = b""
        for v in vals:
            out += struct.pack(e + "II", int(round(v * 1000)), 1000)
        return out

    n0, nexif, ngps = 4, 2, (4 if gps else 0)
    ifd0_off = 8
    exif_off = ifd0_off + 2 + n0 * 12 + 4
    gps_off = exif_off + 2 + nexif * 12 + 4
    DATA_BASE[0] = gps_off + (2 + ngps * 12 + 4 if gps else 0)

    ifd0 = [entry(0x0110, 2, len(model) + 1, model.encode() + b"\0"),
            entry(0x0112, 3, 1, struct.pack(e + "H", orientation)),
            entry(0x8769, 4, 1, struct.pack(e + "I", exif_off)),
            entry(0x8825, 4, 1, struct.pack(e + "I", gps_off if gps else 0))]
    exif = [entry(0x9003, 2, len(dt) + 1, dt.encode() + b"\0"),
            entry(0xA002, 4, 1, struct.pack(e + "I", 6000))]
    gpsd = []
    if gps:
        gpsd = [entry(1, 2, 2, lat_ref.encode() + b"\0"),
                entry(2, 5, 3, rationals(lat)),
                entry(3, 2, 2, lon_ref.encode() + b"\0"),
                entry(4, 5, 3, rationals(lon))]

    def ifd(entries):
        return struct.pack(e + "H", len(entries)) + b"".join(entries) + struct.pack(e + "I", 0)

    buf = b"II" + struct.pack(e + "HI", 42, ifd0_off) + ifd(ifd0) + ifd(exif)
    if gps:
        buf += ifd(gpsd)
    return buf + bytes(data)


def jpeg(**kw) -> bytes:
    t = _tiff(**kw)
    app1 = b"Exif\0\0" + t
    return (b"\xff\xd8" + b"\xff\xe1" + struct.pack(">H", len(app1) + 2) + app1
            + b"\xff\xdb\x00\x04\x00\x00" + b"\xff\xd9")


def write(path, **kw):
    path.write_bytes(jpeg(**kw))
    return path
