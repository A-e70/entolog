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
# OSGB grid reference. Recording schemes ask for one, and it is a pure
# calculation from the position already in the photograph.
_LETTERS = "ABCDEFGHJKLMNOPQRSTUVWXYZ"


def osgb_gridref(lat: float, lon: float, digits: int = 8) -> str:
    """WGS84 degrees to an Ordnance Survey grid reference, '' if outside Britain.
    digits is the total number of numeric figures: 8 gives 10 m precision."""
    a, b = 6378137.0, 6356752.314245                       # WGS84
    e2 = (a * a - b * b) / (a * a)
    p, l = math.radians(lat), math.radians(lon)
    nu = a / math.sqrt(1 - e2 * math.sin(p) ** 2)
    x = nu * math.cos(p) * math.cos(l)
    y = nu * math.cos(p) * math.sin(l)
    z = (1 - e2) * nu * math.sin(p)
    # Helmert, WGS84 to OSGB36
    tx, ty, tz, s = -446.448, 125.157, -542.060, 20.4894e-6
    rx, ry, rz = (math.radians(v / 3600) for v in (-0.1502, -0.2470, -0.8421))
    x2 = tx + x * (1 + s) - y * rz + z * ry
    y2 = ty + x * rz + y * (1 + s) - z * rx
    z2 = tz - x * ry + y * rx + z * (1 + s)
    a2, b2 = 6377563.396, 6356256.909                      # Airy 1830
    e2b = (a2 * a2 - b2 * b2) / (a2 * a2)
    p2 = math.atan2(z2, math.sqrt(x2 * x2 + y2 * y2) * (1 - e2b))
    for _ in range(12):
        nu2 = a2 / math.sqrt(1 - e2b * math.sin(p2) ** 2)
        p2 = math.atan2(z2 + e2b * nu2 * math.sin(p2), math.sqrt(x2 * x2 + y2 * y2))
    l2 = math.atan2(y2, x2)
    # Transverse Mercator
    F0, lat0, lon0, E0, N0 = 0.9996012717, math.radians(49), math.radians(-2), 400000, -100000
    n = (a2 - b2) / (a2 + b2)
    nu2 = a2 * F0 / math.sqrt(1 - e2b * math.sin(p2) ** 2)
    rho = a2 * F0 * (1 - e2b) / (1 - e2b * math.sin(p2) ** 2) ** 1.5
    eta2 = nu2 / rho - 1
    dp, sp = p2 - lat0, p2 + lat0
    M = b2 * F0 * (
        (1 + n + 1.25 * n * n + 1.25 * n ** 3) * dp
        - (3 * n + 3 * n * n + 2.625 * n ** 3) * math.sin(dp) * math.cos(sp)
        + (1.875 * n * n + 1.875 * n ** 3) * math.sin(2 * dp) * math.cos(2 * sp)
        - (35 / 24) * n ** 3 * math.sin(3 * dp) * math.cos(3 * sp))
    sp2, cp, tp = math.sin(p2), math.cos(p2), math.tan(p2)
    I = M + N0
    II = nu2 / 2 * sp2 * cp
    III = nu2 / 24 * sp2 * cp ** 3 * (5 - tp ** 2 + 9 * eta2)
    IIIA = nu2 / 720 * sp2 * cp ** 5 * (61 - 58 * tp ** 2 + tp ** 4)
    IV = nu2 * cp
    V = nu2 / 6 * cp ** 3 * (nu2 / rho - tp ** 2)
    VI = nu2 / 120 * cp ** 5 * (5 - 18 * tp ** 2 + tp ** 4 + 14 * eta2 - 58 * tp ** 2 * eta2)
    d = l2 - lon0
    N = I + II * d ** 2 + III * d ** 4 + IIIA * d ** 6
    E = E0 + IV * d + V * d ** 3 + VI * d ** 5

    if not (0 <= E < 700000 and 0 <= N < 1300000):
        return ""
    e100, n100 = int(E // 100000), int(N // 100000)
    i = 19 - n100 - (19 - n100) % 5 + (e100 + 10) // 5
    j = (19 - n100) * 5 % 25 + e100 % 5
    if not (0 <= i < 25 and 0 <= j < 25):
        return ""
    half = max(1, digits // 2)
    div = 10 ** (5 - half)
    return (f"{_LETTERS[i]}{_LETTERS[j]}"
            f"{int(E % 100000) // div:0{half}d}{int(N % 100000) // div:0{half}d}")


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
