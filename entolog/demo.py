"""A folder of photographs to try entolog on, without a camera card.

The pictures are drawings, not photographs, and say so. Everything else is real:
the EXIF dates and positions are written properly, so the scan, the specimen
events, the grid references and every export behave exactly as they will on a
real card.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta
from pathlib import Path

from . import demodata, exifwrite

# A morning's walk: Wytham Woods, Oxfordshire, which is about as recorded a
# square mile as exists.
START = (51.77150, -1.33550)

CHECKLIST = [
    ("Vespa crabro", "hornet"), ("Vespula vulgaris", "common wasp"),
    ("Bombus terrestris", "buff-tailed bumblebee"), ("Bombus lapidarius", "red-tailed bumblebee"),
    ("Bombus pascuorum", "common carder bee"), ("Andrena fulva", "tawny mining bee"),
    ("Apis mellifera", "honey bee"), ("Aglais urticae", "small tortoiseshell"),
    ("Aglais io", "peacock"), ("Pieris rapae", "small white"),
    ("Maniola jurtina", "meadow brown"), ("Episyrphus balteatus", "marmalade hoverfly"),
    ("Volucella zonaria", "hornet mimic hoverfly"), ("Eristalis tenax", "drone fly"),
    ("Coccinella septempunctata", "seven-spot ladybird"),
    ("Harmonia axyridis", "harlequin ladybird"), ("Pyrrhosoma nymphula", "large red damselfly"),
    ("Calopteryx splendens", "banded demoiselle"), ("Deilephila elpenor", "elephant hawk-moth"),
    ("Noctua pronuba", "large yellow underwing"), ("Autographa gamma", "silver Y"),
    ("Forficula auricularia", "common earwig"), ("Pyrochroa serraticornis", "red-headed cardinal beetle"),
    ("Rhagonycha fulva", "common red soldier beetle"),
]


def build(folder, events=9, seed=7, start_time=None) -> dict:
    """Write the demo photographs. Returns what was made."""
    folder = Path(folder).expanduser()
    folder.mkdir(parents=True, exist_ok=True)
    rnd = random.Random(seed)
    when = start_time or datetime(2026, 6, 14, 9, 12, 0)
    lat, lon = START
    made, n = [], 0
    for event in range(events):
        when += timedelta(minutes=rnd.randint(4, 22))       # walk to the next spot
        lat += rnd.uniform(-0.0016, 0.0016)
        lon += rnd.uniform(-0.0016, 0.0016)
        for _shot in range(rnd.randint(1, 4)):              # a burst of the same insect
            n += 1
            when += timedelta(seconds=rnd.randint(4, 40))
            path = folder / f"IMG_{n:04d}.jpg"
            path.write_bytes(exifwrite.with_exif(
                demodata.IMAGES[n % len(demodata.IMAGES)],
                dt=when.strftime("%Y:%m:%d %H:%M:%S"), lat=lat, lon=lon,
                lat_ref="N", lon_ref="W" if lon < 0 else "E",
                model="entolog demo", width=400, height=300))
            made.append(path)
    # One photograph with no position and no date, because a real card has one.
    odd = folder / "IMG_9999.jpg"
    odd.write_bytes(demodata.IMAGES[0])
    made.append(odd)
    return {"folder": folder, "photos": made, "events": events}
