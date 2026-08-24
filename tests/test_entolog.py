import json
import sys
import tempfile
import unittest
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import fixtures
from entolog import db, exifread, export, records, scan, server
from entolog import profile as P


class Exif(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def test_reads_date_position_and_orientation(self):
        p = fixtures.write(self.tmp / "a.jpg")
        ex = exifread.read(p)
        self.assertEqual(ex["datetime_original"], "2026-06-14T09:30:00")
        self.assertAlmostEqual(ex["lat"], 51.752, places=3)
        self.assertAlmostEqual(ex["lon"], -1.2577, places=3)   # W becomes negative
        self.assertEqual(ex["orientation"], 6)
        self.assertEqual(ex["camera"], "TESTCAM 1")
        self.assertEqual(ex["width"], 6000)

    def test_southern_and_eastern_hemispheres(self):
        p = fixtures.write(self.tmp / "s.jpg", lat=(33, 55, 0.0), lon=(151, 12, 0.0),
                           lat_ref="S", lon_ref="E")
        ex = exifread.read(p)
        self.assertLess(ex["lat"], 0)
        self.assertGreater(ex["lon"], 0)

    def test_photo_without_gps(self):
        p = fixtures.write(self.tmp / "n.jpg", gps=False)
        ex = exifread.read(p)
        self.assertNotIn("lat", ex)
        self.assertTrue(ex["datetime_original"])

    def test_junk_file_does_not_raise(self):
        p = self.tmp / "junk.jpg"
        p.write_bytes(b"\xff\xd8not really a jpeg")
        self.assertIsInstance(exifread.read(p), dict)


class Scan(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.cx = db.connect(self.tmp / "t.db")
        self.addCleanup(self.cx.close)

    def _shoot(self, name, minutes=0, lat=(51, 45, 7.2), sub=None):
        base = datetime(2026, 6, 14, 9, 30) + timedelta(minutes=minutes)
        d = self.tmp / sub if sub else self.tmp
        d.mkdir(exist_ok=True)
        return fixtures.write(d / name, dt=base.strftime("%Y:%m:%d %H:%M:%S"), lat=lat)

    def test_groups_a_burst_and_splits_on_a_time_gap(self):
        for i in range(3):
            self._shoot(f"burst{i}.jpg", minutes=i * 0.5)
        self._shoot("later.jpg", minutes=30)
        r = scan.scan(self.cx, [self.tmp])
        self.assertEqual(r["added"], 4)
        self.assertEqual(r["groups"], 2)
        g = [row["group_id"] for row in
             self.cx.execute("SELECT group_id FROM photos ORDER BY seq")]
        self.assertEqual(g, [1, 1, 1, 2])

    def test_splits_when_the_recorder_walks_away(self):
        self._shoot("a.jpg", 0)
        self._shoot("b.jpg", 0.2, lat=(52, 45, 7.2))   # a degree north, far more than 60 m
        self.assertEqual(scan.scan(self.cx, [self.tmp])["groups"], 2)

    def test_rescanning_changes_nothing(self):
        self._shoot("a.jpg")
        scan.scan(self.cx, [self.tmp])
        again = scan.scan(self.cx, [self.tmp])
        self.assertEqual(again["added"], 0)
        self.assertEqual(again["unchanged"], 1)

    def test_a_renamed_photo_keeps_its_determination(self):
        p = self._shoot("old.jpg")
        scan.scan(self.cx, [self.tmp])
        pid = self.cx.execute("SELECT id FROM photos").fetchone()["id"]
        server.save_record(self.cx, pid, {"species": "Vespa crabro", "stage": "adult"})
        p.rename(self.tmp / "new.jpg")
        self.cx.execute("DELETE FROM photos WHERE id=?", (pid,))  # simulate a fresh row
        self.cx.commit()
        scan.scan(self.cx, [self.tmp])
        row = self.cx.execute(
            "SELECT fv.value FROM field_values fv JOIN photos p ON p.id=fv.photo_id "
            "WHERE p.filename='new.jpg' AND fv.field='species'").fetchone()
        self.assertEqual(row["value"], "Vespa crabro")

    def test_missing_exif_date_falls_back_to_the_file_and_says_so(self):
        (self.tmp / "bare.jpg").write_bytes(b"\xff\xd8\xff\xd9")
        scan.scan(self.cx, [self.tmp])
        row = self.cx.execute("SELECT taken_at, taken_source FROM photos").fetchone()
        self.assertEqual(row["taken_source"], "file-mtime")
        self.assertTrue(row["taken_at"])


class Records(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.cx = db.connect(self.tmp / "t.db")
        self.addCleanup(self.cx.close)
        for i in range(3):
            fixtures.write(self.tmp / f"p{i}.jpg",
                           dt=f"2026:06:14 09:3{i}:00")
        fixtures.write(self.tmp / "z.jpg", dt="2026:06:14 15:00:00")
        scan.scan(self.cx, [self.tmp])
        self.ids = [r["id"] for r in self.cx.execute("SELECT id FROM photos ORDER BY seq")]

    def test_one_determination_covers_the_whole_event(self):
        touched = server.save_record(self.cx, self.ids[0],
                                     {"species": "Andrena fulva", "sex": "female"},
                                     apply_group=True)
        self.assertEqual(len(touched), 3)
        n = self.cx.execute("SELECT COUNT(*) c FROM field_values "
                            "WHERE field='species' AND value='Andrena fulva'").fetchone()["c"]
        self.assertEqual(n, 3)

    def test_single_photo_save_leaves_the_others_alone(self):
        server.save_record(self.cx, self.ids[0], {"species": "Pieris rapae"})
        n = self.cx.execute("SELECT COUNT(*) c FROM field_values "
                            "WHERE field='species' AND value!=''").fetchone()["c"]
        self.assertEqual(n, 1)

    def test_species_list_learns_as_you_type(self):
        server.save_record(self.cx, self.ids[0], {"species": "Bombus terrestris"})
        server.save_record(self.cx, self.ids[1], {"species": "Bombus terrestris"})
        row = self.cx.execute("SELECT uses FROM terms WHERE field='species' "
                              "AND value='Bombus terrestris'").fetchone()
        self.assertEqual(row["uses"], 2)

    def test_filters(self):
        server.save_record(self.cx, self.ids[0], {"species": "Aglais urticae"})
        self.assertEqual(len(server.list_photos(self.cx, "done")), 1)
        self.assertEqual(len(server.list_photos(self.cx, "todo")), 3)
        self.assertEqual(len(server.list_photos(self.cx, "all", q="urticae")), 1)


class Export(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.cx = db.connect(self.tmp / "t.db")
        self.addCleanup(self.cx.close)
        fixtures.write(self.tmp / "IMG_0042.jpg")
        scan.scan(self.cx, [self.tmp])
        pid = self.cx.execute("SELECT id FROM photos").fetchone()["id"]
        server.save_record(self.cx, pid, {
            "species": "Vespa crabro", "stage": "adult", "sex": "female",
            "comments": "on ivy, sunny bank", "confidence": "certain"})

    def test_csv_is_the_table_that_was_asked_for(self):
        text = export.render(self.cx, "csv")
        head, row = text.strip().splitlines()
        self.assertEqual(head, "filename,date,time,latitude,longitude,species,stage,sex,comments")
        self.assertIn("IMG_0042.jpg", row)
        self.assertIn("2026-06-14", row)
        self.assertIn("51.752", row)
        self.assertIn("Vespa crabro", row)
        self.assertIn("on ivy, sunny bank", text)   # quoted, so the comma survives

    def test_undetermined_photos_stay_out_unless_asked_for(self):
        fixtures.write(self.tmp / "blank.jpg", dt="2026:06:14 11:00:00")
        scan.scan(self.cx, [self.tmp])
        self.assertEqual(len(export.render(self.cx, "csv").strip().splitlines()), 2)
        self.assertEqual(len(export.render(self.cx, "csv", only_determined=False)
                             .strip().splitlines()), 3)

    def test_darwin_core_uses_the_standard_terms(self):
        text = export.render(self.cx, "dwc")
        self.assertIn("scientificName", text)
        self.assertIn("decimalLatitude", text)
        self.assertIn("lifeStage", text)
        self.assertIn("HumanObservation", text)
        self.assertIn("WGS84", text)

    def test_geojson_only_carries_located_records(self):
        obj = json.loads(export.render(self.cx, "geojson"))
        self.assertEqual(len(obj["features"]), 1)
        lon, lat = obj["features"][0]["geometry"]["coordinates"]
        self.assertAlmostEqual(lat, 51.752, places=3)

    def test_custom_columns(self):
        text = export.render(self.cx, "csv", columns=["filename", "species", "position"])
        self.assertTrue(text.startswith("filename,species,position"))


class Server(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import threading
        cls.tmp = Path(tempfile.mkdtemp())
        cx = db.connect(cls.tmp / "t.db")
        fixtures.write(cls.tmp / "a.jpg")
        scan.scan(cx, [cls.tmp])
        cls.httpd, cls.url = server.serve(cls.tmp / "t.db", port=8899)
        cls.base, _, cls.token = cls.url.partition("?t=")
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()

    def get(self, path):
        sep = "&" if "?" in path else "?"
        return urllib.request.urlopen(f"{self.base.rstrip('/')}{path}{sep}t={self.token}")

    def test_serves_the_app_and_the_state(self):
        self.assertIn(b"entolog", self.get("/").read())
        st = json.loads(self.get("/api/state").read())
        self.assertEqual(st["total"], 1)
        self.assertEqual(st["profile"]["name"], "insects")
        stage = next(f for f in st["profile"]["fields"] if f["name"] == "stage")
        self.assertIn("adult", stage["choices"])

    def test_rejects_a_request_without_the_token(self):
        with self.assertRaises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(self.base + "/api/state")
        self.assertEqual(e.exception.code, 403)

    def test_export_downloads(self):
        r = self.get("/api/export?fmt=csv&all=1")
        self.assertIn("attachment", r.headers["Content-Disposition"])
        self.assertIn("filename,date", r.read().decode())

    def test_serves_an_image(self):
        pid = json.loads(self.get("/api/photos").read())[0]["id"]
        r = self.get(f"/img/{pid}?size=full")
        self.assertTrue(r.read().startswith(b"\xff\xd8"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
