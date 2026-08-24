"""The things that go wrong between a camera and a recording scheme: the wrong
grid, a position that should not be published exactly, a name with no identifier,
a clock that was never set, and a keystroke that needs taking back."""

import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import fixtures
from entolog import (check, clock, db, exifwrite, export, locality, records, scan,
                     server, taxonomy, tsvedit)
from entolog import profile as P

TAXA = """Recommended name,Authority,Rank,Recommended Taxon Version Key,Common name,Accepted name
Vespa crabro,Linnaeus 1758,Species,NBNSYS0000008320,hornet,
Aglais io,(Linnaeus 1758),Species,NHMSYS0000502212,peacock,
Inachis io,(Linnaeus 1758),Species,NBNSYS0000005182,,Aglais io
Bombus terrestris,(Linnaeus 1758),Species,NBNSYS0000008474,buff-tailed bumblebee,
"""


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.cx = db.connect(self.tmp / "t.db")
        self.addCleanup(self.cx.close)
        for i in range(3):
            fixtures.write(self.tmp / f"p{i}.jpg", dt=f"2026:06:14 09:3{i}:00")
        scan.scan(self.cx, [self.tmp])
        self.prof = P.active(self.cx)
        self.ids = [r["id"] for r in self.cx.execute("SELECT id FROM photos ORDER BY seq")]


class Grids(unittest.TestCase):
    def test_the_ordnance_survey_test_point_is_still_exact(self):
        lat = 52 + 39 / 60 + 28.723 / 3600
        lon = 1 + 42 / 60 + 57.787 / 3600
        self.assertEqual(locality.gridref(lat, lon, 10), ("TG5140913177", "osgb"))

    def test_ireland_gets_the_irish_grid(self):
        for name, lat, lon, square in (("Dublin", 53.3498, -6.2603, "O"),
                                       ("Galway", 53.2707, -9.0568, "M"),
                                       ("Cork", 51.8985, -8.4756, "W"),
                                       ("Belfast", 54.5973, -5.9301, "J")):
            ref, system = locality.gridref(lat, lon)
            self.assertEqual(system, "irish", name)
            self.assertTrue(ref.startswith(square), f"{name}: {ref}")

    def test_scotland_keeps_the_british_grid_even_out_west(self):
        ref, system = locality.gridref(55.30, -5.70)          # Kintyre
        self.assertEqual(system, "osgb")
        self.assertTrue(ref.startswith("NR"), ref)

    def test_nowhere_near_either_grid_is_empty_rather_than_wrong(self):
        self.assertEqual(locality.gridref(-33.9, 151.2), ("", ""))
        self.assertEqual(locality.gridref(None, None), ("", ""))

    def test_the_system_can_be_forced_and_forcing_means_forcing(self):
        auto, system = locality.gridref(53.3498, -6.2603)
        self.assertEqual(system, "irish")
        forced, system = locality.gridref(53.3498, -6.2603, system="osgb")
        self.assertEqual(system, "osgb")
        self.assertNotEqual(forced, auto)


class Blurring(unittest.TestCase):
    lat, lon = 51.771500, -1.335500

    def test_each_square_is_a_shorter_reference(self):
        ref = locality.gridref(self.lat, self.lon, 10)[0]
        self.assertEqual(locality.blur(ref, "100m"), "SP459083")
        self.assertEqual(locality.blur(ref, "1km"), "SP4508")
        self.assertEqual(locality.blur(ref, "10km"), "SP40")
        self.assertEqual(locality.blur(ref, "100km"), "SP")

    def test_a_two_kilometre_square_is_written_as_a_tetrad(self):
        ref = locality.gridref(self.lat, self.lon, 10)[0]
        self.assertEqual(locality.blur(ref, "2km"), "SP40P")

    def test_an_unknown_precision_leaves_the_reference_alone(self):
        self.assertEqual(locality.blur("SP4594", "5km"), "SP4594")
        self.assertEqual(locality.blur("", "1km"), "")

    def test_the_position_given_is_the_middle_of_the_square_named(self):
        lat2, lon2, ref, uncertainty = locality.blur_position(self.lat, self.lon, "1km")
        self.assertEqual(ref, "SP4508")
        self.assertEqual(uncertainty, 707)
        # the centre must fall in the same square it names
        self.assertEqual(locality.blur(locality.gridref(lat2, lon2, 10)[0], "1km"), ref)

    def test_a_coarser_square_says_it_is_less_certain(self):
        self.assertEqual(locality.blur_position(self.lat, self.lon, "10km")[3], 7071)

    def test_it_works_on_the_irish_grid_too(self):
        lat2, lon2, ref, _u = locality.blur_position(53.3498, -6.2603, "1km")
        self.assertTrue(ref.startswith("O"), ref)
        self.assertEqual(locality.blur(locality.gridref(lat2, lon2, 10)[0], "1km"), ref)

    def test_no_precision_means_no_change(self):
        self.assertEqual(locality.blur_position(self.lat, self.lon, "")[:2],
                         (self.lat, self.lon))


class Sensitive(Base):
    def setUp(self):
        super().setUp()
        server.save_record(self.cx, self.ids[0], {"species": "Vespa crabro"})

    def row(self, filename="p0.jpg"):
        import csv
        import io
        text = export.render(self.cx, "full")
        for d in csv.DictReader(io.StringIO(text)):
            if d["filename"] == filename:
                return d
        return {}

    def test_a_record_is_exact_until_it_is_told_otherwise(self):
        self.assertEqual(self.row()["precision"], "exact")
        self.assertEqual(self.row()["gridref"], locality.gridref(51.752, -1.2577)[0][:2]
                         + self.row()["gridref"][2:])

    def test_marking_one_record_publishes_it_as_a_square(self):
        records.save(self.cx, self.prof, self.ids[0], {records.PRECISION: "1km"})
        d = self.row()
        self.assertEqual(d["precision"], "1km")
        self.assertEqual(len(d["gridref"].replace("SP", "")), 4)
        self.assertEqual(d["coord_uncertainty_m"], "707")
        self.assertNotEqual(d["latitude"], "51.7537917")

    def test_the_whole_dataset_can_be_coarsened_at_once(self):
        db.set_meta(self.cx, "blur", "10km")
        self.assertEqual(self.row()["precision"], "10km")

    def test_a_record_of_its_own_beats_the_dataset_default(self):
        db.set_meta(self.cx, "blur", "10km")
        records.save(self.cx, self.prof, self.ids[0], {records.PRECISION: "100m"})
        self.assertEqual(self.row()["precision"], "100m")

    def test_an_impossible_precision_is_refused(self):
        _ids, errors = records.save(self.cx, self.prof, self.ids[0],
                                    {records.PRECISION: "3km"})
        self.assertIn(records.PRECISION, errors)

    def test_darwin_core_says_what_was_withheld(self):
        records.save(self.cx, self.prof, self.ids[0], {records.PRECISION: "1km"})
        text = export.render(self.cx, "dwc")
        self.assertIn("informationWithheld", text.splitlines()[0])
        self.assertIn("1km square", text)

    def test_irecord_is_told_the_precision_in_metres(self):
        records.save(self.cx, self.prof, self.ids[0], {records.PRECISION: "1km"})
        head, row = export.render(self.cx, "irecord").splitlines()[:2]
        self.assertEqual(row.split(",")[head.split(",").index("Sensitivity precision")],
                         "1000")


class Taxonomy(Base):
    def setUp(self):
        super().setUp()
        self.result = taxonomy.load(self.cx, TAXA)

    def test_the_columns_are_recognised_by_their_headings(self):
        self.assertEqual(self.result["names"], 4)
        self.assertEqual(self.result["columns"]["taxon_id"],
                         "Recommended Taxon Version Key")
        self.assertEqual(self.result["synonyms"], 1)

    def test_other_column_names_are_understood_too(self):
        cx = db.connect(self.tmp / "b.db")
        self.addCleanup(cx.close)
        out = taxonomy.load(cx, "scientificName\ttaxonID\tvernacularName\n"
                                "Apis mellifera\t123\thoney bee\n")
        self.assertEqual(out["names"], 1)
        self.assertEqual(taxonomy.lookup(cx, "Apis mellifera")["taxon_id"], "123")

    def test_a_column_can_be_pointed_at_by_hand(self):
        cx = db.connect(self.tmp / "c.db")
        self.addCleanup(cx.close)
        out = taxonomy.load(cx, "Thing,Code\nApis mellifera,999\n",
                            override="name=Thing,taxon_id=Code")
        self.assertEqual(out["names"], 1)
        self.assertEqual(taxonomy.lookup(cx, "apis mellifera")["taxon_id"], "999")

    def test_a_file_with_no_name_column_says_so_rather_than_loading_rubbish(self):
        cx = db.connect(self.tmp / "d.db")
        self.addCleanup(cx.close)
        out = taxonomy.load(cx, "a,b\n1,2\n")
        self.assertIn("scientific name", out["problem"])
        self.assertEqual(taxonomy.count(cx), 0)

    def test_a_name_is_found_whatever_the_case(self):
        self.assertEqual(taxonomy.lookup(self.cx, "VESPA CRABRO")["taxon_id"],
                         "NBNSYS0000008320")

    def test_a_synonym_knows_what_it_is_a_synonym_of(self):
        accepted, entry = taxonomy.accepted_for(self.cx, "Inachis io")
        self.assertEqual(accepted, "Aglais io")
        self.assertEqual(entry["taxon_id"], "NHMSYS0000502212")

    def test_the_list_is_offered_while_typing(self):
        hits = records.suggest(self.cx, "species", "vesp", taxa=True)
        self.assertEqual(hits[0]["value"], "Vespa crabro")
        self.assertIn("hornet", hits[0]["note"])

    def test_a_synonym_is_offered_but_says_what_it_really_is(self):
        hits = records.suggest(self.cx, "species", "inach", taxa=True)
        self.assertIn("synonym of Aglais io", hits[0]["note"])

    def test_only_the_field_that_holds_names_gets_the_taxon_list(self):
        self.assertEqual(records.suggest(self.cx, "comments", "vesp", taxa=False), [])

    def test_the_identifier_travels_into_darwin_core(self):
        server.save_record(self.cx, self.ids[0], {"species": "Vespa crabro"})
        text = export.render(self.cx, "dwc")
        head, row = text.splitlines()[0].split(","), text.splitlines()[1].split(",")
        got = dict(zip(head, row))
        self.assertEqual(got["taxonID"], "NBNSYS0000008320")
        self.assertEqual(got["scientificNameAuthorship"], "Linnaeus 1758")
        self.assertEqual(got["taxonRank"], "Species")

    def test_a_synonym_exports_with_the_accepted_name_beside_it(self):
        server.save_record(self.cx, self.ids[0], {"species": "Inachis io"})
        got = dict(zip(*[l.split(",") for l in export.render(self.cx, "dwc").splitlines()[:2]]))
        self.assertEqual(got["scientificName"], "Inachis io")
        self.assertEqual(got["acceptedNameUsage"], "Aglais io")

    def test_irecord_gets_the_taxon_version_key(self):
        server.save_record(self.cx, self.ids[0], {"species": "Vespa crabro"})
        head, row = export.render(self.cx, "irecord").splitlines()[:2]
        self.assertEqual(row.split(",")[head.split(",").index("Taxon Version Key")],
                         "NBNSYS0000008320")

    def test_no_taxon_list_means_no_empty_taxon_columns(self):
        cx = db.connect(self.tmp / "e.db")
        self.addCleanup(cx.close)
        fixtures.write(self.tmp / "solo.jpg")
        scan.scan(cx, [self.tmp])
        pid = cx.execute("SELECT id FROM photos LIMIT 1").fetchone()["id"]
        server.save_record(cx, pid, {"species": "Vespa crabro"})
        self.assertNotIn("taxonID", export.render(cx, "dwc").splitlines()[0])

    def test_check_reports_a_name_the_list_does_not_have(self):
        server.save_record(self.cx, self.ids[0], {"species": "Vespa velutina"})
        codes = {f["code"] for f in check.run(self.cx, self.prof)}
        self.assertIn("not-in-taxon-list", codes)

    def test_check_reports_a_record_filed_under_a_synonym(self):
        server.save_record(self.cx, self.ids[0], {"species": "Inachis io"})
        found = [f for f in check.run(self.cx, self.prof)
                 if f["code"] == "recorded-under-a-synonym"]
        self.assertTrue(found)
        self.assertIn("Aglais io", found[0]["message"])

    def test_a_taxon_list_replaces_the_plain_checklist_for_names(self):
        records.import_terms(self.cx, "species", ["Vespa crabro"])
        server.save_record(self.cx, self.ids[0], {"species": "Vespa velutina"})
        codes = {f["code"] for f in check.run(self.cx, self.prof)}
        self.assertIn("not-in-taxon-list", codes)
        self.assertNotIn("not-in-checklist", codes)   # one complaint, not two

    def test_clearing_the_list_leaves_the_records_alone(self):
        server.save_record(self.cx, self.ids[0], {"species": "Vespa crabro"})
        self.cx.execute("DELETE FROM taxa")
        self.cx.commit()
        self.assertEqual(records.values(self.cx, self.ids[0])["species"], "Vespa crabro")


class Clock(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.cx = db.connect(self.tmp / "t.db")
        self.addCleanup(self.cx.close)

    def shoot(self, name, when, gps_utc=None):
        (self.tmp / name).write_bytes(exifwrite.with_exif(
            fixtures.jpeg(), dt=when.strftime("%Y:%m:%d %H:%M:%S"),
            lat=51.7715, lon=-1.3355, gps_utc=gps_utc))

    def test_reading_a_shift(self):
        self.assertEqual(clock.parse_shift("+3h12m"), 3 * 3600 + 12 * 60)
        self.assertEqual(clock.parse_shift("-45m"), -45 * 60)
        self.assertEqual(clock.parse_shift("2h"), 7200)
        self.assertEqual(clock.parse_shift("90"), 90)
        for bad in ("", "soon", "3 weeks"):
            with self.assertRaises(ValueError):
                clock.parse_shift(bad)

    def test_writing_a_shift_back_out(self):
        self.assertEqual(clock.describe(3 * 3600 + 12 * 60), "+3h12m")
        self.assertEqual(clock.describe(-90), "-1m30s")
        self.assertEqual(clock.describe(0), "+0s")

    def test_the_satellite_clock_measures_the_camera(self):
        base = datetime(2026, 6, 14, 10, 0, 0)
        for i in range(4):
            when = base + timedelta(minutes=i)
            self.shoot(f"g{i}.jpg", when, gps_utc=when - timedelta(hours=1, minutes=47))
        scan.scan(self.cx, [self.tmp])
        m = clock.against_gps(self.cx)
        self.assertEqual(m["photos"], 4)
        self.assertEqual(m["median"], (3600 + 47 * 60))
        self.assertEqual(m["zones"], [3600, 7200])       # both readings offered

    def test_no_satellite_time_means_nothing_to_measure(self):
        self.shoot("plain.jpg", datetime(2026, 6, 14, 10, 0, 0))
        scan.scan(self.cx, [self.tmp])
        self.assertEqual(clock.against_gps(self.cx)["photos"], 0)

    def test_a_shift_moves_every_date_and_says_it_did(self):
        self.shoot("a.jpg", datetime(2026, 6, 14, 10, 0, 0))
        scan.scan(self.cx, [self.tmp])
        clock.shift(self.cx, -47 * 60)
        row = self.cx.execute("SELECT taken_at, taken_source FROM photos").fetchone()
        self.assertTrue(row["taken_at"].startswith("2026-06-14T09:13"))
        self.assertIn("corrected", row["taken_source"])

    def test_shifting_back_puts_the_dates_where_they_were(self):
        self.shoot("a.jpg", datetime(2026, 6, 14, 10, 0, 0))
        scan.scan(self.cx, [self.tmp])
        before = self.cx.execute("SELECT taken_at FROM photos").fetchone()["taken_at"]
        clock.shift(self.cx, 3600)
        clock.shift(self.cx, -3600)
        self.assertEqual(self.cx.execute("SELECT taken_at FROM photos")
                         .fetchone()["taken_at"], before)

    def test_a_photograph_dated_from_the_file_is_left_out_unless_asked_for(self):
        (self.tmp / "bare.jpg").write_bytes(b"\xff\xd8\xff\xd9")
        scan.scan(self.cx, [self.tmp])
        self.assertEqual(clock.shift(self.cx, 3600)["photos"], 0)
        self.assertEqual(clock.shift(self.cx, 3600, only_exif=False)["photos"], 1)

    def test_correcting_the_clock_regroups_the_specimen_events(self):
        base = datetime(2026, 6, 14, 10, 0, 0)
        self.shoot("a.jpg", base)
        self.shoot("b.jpg", base + timedelta(minutes=40))
        scan.scan(self.cx, [self.tmp])
        self.assertEqual(clock.shift(self.cx, 60)["groups"], 2)

    def test_one_known_photograph_gives_the_offset(self):
        self.shoot("a.jpg", datetime(2026, 6, 14, 10, 0, 0))
        scan.scan(self.cx, [self.tmp])
        photo = self.cx.execute("SELECT * FROM photos").fetchone()
        self.assertEqual(clock.offset_to(self.cx, photo, "2026-06-14 09:13"), -47 * 60)
        with self.assertRaises(ValueError):
            clock.offset_to(self.cx, photo, "sometime tuesday")

    def test_what_was_applied_is_remembered(self):
        self.shoot("a.jpg", datetime(2026, 6, 14, 10, 0, 0))
        scan.scan(self.cx, [self.tmp])
        clock.shift(self.cx, -60)
        self.assertEqual(clock.json_history(self.cx)[-1]["seconds"], -60)


class Undo(Base):
    def test_one_keystroke_is_one_step_back(self):
        server.save_record(self.cx, self.ids[0],
                           {"species": "Vespa crabro", "stage": "adult"},
                           apply_group=True)
        self.assertEqual(records.counts(self.cx, self.prof)["done"], 3)
        done = records.undo(self.cx)
        self.assertEqual(done[0]["photos"], 3)
        self.assertEqual(records.counts(self.cx, self.prof)["done"], 0)

    def test_it_goes_back_one_change_at_a_time(self):
        server.save_record(self.cx, self.ids[0], {"species": "Vespa crabro"})
        server.save_record(self.cx, self.ids[0], {"species": "Vespula vulgaris"})
        records.undo(self.cx)
        self.assertEqual(records.values(self.cx, self.ids[0])["species"], "Vespa crabro")
        records.undo(self.cx)
        self.assertEqual(records.values(self.cx, self.ids[0])["species"], "")

    def test_several_steps_at_once(self):
        for name in ("a", "b", "c"):
            server.save_record(self.cx, self.ids[0], {"species": name})
        self.assertEqual(len(records.undo(self.cx, 3)), 3)
        self.assertEqual(records.values(self.cx, self.ids[0]).get("species", ""), "")

    def test_nothing_to_undo_is_not_an_error(self):
        self.assertEqual(records.undo(self.cx), [])
        self.assertIsNone(records.pending_undo(self.cx))

    def test_it_says_what_it_would_put_back_before_doing_it(self):
        server.save_record(self.cx, self.ids[0], {"species": "Vespa crabro"})
        pending = records.pending_undo(self.cx)
        self.assertEqual(pending["photos"], 1)
        self.assertIn("Vespa crabro", pending["what"])
        self.assertEqual(records.values(self.cx, self.ids[0])["species"], "Vespa crabro")

    def test_a_whole_edited_table_is_one_step_back(self):
        text = tsvedit.dump(self.cx, self.prof)
        edited = text.replace("\tp0.jpg", "\tp0.jpg").splitlines()
        head = [l for l in edited if l.startswith("id")][0].split("\t")
        rows = ["\t".join([str(pid), "Vespa crabro"]) for pid in self.ids]
        tsvedit.apply(self.cx, self.prof, "id\tspecies\n" + "\n".join(rows))
        self.assertEqual(records.counts(self.cx, self.prof)["done"], 3)
        records.undo(self.cx)
        self.assertEqual(records.counts(self.cx, self.prof)["done"], 0)

    def test_a_value_that_did_not_change_is_not_a_step(self):
        server.save_record(self.cx, self.ids[0], {"species": "Vespa crabro"})
        server.save_record(self.cx, self.ids[0], {"species": "Vespa crabro"})
        records.undo(self.cx)
        self.assertEqual(records.values(self.cx, self.ids[0]).get("species", ""), "")

    def test_flagging_can_be_taken_back_too(self):
        server.save_record(self.cx, self.ids[0], {records.FLAG: "1"})
        records.undo(self.cx)
        self.assertEqual(len(records.list_photos(self.cx, self.prof, "flagged")), 0)


class Backup(Base):
    def test_a_copy_holds_the_same_records(self):
        server.save_record(self.cx, self.ids[0], {"species": "Vespa crabro"})
        out = self.tmp / "copy.db"
        with db.connect(out) as copy:
            self.cx.backup(copy)
        again = db.connect(out)
        self.addCleanup(again.close)
        self.assertIn("Vespa crabro", export.render(again, "csv"))


if __name__ == "__main__":
    unittest.main(verbosity=2)


class SeveralOnOnePhotograph(Base):
    """A light trap egg box holds ten moths, and a leaf can hold two mines."""

    def test_the_first_record_is_the_only_one_until_another_is_asked_for(self):
        server.save_record(self.cx, self.ids[0], {"species": "Vespa crabro"})
        self.assertEqual(records.occurrences(self.cx, self.ids[0]), [1])

    def test_asking_for_another_writes_nothing_until_something_is_typed(self):
        occ = records.add_record(self.cx, self.ids[0], self.prof)
        self.assertEqual(occ, 2)
        self.assertEqual(records.occurrences(self.cx, self.ids[0]), [1])
        records.save(self.cx, self.prof, self.ids[0], {"species": "Aglais io"}, occ=occ)
        self.assertEqual(records.occurrences(self.cx, self.ids[0]), [1, 2])

    def test_the_second_record_leaves_the_first_alone(self):
        server.save_record(self.cx, self.ids[0], {"species": "Vespa crabro",
                                                  "stage": "adult"})
        records.save(self.cx, self.prof, self.ids[0], {"species": "Aglais io"}, occ=2)
        self.assertEqual(records.values(self.cx, self.ids[0], 1)["species"],
                         "Vespa crabro")
        self.assertEqual(records.values(self.cx, self.ids[0], 2)["species"], "Aglais io")
        self.assertEqual(records.values(self.cx, self.ids[0], 2).get("stage", ""), "")

    def test_a_photograph_recorded_only_on_its_second_record_still_counts_as_done(self):
        records.save(self.cx, self.prof, self.ids[0], {"species": "Aglais io"}, occ=2)
        self.assertEqual(records.counts(self.cx, self.prof)["done"], 1)
        self.assertEqual(len(records.list_photos(self.cx, self.prof, "done")), 1)
        self.assertEqual(len(records.list_photos(self.cx, self.prof, "todo")), 2)

    def test_the_counts_separate_photographs_from_records(self):
        server.save_record(self.cx, self.ids[0], {"species": "Vespa crabro"})
        records.save(self.cx, self.prof, self.ids[0], {"species": "Aglais io"}, occ=2)
        got = records.counts(self.cx, self.prof)
        self.assertEqual((got["done"], got["records"]), (1, 2))

    def test_a_listed_photograph_carries_every_record_it_holds(self):
        server.save_record(self.cx, self.ids[0], {"species": "Vespa crabro"})
        records.save(self.cx, self.prof, self.ids[0], {"species": "Aglais io"}, occ=2)
        row = records.list_photos(self.cx, self.prof, "all")[0]
        self.assertEqual(row["occs"], 2)
        self.assertEqual([o for o, _v, _f, _p in records.each_record(row)], [1, 2])
        self.assertEqual([v.get("species") for _o, v, _f, _p in records.each_record(row)],
                         ["Vespa crabro", "Aglais io"])

    def test_taking_one_off_again(self):
        server.save_record(self.cx, self.ids[0], {"species": "Vespa crabro"})
        records.save(self.cx, self.prof, self.ids[0], {"species": "Aglais io"}, occ=2)
        self.assertTrue(records.remove_record(self.cx, self.ids[0], 2))
        self.assertEqual(records.occurrences(self.cx, self.ids[0]), [1])
        self.assertEqual(records.values(self.cx, self.ids[0], 1)["species"],
                         "Vespa crabro")

    def test_the_first_record_is_emptied_rather_than_removed(self):
        server.save_record(self.cx, self.ids[0], {"species": "Vespa crabro"})
        self.assertFalse(records.remove_record(self.cx, self.ids[0], 1))
        self.assertEqual(records.values(self.cx, self.ids[0], 1), {})

    def test_each_record_exports_as_its_own_occurrence(self):
        server.save_record(self.cx, self.ids[0], {"species": "Vespa crabro"})
        records.save(self.cx, self.prof, self.ids[0], {"species": "Aglais io"}, occ=2)
        rows = export.render(self.cx, "csv").strip().splitlines()
        self.assertEqual(len(rows), 3)                      # header and two records
        self.assertIn("Vespa crabro", rows[1])
        self.assertIn("Aglais io", rows[2])

    def test_the_first_record_keeps_the_identifier_it_always_had(self):
        server.save_record(self.cx, self.ids[0], {"species": "Vespa crabro"})
        first = export.render(self.cx, "dwc").splitlines()[1].split(",")[0]
        records.save(self.cx, self.prof, self.ids[0], {"species": "Aglais io"}, occ=2)
        after = export.render(self.cx, "dwc").splitlines()[1].split(",")[0]
        second = export.render(self.cx, "dwc").splitlines()[2].split(",")[0]
        self.assertEqual(first, after)
        self.assertEqual(second, first + ":2")

    def test_an_empty_second_record_is_not_exported(self):
        server.save_record(self.cx, self.ids[0], {"species": "Vespa crabro"})
        records.save(self.cx, self.prof, self.ids[0], {"stage": "adult"}, occ=2)
        self.assertEqual(len(export.render(self.cx, "csv").strip().splitlines()), 2)

    def test_the_table_grows_a_record_column_only_when_it_needs_one(self):
        server.save_record(self.cx, self.ids[0], {"species": "Vespa crabro"})
        self.assertNotIn("\trecord\t", tsvedit.dump(self.cx, self.prof))
        records.save(self.cx, self.prof, self.ids[0], {"species": "Aglais io"}, occ=2)
        text = tsvedit.dump(self.cx, self.prof)
        self.assertIn("\trecord\t", text)
        self.assertEqual(len([l for l in text.splitlines()
                              if l.startswith(str(self.ids[0]) + "\t")]), 2)

    def test_an_edited_table_goes_back_to_the_right_record(self):
        server.save_record(self.cx, self.ids[0], {"species": "Vespa crabro"})
        records.save(self.cx, self.prof, self.ids[0], {"species": "Aglais io"}, occ=2)
        tsvedit.apply(self.cx, self.prof,
                      f"id\trecord\tspecies\n{self.ids[0]}\t2\tInachis io\n")
        self.assertEqual(records.values(self.cx, self.ids[0], 1)["species"],
                         "Vespa crabro")
        self.assertEqual(records.values(self.cx, self.ids[0], 2)["species"], "Inachis io")

    def test_the_cleaning_pass_sees_two_records_not_one(self):
        server.save_record(self.cx, self.ids[0], {"species": "Vespa crabro"})
        records.save(self.cx, self.prof, self.ids[0], {"species": "vespa  crabro"},
                     occ=2)
        codes = {f["code"] for f in check.run(self.cx, self.prof)}
        self.assertIn("same-name-two-ways", codes)

    def test_undo_puts_back_the_record_it_changed(self):
        server.save_record(self.cx, self.ids[0], {"species": "Vespa crabro"})
        records.save(self.cx, self.prof, self.ids[0], {"species": "Aglais io"}, occ=2)
        records.undo(self.cx)
        self.assertEqual(records.values(self.cx, self.ids[0], 1)["species"],
                         "Vespa crabro")
        self.assertEqual(records.values(self.cx, self.ids[0], 2).get("species", ""), "")

    def test_a_database_from_before_this_existed_still_opens(self):
        server.save_record(self.cx, self.ids[0], {"species": "Vespa crabro"})
        self.cx.commit()
        # rebuild the table the way 1.4 had it, then reopen
        self.cx.executescript("""
          CREATE TABLE old_shape (photo_id INTEGER NOT NULL, field TEXT NOT NULL,
            value TEXT NOT NULL DEFAULT '', updated_at TEXT,
            PRIMARY KEY (photo_id, field));
          INSERT INTO old_shape SELECT photo_id, field, value, updated_at
            FROM field_values WHERE occ=1;
          DROP TABLE field_values;
          ALTER TABLE old_shape RENAME TO field_values;
        """)
        self.cx.commit()
        self.cx.close()
        cx = db.connect(self.tmp / "t.db")
        self.addCleanup(cx.close)
        self.assertIn("occ", {r["name"] for r in cx.execute(
            "PRAGMA table_info(field_values)")})
        self.assertEqual(records.values(cx, self.ids[0], 1)["species"], "Vespa crabro")
