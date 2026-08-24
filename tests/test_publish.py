"""Getting records out of entolog and into a recording scheme: the archive, the
iRecord columns, and the cleaning pass that runs before either."""

import io
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import fixtures
from entolog import check, db, demo, exifread, exifwrite, export, records, scan, server
from entolog import profile as P

DWC = "http://rs.tdwg.org/dwc/terms/"


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.cx = db.connect(self.tmp / "t.db")
        self.addCleanup(self.cx.close)
        for i in range(3):
            fixtures.write(self.tmp / f"a{i}.jpg", dt=f"2026:06:14 09:3{i}:00")
        scan.scan(self.cx, [self.tmp])
        self.prof = P.active(self.cx)
        self.ids = [r["id"] for r in self.cx.execute("SELECT id FROM photos ORDER BY seq")]
        server.save_record(self.cx, self.ids[0],
                           {"species": "Vespa crabro", "stage": "adult", "sex": "female",
                            "comments": "on ivy", "confidence": "certain"})


class Archive(Base):
    def zip(self, **kw):
        return zipfile.ZipFile(io.BytesIO(export.dwca(self.cx, **kw)))

    def test_it_is_the_three_files_a_dwc_archive_needs(self):
        self.assertEqual(sorted(self.zip().namelist()),
                         ["eml.xml", "meta.xml", "occurrence.csv"])

    def test_the_descriptor_is_valid_xml_and_describes_every_column(self):
        z = self.zip()
        root = ET.fromstring(z.read("meta.xml").decode())
        ns = {"d": "http://rs.tdwg.org/dwc/text/"}
        core = root.find("d:core", ns)
        self.assertEqual(core.get("rowType"), DWC + "Occurrence")
        self.assertEqual(core.get("ignoreHeaderLines"), "1")
        self.assertEqual(core.get("linesTerminatedBy"), "\\n")
        self.assertEqual(core.find("d:id", ns).get("index"), "0")
        fields = core.findall("d:field", ns)
        header = z.read("occurrence.csv").decode().splitlines()[0].split(",")
        self.assertEqual(len(fields), len(header))
        self.assertEqual(fields[0].get("term"), DWC + "occurrenceID")

    def test_the_terms_gbif_insists_on_are_all_there(self):
        header = self.zip().read("occurrence.csv").decode().splitlines()[0]
        for term in ("occurrenceID", "basisOfRecord", "scientificName",
                     "eventDate", "decimalLatitude", "decimalLongitude",
                     "occurrenceStatus"):
            self.assertIn(term, header)

    def test_the_metadata_carries_the_licence_and_the_recorder(self):
        db.set_meta(self.cx, "recorded_by", "A Naturalist")
        db.set_meta(self.cx, "licence", "CC0")
        eml = self.zip().read("eml.xml").decode()
        ET.fromstring(eml)
        self.assertIn("A Naturalist", eml)
        self.assertIn("CC0 1.0", eml)
        self.assertIn("publicdomain/zero", eml)

    def test_the_default_licence_is_one_gbif_accepts(self):
        eml = self.zip().read("eml.xml").decode()
        self.assertIn("CC BY 4.0", eml)

    def test_an_occurrence_id_is_unique_in_the_world_and_stays_put(self):
        first = self.zip().read("occurrence.csv").decode().splitlines()[1].split(",")[0]
        self.assertTrue(first.startswith("urn:entolog:"))
        self.assertEqual(len(first.split(":")), 4)
        again = self.zip().read("occurrence.csv").decode().splitlines()[1].split(",")[0]
        self.assertEqual(first, again)

    def test_two_databases_do_not_share_occurrence_ids(self):
        other = db.connect(self.tmp / "other.db")
        self.addCleanup(other.close)
        self.assertNotEqual(export.dataset_id(self.cx), export.dataset_id(other))

    def test_the_archive_survives_a_round_trip_through_a_zip_reader(self):
        z = self.zip()
        self.assertIsNone(z.testzip())
        rows = z.read("occurrence.csv").decode().strip().splitlines()
        self.assertEqual(len(rows), 2)

    def test_a_custom_field_reaches_the_archive_under_its_own_term(self):
        prof = P.load("insects")
        prof["fields"].append({"name": "host_plant", "type": "text",
                               "dwc": "associatedTaxa"})
        P.set_active(self.cx, prof)
        server.save_record(self.cx, self.ids[0], {"host_plant": "Hedera helix"})
        z = self.zip()
        self.assertIn("associatedTaxa", z.read("occurrence.csv").decode())
        self.assertIn(DWC + "associatedTaxa", z.read("meta.xml").decode())


class IRecord(Base):
    def test_the_headings_are_the_ones_irecord_offers(self):
        head = export.render(self.cx, "irecord").splitlines()[0]
        self.assertEqual(head, "Species or taxon name,Date,Spatial reference,"
                               "Location name,Recorder Name,Identified By,Quantity,"
                               "Stage,Sex,Occurrence comment,Recorder certainty")

    def test_the_date_is_written_the_way_a_uk_form_expects(self):
        row = export.render(self.cx, "irecord").splitlines()[1]
        self.assertIn("14/06/2026", row)

    def test_the_spatial_reference_prefers_a_grid_reference(self):
        row = export.render(self.cx, "irecord").splitlines()[1].split(",")
        self.assertTrue(row[2].startswith("SP"), row[2])

    def test_it_falls_back_to_latitude_and_longitude_outside_britain(self):
        fixtures.write(self.tmp / "syd.jpg", dt="2026:06:14 12:00:00",
                       lat=(33, 55, 0.0), lon=(151, 12, 0.0), lat_ref="S", lon_ref="E")
        scan.scan(self.cx, [self.tmp])
        pid = self.cx.execute("SELECT id FROM photos WHERE filename='syd.jpg'").fetchone()["id"]
        server.save_record(self.cx, pid, {"species": "Apis mellifera"})
        row = [r for r in export.render(self.cx, "irecord").splitlines()
               if "Apis" in r][0]
        self.assertIn("-33.9", row)

    def test_a_profile_with_its_own_names_still_maps_by_darwin_core_term(self):
        P.set_active(self.cx, "moths", force=True)
        prof = P.active(self.cx)
        records.save(self.cx, prof, self.ids[0],
                     {"taxon": "Noctua pronuba", "count": "4", "notes": "at MV"})
        rows = export.render(self.cx, "irecord").splitlines()
        self.assertIn("Noctua pronuba", rows[1])
        self.assertIn("4", rows[1].split(","))
        self.assertIn("at MV", rows[1])


class Cleaning(Base):
    def codes(self, findings=None):
        return {f["code"] for f in (findings or check.run(self.cx, P.active(self.cx)))}

    def test_a_tidy_database_reports_only_what_is_left_to_do(self):
        self.assertEqual(self.codes() - {"not-recorded-yet"}, set())

    def test_a_record_with_no_position(self):
        fixtures.write(self.tmp / "nogps.jpg", gps=False, dt="2026:06:14 10:00:00")
        scan.scan(self.cx, [self.tmp])
        pid = self.cx.execute("SELECT id FROM photos WHERE filename='nogps.jpg'").fetchone()["id"]
        server.save_record(self.cx, pid, {"species": "Apis mellifera"})
        self.assertIn("no-position", self.codes())

    def test_a_camera_clock_set_to_the_future(self):
        later = (datetime.now() + timedelta(days=400)).strftime("%Y:%m:%d %H:%M:%S")
        fixtures.write(self.tmp / "future.jpg", dt=later)
        scan.scan(self.cx, [self.tmp])
        pid = self.cx.execute("SELECT id FROM photos WHERE filename='future.jpg'").fetchone()["id"]
        server.save_record(self.cx, pid, {"species": "Apis mellifera"})
        self.assertIn("date-in-future", self.codes())

    def test_a_camera_clock_that_reset_itself(self):
        fixtures.write(self.tmp / "old.jpg", dt="1980:01:01 00:00:00")
        scan.scan(self.cx, [self.tmp])
        pid = self.cx.execute("SELECT id FROM photos WHERE filename='old.jpg'").fetchone()["id"]
        server.save_record(self.cx, pid, {"species": "Apis mellifera"})
        self.assertIn("date-implausible", self.codes())

    def test_one_name_written_two_ways(self):
        server.save_record(self.cx, self.ids[1], {"species": "vespa  crabro"})
        self.assertIn("same-name-two-ways", self.codes())

    def test_two_names_one_letter_apart(self):
        server.save_record(self.cx, self.ids[1], {"species": "Vespa crabra"})
        self.assertIn("names-nearly-the-same", self.codes())

    def test_genuinely_different_names_are_left_alone(self):
        server.save_record(self.cx, self.ids[1], {"species": "Bombus terrestris"})
        self.assertNotIn("names-nearly-the-same", self.codes())
        self.assertNotIn("same-name-two-ways", self.codes())

    def test_a_name_that_is_not_in_the_checklist(self):
        records.import_terms(self.cx, "species", ["Vespa crabro", "Bombus terrestris"])
        server.save_record(self.cx, self.ids[1], {"species": "Vespa velutina"})
        self.assertIn("not-in-checklist", self.codes())

    def test_no_checklist_means_no_complaint(self):
        server.save_record(self.cx, self.ids[1], {"species": "Anything at all"})
        self.assertNotIn("not-in-checklist", self.codes())

    def test_a_value_that_breaks_its_own_rule(self):
        P.set_active(self.cx, "moths", force=True)
        prof = P.active(self.cx)
        records.save(self.cx, prof, self.ids[1], {"taxon": "Noctua pronuba", "count": "a few"})
        self.assertIn("invalid-value", {f["code"] for f in check.run(self.cx, prof)})

    def test_a_required_field_left_empty(self):
        prof = P.load("insects")
        for f in prof["fields"]:
            if f["name"] == "stage":
                f["required"] = True
        P.set_active(self.cx, prof)
        server.save_record(self.cx, self.ids[1], {"species": "Bombus terrestris"})
        self.assertIn("required-empty", {f["code"] for f in check.run(self.cx, prof)})

    def test_two_species_inside_one_burst_is_a_note_not_an_error(self):
        server.save_record(self.cx, self.ids[1], {"species": "Bombus terrestris"})
        found = [f for f in check.run(self.cx, P.active(self.cx))
                 if f["code"] == "event-has-two-names"]
        self.assertTrue(found)
        self.assertEqual(found[0]["level"], check.NOTE)

    def test_a_flagged_photograph_is_not_forgotten(self):
        server.save_record(self.cx, self.ids[1], {"_flag": "1"})
        self.assertIn("still-flagged", self.codes())

    def test_errors_come_before_warnings_and_notes(self):
        fixtures.write(self.tmp / "nogps.jpg", gps=False)
        scan.scan(self.cx, [self.tmp])
        pid = self.cx.execute("SELECT id FROM photos WHERE filename='nogps.jpg'").fetchone()["id"]
        server.save_record(self.cx, pid, {"species": "vespa crabro"})
        levels = [f["level"] for f in check.run(self.cx, P.active(self.cx))]
        self.assertEqual(levels, sorted(levels, key=lambda l: {"error": 0, "warning": 1,
                                                               "note": 2}[l]))

    def test_the_report_reads_as_sentences(self):
        text = check.report(check.run(self.cx, P.active(self.cx)))
        self.assertIn("photographs have no species yet", text)
        self.assertIn("note", text)

    def test_nothing_at_all_to_report(self):
        self.assertEqual(check.report([]),
                         "nothing to report. Every record has a name, a date and a position.")


class WritingExif(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def test_what_is_written_is_what_is_read_back(self):
        jpeg = exifwrite.with_exif(fixtures.jpeg(), dt="2026:07:04 21:15:00",
                                   lat=52.6576, lon=1.7179, lon_ref="E",
                                   width=400, height=300)
        p = self.tmp / "w.jpg"
        p.write_bytes(jpeg)
        ex = exifread.read(p)
        self.assertEqual(ex["datetime_original"], "2026-07-04T21:15:00")
        self.assertAlmostEqual(ex["lat"], 52.6576, places=4)
        self.assertAlmostEqual(ex["lon"], 1.7179, places=4)
        self.assertEqual(ex["width"], 400)

    def test_an_existing_exif_block_is_replaced_not_doubled(self):
        once = exifwrite.with_exif(fixtures.jpeg(), dt="2026:07:04 21:15:00")
        twice = exifwrite.with_exif(once, dt="2026:08:01 06:00:00")
        self.assertEqual(twice.count(b"Exif\x00\x00"), 1)
        p = self.tmp / "t.jpg"
        p.write_bytes(twice)
        self.assertEqual(exifread.read(p)["datetime_original"], "2026-08-01T06:00:00")

    def test_southern_and_eastern_positions_come_back_signed_correctly(self):
        p = self.tmp / "s.jpg"
        p.write_bytes(exifwrite.with_exif(fixtures.jpeg(), lat=-33.8688, lon=151.2093,
                                          lat_ref="S", lon_ref="E"))
        ex = exifread.read(p)
        self.assertLess(ex["lat"], 0)
        self.assertGreater(ex["lon"], 0)


class Demo(unittest.TestCase):
    def test_the_demo_folder_scans_into_real_records(self):
        tmp = Path(tempfile.mkdtemp()) / "demo"
        made = demo.build(tmp, events=5)
        self.assertTrue(len(made["photos"]) >= 6)
        cx = db.connect(tmp / "entolog.db")
        self.addCleanup(cx.close)
        result = scan.scan(cx, [tmp])
        self.assertEqual(result["added"], len(made["photos"]))
        self.assertEqual(result["groups"], 6)          # five walked stops, plus the odd one
        row = cx.execute("SELECT gridref, lat FROM photos WHERE lat IS NOT NULL "
                         "LIMIT 1").fetchone()
        self.assertTrue(row["gridref"].startswith("SP"))

    def test_the_demo_is_the_same_every_time(self):
        a = Path(tempfile.mkdtemp()) / "a"
        b = Path(tempfile.mkdtemp()) / "b"
        demo.build(a, events=3)
        demo.build(b, events=3)
        self.assertEqual([p.name for p in sorted(a.iterdir())],
                         [p.name for p in sorted(b.iterdir())])
        self.assertEqual((a / "IMG_0001.jpg").read_bytes(),
                         (b / "IMG_0001.jpg").read_bytes())

    def test_one_photograph_has_no_exif_at_all_because_a_real_card_has_one(self):
        tmp = Path(tempfile.mkdtemp()) / "demo"
        demo.build(tmp, events=3)
        cx = db.connect(tmp / "entolog.db")
        self.addCleanup(cx.close)
        scan.scan(cx, [tmp])
        odd = cx.execute("SELECT taken_source, lat FROM photos "
                         "WHERE filename='IMG_9999.jpg'").fetchone()
        self.assertEqual(odd["taken_source"], "file-mtime")
        self.assertIsNone(odd["lat"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
