"""Write an EXIF block into a JPEG. Used to build the demo photographs, so a
stranger can try entolog without a camera card and without installing anything.

Reading EXIF is the job; writing it is only ever done here.
"""

from __future__ import annotations

import struct

E = "<"                                   # little endian, as most cameras write


def tiff_block(dt="2026:06:14 09:30:00", lat=None, lon=None, lat_ref="N",
               lon_ref="W", orientation=1, model="entolog demo", width=0, height=0) -> bytes:
    """A TIFF/EXIF block: IFD0, the EXIF sub-IFD, and the GPS sub-IFD."""
    data = bytearray()
    base = [0]

    def stash(b: bytes) -> int:
        off = base[0] + len(data)
        data.extend(b)
        if len(data) % 2:
            data.append(0)
        return off

    def entry(tag, typ, count, payload: bytes) -> bytes:
        if len(payload) <= 4:
            payload = payload.ljust(4, b"\0")
        else:
            payload = struct.pack(E + "I", stash(payload))
        return struct.pack(E + "HHI", tag, typ, count) + payload

    def rationals(vals) -> bytes:
        return b"".join(struct.pack(E + "II", int(round(v * 10000)), 10000) for v in vals)

    def dms(v):
        deg = int(abs(v))
        minutes = int((abs(v) - deg) * 60)
        return (deg, minutes, round(((abs(v) - deg) * 60 - minutes) * 60, 4))

    gps = lat is not None and lon is not None
    n0, n_exif, n_gps = 4, 3, (4 if gps else 0)
    ifd0_off = 8
    exif_off = ifd0_off + 2 + n0 * 12 + 4
    gps_off = exif_off + 2 + n_exif * 12 + 4
    base[0] = gps_off + (2 + n_gps * 12 + 4 if gps else 0)

    ifd0 = [entry(0x010F, 2, 8, b"entolog\0"),
            entry(0x0110, 2, len(model) + 1, model.encode() + b"\0"),
            entry(0x8769, 4, 1, struct.pack(E + "I", exif_off)),
            entry(0x8825, 4, 1, struct.pack(E + "I", gps_off if gps else 0))]
    exif = [entry(0x9003, 2, len(dt) + 1, dt.encode() + b"\0"),
            entry(0xA002, 4, 1, struct.pack(E + "I", width)),
            entry(0xA003, 4, 1, struct.pack(E + "I", height))]
    gpsd = []
    if gps:
        gpsd = [entry(1, 2, 2, (lat_ref if lat >= 0 else ("S" if lat_ref in "NS" else lat_ref)).encode() + b"\0"),
                entry(2, 5, 3, rationals(dms(lat))),
                entry(3, 2, 2, lon_ref.encode() + b"\0"),
                entry(4, 5, 3, rationals(dms(lon)))]

    def ifd(entries):
        return struct.pack(E + "H", len(entries)) + b"".join(entries) + struct.pack(E + "I", 0)

    out = b"II" + struct.pack(E + "HI", 42, ifd0_off) + ifd(ifd0) + ifd(exif)
    if gps:
        out += ifd(gpsd)
    return out + bytes(data)


def with_exif(jpeg: bytes, **kw) -> bytes:
    """Return the JPEG with an APP1 EXIF segment, replacing any it already has."""
    if jpeg[:2] != b"\xff\xd8":
        raise ValueError("not a JPEG")
    body, p = bytearray(), 2
    while p + 4 <= len(jpeg):
        if jpeg[p] != 0xFF:
            break
        marker = jpeg[p + 1]
        if marker == 0xDA:                       # start of scan: the rest is image
            body += jpeg[p:]
            p = len(jpeg)
            break
        (seg,) = struct.unpack_from(">H", jpeg, p + 2)
        if not (marker == 0xE1 and jpeg[p + 4:p + 10] == b"Exif\0\0"):
            body += jpeg[p:p + 2 + seg]
        p += 2 + seg
    else:
        body += jpeg[p:]
    app1 = b"Exif\0\0" + tiff_block(**kw)
    return (b"\xff\xd8" + b"\xff\xe1" + struct.pack(">H", len(app1) + 2) + app1 + bytes(body))
