"""Locality: make a verbose reverse-geocode usable in a record, and turn a
position into a grid reference.

A satnav lookup gives back the whole postal hierarchy:

    Wytham Woods, Wytham, Vale of White Horse, Oxfordshire, England, OX2 8QQ, United Kingdom

A record wants the two parts that place it: the named site and the county.
Nothing here needs the network. `lookup()` is the only function that touches it
and it is only ever called from the explicit `entolog locality lookup` command.
"""

from __future__ import annotations

import json
import math
import re
import time
import urllib.parse
import urllib.request

# Things that never help a record: postcodes, house numbers, countries and the
# very coarse administrative layers that sit just below a country.
_POSTCODE = re.compile(
    r"^(?:[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}|\d{4,6}|\d{5}-\d{4}|[A-Z]\d[A-Z]\s*\d[A-Z]\d)$", re.I)
_COARSE = {
    "united kingdom", "uk", "great britain", "england", "scotland", "wales",
    "northern ireland", "ireland", "united states", "usa", "united states of america",
    "france", "germany", "spain", "italy", "netherlands", "belgium", "portugal",
    "australia", "new zealand", "canada", "india", "bangladesh", "south africa",
    "cymru", "alba",
}
_DROP_PATTERNS = (
    re.compile(r"^\d+[a-z]?$", re.I),                       # house number
    re.compile(r"^unclassified$|^unnamed road$", re.I),
    re.compile(r"^[A-Z]{2,3}\d{1,4}$"),                     # road numbers, A420
)

# Nominatim address keys, most specific first. The first hit becomes the site.
_SITE_KEYS = ("nature_reserve", "protected_area", "leisure", "park", "wood", "forest",
              "farm", "isolated_dwelling", "locality", "hamlet", "croft", "village",
              "suburb", "neighbourhood", "town", "city_district", "city",
              "municipality", "road")
_AREA_KEYS = ("county", "state_district", "province", "state", "region", "district")


def _useful(token: str) -> bool:
    t = token.strip()
    if not t or t.lower() in _COARSE or _POSTCODE.match(t):
        return False
    return not any(p.match(t) for p in _DROP_PATTERNS)


def _dedupe(parts):
    """Drop a part that is already contained in one being kept: Wytham inside
    Wytham Woods adds nothing."""
    out = []
    for p in parts:
        low = p.lower()
        if any(low in q.lower() or q.lower() in low for q in out):
            continue
        out.append(p)
    return out


def shorten(verbose, parts: int = 2) -> str:
    """Verbose lookup (a string, or Nominatim JSON/dict) to a short locality."""
    if not verbose:
        return ""
    if isinstance(verbose, str) and verbose.lstrip().startswith("{"):
        try:
            verbose = json.loads(verbose)
        except json.JSONDecodeError:
            pass
    if isinstance(verbose, dict):
        addr = verbose.get("address", verbose)
        picked = []
        for k in _SITE_KEYS:
            if addr.get(k):
                picked.append(str(addr[k]))
                break
        for k in _AREA_KEYS:
            if addr.get(k):
                picked.append(str(addr[k]))
                break
        if picked:
            return ", ".join(_dedupe(picked)[:parts])
        verbose = verbose.get("display_name", "")
    tokens = [t.strip() for t in str(verbose).replace("\t", ",").split(",")]
    keep = _dedupe([t for t in tokens if _useful(t)])
    if not keep:
        return ""
    if len(keep) <= parts:
        return ", ".join(keep)
    # Most specific, then the broadest surviving layer, which is the county.
    return ", ".join([keep[0]] + keep[-(parts - 1):]) if parts > 1 else keep[0]


# --------------------------------------------------------------------------
# Grid references. Recording schemes ask for one, and it is a pure calculation
# from the position already in the photograph.
_GB_LETTERS = "ABCDEFGHJKLMNOPQRSTUVWXYZ"
_IE_LETTERS = "ABCDEFGHJKLMNOPQRSTUVWXYZ"

# (semi major, semi minor) of the ellipsoid the grid is drawn on
_AIRY = (6377563.396, 6356256.909)                  # Airy 1830, Great Britain
_AIRY_MOD = (6377340.189, 6356034.447)              # Airy Modified, Ireland

# Helmert from WGS84 to the local datum: tx, ty, tz, parts per million,
# then the three rotations in seconds of arc.
_TO_OSGB36 = (-446.448, 125.157, -542.060, 20.4894, -0.1502, -0.2470, -0.8421)
_TO_IRE65 = (-482.530, 130.596, -564.557, -8.150, -1.042, -0.214, -0.631)

# Transverse Mercator: scale, origin latitude, origin longitude, false easting,
# false northing, and how far the grid runs before it stops meaning anything.
_GB_TM = (0.9996012717, 49.0, -2.0, 400000, -100000, 700000, 1300000)
_IE_TM = (1.000035, 53.5, -8.0, 200000, 250000, 500000, 500000)

# The island of Ireland, roughly, for deciding which grid a position belongs to.
_IRELAND = [(55.45, -7.4), (55.30, -6.0), (54.55, -5.4), (54.05, -5.9),
            (53.35, -5.9), (52.15, -6.1), (51.90, -6.9), (51.42, -8.3),
            (51.55, -9.4), (51.75, -10.5), (52.55, -10.1), (53.30, -10.3),
            (54.00, -10.2), (54.35, -9.0), (55.20, -8.6), (55.40, -7.9)]


def _in_ireland(lat: float, lon: float) -> bool:
    inside, n = False, len(_IRELAND)
    for i in range(n):
        y1, x1 = _IRELAND[i]
        y2, x2 = _IRELAND[(i + 1) % n]
        if (y1 > lat) != (y2 > lat) and lon < x1 + (lat - y1) / (y2 - y1) * (x2 - x1):
            inside = not inside
    return inside


def _to_datum(lat, lon, ellipsoid, helmert):
    """WGS84 degrees to latitude and longitude on a local datum, by Helmert."""
    a, b = 6378137.0, 6356752.314245                # WGS84
    e2 = (a * a - b * b) / (a * a)
    p, l = math.radians(lat), math.radians(lon)
    nu = a / math.sqrt(1 - e2 * math.sin(p) ** 2)
    x = nu * math.cos(p) * math.cos(l)
    y = nu * math.cos(p) * math.sin(l)
    z = (1 - e2) * nu * math.sin(p)
    tx, ty, tz, ppm, rxs, rys, rzs = helmert
    s = ppm * 1e-6
    rx, ry, rz = (math.radians(v / 3600) for v in (rxs, rys, rzs))
    x2 = tx + x * (1 + s) - y * rz + z * ry
    y2 = ty + x * rz + y * (1 + s) - z * rx
    z2 = tz - x * ry + y * rx + z * (1 + s)
    a2, b2 = ellipsoid
    e2b = (a2 * a2 - b2 * b2) / (a2 * a2)
    p2 = math.atan2(z2, math.sqrt(x2 * x2 + y2 * y2) * (1 - e2b))
    for _ in range(12):
        nu2 = a2 / math.sqrt(1 - e2b * math.sin(p2) ** 2)
        p2 = math.atan2(z2 + e2b * nu2 * math.sin(p2), math.sqrt(x2 * x2 + y2 * y2))
    return p2, math.atan2(y2, x2)


def _project(p2, l2, ellipsoid, tm):
    """Transverse Mercator, the projection both grids are drawn with."""
    a2, b2 = ellipsoid
    e2b = (a2 * a2 - b2 * b2) / (a2 * a2)
    F0, lat0, lon0, E0, N0 = tm[0], math.radians(tm[1]), math.radians(tm[2]), tm[3], tm[4]
    n = (a2 - b2) / (a2 + b2)
    nu = a2 * F0 / math.sqrt(1 - e2b * math.sin(p2) ** 2)
    rho = a2 * F0 * (1 - e2b) / (1 - e2b * math.sin(p2) ** 2) ** 1.5
    eta2 = nu / rho - 1
    dp, sp = p2 - lat0, p2 + lat0
    M = b2 * F0 * (
        (1 + n + 1.25 * n * n + 1.25 * n ** 3) * dp
        - (3 * n + 3 * n * n + 2.625 * n ** 3) * math.sin(dp) * math.cos(sp)
        + (1.875 * n * n + 1.875 * n ** 3) * math.sin(2 * dp) * math.cos(2 * sp)
        - (35 / 24) * n ** 3 * math.sin(3 * dp) * math.cos(3 * sp))
    s2, cp, tp = math.sin(p2), math.cos(p2), math.tan(p2)
    I = M + N0
    II = nu / 2 * s2 * cp
    III = nu / 24 * s2 * cp ** 3 * (5 - tp ** 2 + 9 * eta2)
    IIIA = nu / 720 * s2 * cp ** 5 * (61 - 58 * tp ** 2 + tp ** 4)
    IV = nu * cp
    V = nu / 6 * cp ** 3 * (nu / rho - tp ** 2)
    VI = nu / 120 * cp ** 5 * (5 - 18 * tp ** 2 + tp ** 4 + 14 * eta2 - 58 * tp ** 2 * eta2)
    d = l2 - lon0
    return (E0 + IV * d + V * d ** 3 + VI * d ** 5,
            I + II * d ** 2 + III * d ** 4 + IIIA * d ** 6)


def _letters_gb(E, N):
    e100, n100 = int(E // 100000), int(N // 100000)
    i = 19 - n100 - (19 - n100) % 5 + (e100 + 10) // 5
    j = (19 - n100) * 5 % 25 + e100 % 5
    if not (0 <= i < 25 and 0 <= j < 25):
        return ""
    return _GB_LETTERS[i] + _GB_LETTERS[j]


def _letters_ie(E, N):
    e100, n100 = int(E // 100000), int(N // 100000)
    if not (0 <= e100 < 5 and 0 <= n100 < 5):
        return ""
    return _IE_LETTERS[(4 - n100) * 5 + e100]


def gridref(lat: float, lon: float, digits: int = 8, system: str = "auto"):
    """(reference, system) for a position, or ('', '') where no grid applies.
    digits is the total number of figures: 8 gives ten metre precision.

    'auto' picks the grid the position belongs to. Naming a system means what it
    says: both grids are defined well beyond the land they were drawn for, so
    forcing one will happily give a reference in the middle of the sea."""
    if lat is None or lon is None:
        return "", ""
    order = ["irish", "osgb"] if (system == "auto" and _in_ireland(lat, lon)) else \
            (["osgb", "irish"] if system == "auto" else [system])
    for which in order:
        if which == "osgb":
            p, l = _to_datum(lat, lon, _AIRY, _TO_OSGB36)
            E, N = _project(p, l, _AIRY, _GB_TM)
            limit_e, limit_n = _GB_TM[5], _GB_TM[6]
            letters = _letters_gb(E, N) if 0 <= E < limit_e and 0 <= N < limit_n else ""
        else:
            p, l = _to_datum(lat, lon, _AIRY_MOD, _TO_IRE65)
            E, N = _project(p, l, _AIRY_MOD, _IE_TM)
            limit_e, limit_n = _IE_TM[5], _IE_TM[6]
            letters = _letters_ie(E, N) if 0 <= E < limit_e and 0 <= N < limit_n else ""
        if letters:
            half = max(1, digits // 2)
            div = 10 ** (5 - half)
            return (f"{letters}{int(E % 100000) // div:0{half}d}"
                    f"{int(N % 100000) // div:0{half}d}", which)
    return "", ""


def osgb_gridref(lat: float, lon: float, digits: int = 8) -> str:
    """The British grid only, kept because it is what the tests pin."""
    ref, _system = gridref(lat, lon, digits, system="osgb")
    return ref


def _unproject(E, N, ellipsoid, tm):
    """Grid coordinates back to latitude and longitude on the local datum."""
    a2, b2 = ellipsoid
    e2b = (a2 * a2 - b2 * b2) / (a2 * a2)
    F0, lat0, lon0, E0, N0 = tm[0], math.radians(tm[1]), math.radians(tm[2]), tm[3], tm[4]
    n = (a2 - b2) / (a2 + b2)
    p = lat0
    M = 0.0
    for _ in range(20):
        p += (N - N0 - M) / (a2 * F0)
        dp, sp = p - lat0, p + lat0
        M = b2 * F0 * (
            (1 + n + 1.25 * n * n + 1.25 * n ** 3) * dp
            - (3 * n + 3 * n * n + 2.625 * n ** 3) * math.sin(dp) * math.cos(sp)
            + (1.875 * n * n + 1.875 * n ** 3) * math.sin(2 * dp) * math.cos(2 * sp)
            - (35 / 24) * n ** 3 * math.sin(3 * dp) * math.cos(3 * sp))
        if abs(N - N0 - M) < 1e-5:
            break
    nu = a2 * F0 / math.sqrt(1 - e2b * math.sin(p) ** 2)
    rho = a2 * F0 * (1 - e2b) / (1 - e2b * math.sin(p) ** 2) ** 1.5
    eta2 = nu / rho - 1
    tp, sec = math.tan(p), 1 / math.cos(p)
    VII = tp / (2 * rho * nu)
    VIII = tp / (24 * rho * nu ** 3) * (5 + 3 * tp ** 2 + eta2 - 9 * tp ** 2 * eta2)
    IX = tp / (720 * rho * nu ** 5) * (61 + 90 * tp ** 2 + 45 * tp ** 4)
    X = sec / nu
    XI = sec / (6 * nu ** 3) * (nu / rho + 2 * tp ** 2)
    XII = sec / (120 * nu ** 5) * (5 + 28 * tp ** 2 + 24 * tp ** 4)
    XIIA = sec / (5040 * nu ** 7) * (61 + 662 * tp ** 2 + 1320 * tp ** 4 + 720 * tp ** 6)
    d = E - E0
    lat = p - VII * d ** 2 + VIII * d ** 4 - IX * d ** 6
    lon = lon0 + X * d - XI * d ** 3 + XII * d ** 5 - XIIA * d ** 7
    return lat, lon


def _from_datum(p2, l2, ellipsoid, helmert):
    """Local datum back to WGS84. The Helmert parameters run the other way,
    which is accurate to millimetres at this scale."""
    a2, b2 = ellipsoid
    e2b = (a2 * a2 - b2 * b2) / (a2 * a2)
    nu = a2 / math.sqrt(1 - e2b * math.sin(p2) ** 2)
    x = nu * math.cos(p2) * math.cos(l2)
    y = nu * math.cos(p2) * math.sin(l2)
    z = (1 - e2b) * nu * math.sin(p2)
    tx, ty, tz, ppm, rxs, rys, rzs = (-v for v in helmert)
    s = ppm * 1e-6
    rx, ry, rz = (math.radians(v / 3600) for v in (rxs, rys, rzs))
    x2 = tx + x * (1 + s) - y * rz + z * ry
    y2 = ty + x * rz + y * (1 + s) - z * rx
    z2 = tz - x * ry + y * rx + z * (1 + s)
    a, b = 6378137.0, 6356752.314245
    e2 = (a * a - b * b) / (a * a)
    p = math.atan2(z2, math.sqrt(x2 * x2 + y2 * y2) * (1 - e2))
    for _ in range(12):
        nu2 = a / math.sqrt(1 - e2 * math.sin(p) ** 2)
        p = math.atan2(z2 + e2 * nu2 * math.sin(p), math.sqrt(x2 * x2 + y2 * y2))
    return math.degrees(p), math.degrees(math.atan2(y2, x2))


# How far a reference of each length reaches, and what to call it.
PRECISIONS = [("10m", 8, 10), ("100m", 6, 100), ("1km", 4, 1000),
              ("2km", 4, 2000), ("10km", 2, 10000), ("100km", 0, 100000)]
PRECISION_METRES = {name: m for name, _d, m in PRECISIONS}


def blur_position(lat, lon, precision: str, system: str = "auto"):
    """Coarsen a position to a whole grid square, the way a recording scheme
    asks for a sensitive record. Returns the centre of the square, the shortened
    reference, and how far the truth could be from what is given.

    The point returned is the centre of the same square the reference names, so
    the two can never disagree."""
    ref, which = gridref(lat, lon, 10, system)
    metres = PRECISION_METRES.get(precision)
    if not ref or not metres:
        return lat, lon, ref, None
    ellipsoid, tm = ((_AIRY, _GB_TM) if which == "osgb" else (_AIRY_MOD, _IE_TM))
    p, l = _to_datum(lat, lon, ellipsoid,
                     _TO_OSGB36 if which == "osgb" else _TO_IRE65)
    E, N = _project(p, l, ellipsoid, tm)
    cE = (E // metres) * metres + metres / 2
    cN = (N // metres) * metres + metres / 2
    p2, l2 = _unproject(cE, cN, ellipsoid, tm)
    lat2, lon2 = _from_datum(p2, l2, ellipsoid,
                             _TO_OSGB36 if which == "osgb" else _TO_IRE65)
    places = 5 if metres < 1000 else (3 if metres < 10000 else 2)
    return (round(lat2, places), round(lon2, places), blur(ref, precision),
            round(metres / 2 * math.sqrt(2)))


def blur(ref: str, precision: str) -> str:
    """Cut a grid reference down to a coarser square. 2 km squares are the
    tetrad, written as the 10 km square plus a letter, which is how recording
    schemes write them."""
    if not ref or precision in ("", "exact", None):
        return ref
    letters = "".join(c for c in ref if c.isalpha())
    digits = "".join(c for c in ref if c.isdigit())
    if not digits or len(digits) % 2:
        return ref
    half = len(digits) // 2
    east, north = digits[:half], digits[half:]
    if precision == "2km":
        if half < 2:
            return ref
        e10, n10 = int(east[1]), int(north[1])
        # DINTY tetrads: 25 letters with O left out, up each column from the
        # south west corner of the 10 km square.
        letter = "ABCDEFGHIJKLMNPQRSTUVWXYZ"[(e10 // 2) * 5 + (n10 // 2)]
        return f"{letters}{east[0]}{north[0]}{letter}"
    want = dict((name, d) for name, d, _m in PRECISIONS).get(precision)
    if want is None:
        return ref
    keep = max(0, want // 2)
    return f"{letters}{east[:keep]}{north[:keep]}"
# --------------------------------------------------------------------------
# storing what a position is called
def place_key(lat: float, lon: float, dp: int = 4) -> str:
    """Positions rounded to about 10 m, so one lookup covers a whole burst."""
    return f"{lat:.{dp}f},{lon:.{dp}f}"


def store(cx, lat, lon, verbose, parts=2, source="import") -> str:
    short = shorten(verbose, parts)
    key = place_key(lat, lon)
    cx.execute("INSERT INTO places(key, lat, lon, verbose, short, source) "
               "VALUES(?,?,?,?,?,?) ON CONFLICT(key) DO UPDATE SET "
               "verbose=excluded.verbose, short=excluded.short, source=excluded.source",
               (key, lat, lon, str(verbose), short, source))
    return short


def apply_to_photos(cx) -> int:
    """Copy every known place onto the photographs taken there."""
    n = 0
    for p in cx.execute("SELECT key, verbose, short FROM places").fetchall():
        lat, _, lon = p["key"].partition(",")
        n += cx.execute(
            "UPDATE photos SET locality=?, locality_full=? "
            "WHERE lat IS NOT NULL AND printf('%.4f', lat)=? AND printf('%.4f', lon)=?",
            (p["short"], p["verbose"], lat, lon)).rowcount
    cx.commit()
    return n


def reshorten(cx, parts=2) -> int:
    for p in cx.execute("SELECT key, verbose FROM places").fetchall():
        cx.execute("UPDATE places SET short=? WHERE key=?",
                   (shorten(p["verbose"], parts), p["key"]))
    cx.commit()
    return apply_to_photos(cx)


def pending(cx) -> list:
    """Positions that have no name yet, one per rounded position."""
    # Group by the expression, not by an alias: places.key is in scope here and
    # would swallow every row into one NULL group.
    return [dict(r) for r in cx.execute(
        "SELECT printf('%.4f', p.lat) || ',' || printf('%.4f', p.lon) AS place_key, "
        "AVG(p.lat) lat, AVG(p.lon) lon, COUNT(*) n FROM photos p "
        "LEFT JOIN places pl ON pl.key = printf('%.4f', p.lat)||','||printf('%.4f', p.lon) "
        "WHERE p.lat IS NOT NULL AND pl.key IS NULL "
        "GROUP BY printf('%.4f', p.lat) || ',' || printf('%.4f', p.lon) "
        "ORDER BY n DESC")]


def lookup(lat: float, lon: float, email: str = "", zoom: int = 16, pause: float = 1.1):
    """Ask OpenStreetMap what is at a position. Network. Called only by the
    explicit `locality lookup` command, one request a second as they ask."""
    q = urllib.parse.urlencode({"lat": f"{lat:.6f}", "lon": f"{lon:.6f}", "format": "jsonv2",
                                "zoom": zoom, "addressdetails": 1,
                                **({"email": email} if email else {})})
    req = urllib.request.Request(
        "https://nominatim.openstreetmap.org/reverse?" + q,
        headers={"User-Agent": "entolog/1.1 (species recording; local use)"})
    with urllib.request.urlopen(req, timeout=20) as r:
        data = json.load(r)
    time.sleep(pause)
    return data
