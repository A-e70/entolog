"""Place names and grid references. No network is used by any of this."""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import fixtures
from entolog import db, export, locality, scan

VERBOSE = ("Wytham Woods, Wytham, Vale of White Horse, Oxfordshire, England, "
           "OX2 8QQ, United Kingdom")


class Shorten(unittest.TestCase):
    def test_a_postal_hierarchy_becomes_a_site_and_a_county(self):
        self.assertEqual(locality.shorten(VERBOSE), "Wytham Woods, Oxfordshire")

    def test_one_part_if_that_is_all_you_want(self):
        self.assertEqual(locality.shorten(VERBOSE, parts=1), "Wytham Woods")

    def test_house_numbers_postcodes_and_countries_go(self):
        self.assertEqual(
            locality.shorten("12, High Street, Old Town, Swindon, England, SN1 3EQ, "
                             "United Kingdom"), "High Street, Swindon")

    def test_a_part_already_contained_in_another_is_dropped(self):
        self.assertEqual(locality.shorten("Wytham Woods, Wytham, Oxfordshire"),
                         "Wytham Woods, Oxfordshire")

    def test_structured_nominatim_json_is_understood(self):
        self.assertEqual(
            locality.shorten('{"address": {"nature_reserve": "Bookham Common", '
                             '"village": "Bookham", "county": "Surrey", '
                             '"country": "United Kingdom"}}'),
            "Bookham Common, Surrey")

    def test_a_dict_works_as_well_as_the_json(self):
        self.assertEqual(locality.shorten({"address": {"village": "Sonning",
                                                       "county": "Berkshire"}}),
                         "Sonning, Berkshire")

    def test_outside_the_uk_too(self):
        self.assertEqual(
            locality.shorten("Rue de la Paix, 2e Arrondissement, Paris, "
                             "Ile-de-France, 75002, France"),
            "Rue de la Paix, Ile-de-France")

    def test_nothing_useful_gives_nothing_rather_than_rubbish(self):
        self.assertEqual(locality.shorten("SN1 3EQ, United Kingdom"), "")
        self.assertEqual(locality.shorten(""), "")
        self.assertEqual(locality.shorten(None), "")


class GridReference(unittest.TestCase):
    def dms(self, d, m, s):
        return d + m / 60 + s / 3600

    def test_exact_against_the_ordnance_survey_test_point(self):
        # Caister water tower, ETRS89 in, OSGB36 grid out
        self.assertEqual(locality.osgb_gridref(self.dms(52, 39, 28.723),
                                               self.dms(1, 42, 57.787), digits=10),
                         "TG5140913177")

    def test_precision_follows_the_number_of_figures(self):
        lat, lon = self.dms(52, 39, 28.723), self.dms(1, 42, 57.787)
        self.assertEqual(locality.osgb_gridref(lat, lon, digits=4), "TG5113")
        self.assertEqual(locality.osgb_gridref(lat, lon, digits=6), "TG514131")
        self.assertEqual(locality.osgb_gridref(lat, lon, digits=8), "TG51401317")

    def test_scotland_and_the_south_coast_land_in_the_right_squares(self):
        self.assertTrue(locality.osgb_gridref(55.9486, -3.2008).startswith("NT"))
        self.assertTrue(locality.osgb_gridref(50.7184, -3.5339).startswith("SX"))

    def test_outside_britain_is_empty_rather_than_wrong(self):
        self.assertEqual(locality.osgb_gridref(-33.9, 151.2), "")
        self.assertEqual(locality.osgb_gridref(40.7, -74.0), "")


class Places(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.cx = db.connect(self.tmp / "t.db")
        self.addCleanup(self.cx.close)
        for i in range(3):
            fixtures.write(self.tmp / f"a{i}.jpg", dt=f"2026:06:14 09:3{i}:00")
        fixtures.write(self.tmp / "far.jpg", dt="2026:06:14 15:00:00",
                       lat=(53, 0, 0.0), lon=(2, 0, 0.0))
        scan.scan(self.cx, [self.tmp])

    def test_one_lookup_names_every_photograph_at_that_position(self):
        row = self.cx.execute("SELECT lat, lon FROM photos LIMIT 1").fetchone()
        locality.store(self.cx, row["lat"], row["lon"], VERBOSE)
        self.assertEqual(locality.apply_to_photos(self.cx), 3)
        named = self.cx.execute("SELECT COUNT(*) c FROM photos "
                                "WHERE locality='Wytham Woods, Oxfordshire'").fetchone()["c"]
        self.assertEqual(named, 3)

    def test_positions_still_needing_a_name_are_grouped_not_listed_one_by_one(self):
        todo = locality.pending(self.cx)
        self.assertEqual(len(todo), 2)
        self.assertEqual(sorted(t["n"] for t in todo), [1, 3])

    def test_re_shortening_changes_every_photograph_at_once(self):
        row = self.cx.execute("SELECT lat, lon FROM photos LIMIT 1").fetchone()
        locality.store(self.cx, row["lat"], row["lon"], VERBOSE)
        locality.apply_to_photos(self.cx)
        locality.reshorten(self.cx, parts=1)
        self.assertEqual(self.cx.execute("SELECT locality FROM photos LIMIT 1")
                         .fetchone()["locality"], "Wytham Woods")

    def test_the_verbose_original_is_kept(self):
        row = self.cx.execute("SELECT lat, lon FROM photos LIMIT 1").fetchone()
        locality.store(self.cx, row["lat"], row["lon"], VERBOSE)
        locality.apply_to_photos(self.cx)
        full = self.cx.execute("SELECT locality_full FROM photos LIMIT 1").fetchone()
        self.assertEqual(full["locality_full"], VERBOSE)

    def test_locality_and_grid_reference_reach_the_export(self):
        row = self.cx.execute("SELECT lat, lon FROM photos LIMIT 1").fetchone()
        locality.store(self.cx, row["lat"], row["lon"], VERBOSE)
        locality.apply_to_photos(self.cx)
        from entolog import server
        pid = self.cx.execute("SELECT id FROM photos ORDER BY seq").fetchone()["id"]
        server.save_record(self.cx, pid, {"species": "Vespa crabro"})
        text = export.render(self.cx, "full")
        self.assertIn("Wytham Woods, Oxfordshire", text)
        self.assertIn("SP", text)

    def test_a_photograph_with_no_position_gets_no_grid_reference(self):
        fixtures.write(self.tmp / "nogps.jpg", gps=False)
        scan.scan(self.cx, [self.tmp])
        row = self.cx.execute("SELECT gridref FROM photos WHERE filename='nogps.jpg'").fetchone()
        self.assertIsNone(row["gridref"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
