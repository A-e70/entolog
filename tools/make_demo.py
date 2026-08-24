"""Make a folder of fake 'photographs' with real EXIF, to try entolog on before
pointing it at a real card. Needs Pillow only for this script, not for entolog."""
import random
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests import fixtures  # noqa: E402

try:
    from PIL import Image, ImageDraw
except ImportError:
    sys.exit("this demo generator needs Pillow: pip install pillow")

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "demo-photos")
OUT.mkdir(parents=True, exist_ok=True)
rnd = random.Random(7)
t = datetime(2026, 6, 14, 9, 12, 0)
lat, lon = 51.7520, 1.2577          # degrees; the fixture writer wants d, m, s
n = 0
for event in range(9):
    t += timedelta(minutes=rnd.randint(4, 22))
    lat += rnd.uniform(-0.002, 0.002)
    lon += rnd.uniform(-0.002, 0.002)
    for shot in range(rnd.randint(1, 4)):
        n += 1
        t += timedelta(seconds=rnd.randint(3, 40))
        im = Image.new("RGB", (900, 600), (rnd.randint(20, 60), rnd.randint(60, 110), 40))
        d = ImageDraw.Draw(im)
        for _ in range(60):
            x, y = rnd.randint(0, 880), rnd.randint(0, 580)
            d.ellipse([x, y, x + rnd.randint(6, 40), y + rnd.randint(6, 40)],
                      fill=(rnd.randint(80, 220), rnd.randint(80, 200), rnd.randint(30, 90)))
        d.text((20, 20), f"specimen event {event + 1}, shot {shot + 1}", fill=(255, 255, 255))
        def dms(v):
            deg = int(abs(v)); m = int((abs(v) - deg) * 60)
            return (deg, m, round(((abs(v) - deg) * 60 - m) * 60, 2))
        exif = fixtures._tiff(dt=t.strftime("%Y:%m:%d %H:%M:%S"), lat=dms(lat), lon=dms(lon),
                              lat_ref="N", lon_ref="W" if lon > 0 else "E",
                              orientation=1, model="DEMO CAM")
        im.save(OUT / f"IMG_{n:04d}.jpg", exif=b"Exif\0\0" + exif, quality=80)
print(f"{n} demo photographs in {OUT}")
