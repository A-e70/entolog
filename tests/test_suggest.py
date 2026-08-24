"""What gets offered while a name is half typed.

Two rules run through all of it. The list is derived from the records themselves,
so it needs no upkeep, and nothing a recorder typed is ever replaced unless
exactly one thing could have been meant.
"""

import json
import sys
import tempfile
import unittest
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import fixtures
from entolog import db, entry, records, scan, server
from entolog import profile as P

CHECKLIST = ["Vespa crabro\thornet", "Vespula vulgaris\tcommon wasp",
             "Bombus terrestris\tbuff-tailed bumblebee",
             "Bombus lapidarius\tred-tailed bumblebee",
             "Volucella zonaria\thornet mimic hoverfly"]


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.cx = db.connect(self.tmp / "t.db")
        self.addCleanup(self.cx.close)
        for i in range(6):
            fixtures.write(self.tmp / f"p{i}.jpg", dt=f"2026:06:14 0{i + 1}:00:00")
        scan.scan(self.cx, [self.tmp])
        self.prof = P.active(self.cx)
        self.ids = [r["id"] for r in self.cx.execute("SELECT id FROM photos ORDER BY seq")]

    def values(self, q="", field="species", limit=20):
        return [h["value"] for h in records.suggest(self.cx, field, q, limit)]


class FromTheRecords(Base):
    def test_a_species_is_offered_as_soon_as_it_has_been_recorded_once(self):
        self.assertEqual(self.values("and"), [])
        server.save_record(self.cx, self.ids[0], {"species": "Andrena fulva"})
        self.assertEqual(self.values("and"), ["Andrena fulva"])

    def test_the_count_is_how_many_records_actually_hold_it(self):
        for pid in self.ids[:3]:
            server.save_record(self.cx, pid, {"species": "Andrena fulva"})
        self.assertEqual(records.known_values(self.cx, "species")["Andrena fulva"]["n"], 3)

    def test_changing_a_record_changes_what_is_offered(self):
        server.save_record(self.cx, self.ids[0], {"species": "Andrena fulva"})
        server.save_record(self.cx, self.ids[0], {"species": "Andrena cineraria"})
        known = records.known_values(self.cx, "species")
        self.assertEqual(known["Andrena cineraria"]["n"], 1)
        self.assertEqual(known["Andrena fulva"]["n"], 0)

    def test_a_checklist_entry_is_offered_before_it_is_ever_used(self):
        records.import_terms(self.cx, "species", CHECKLIST)
        self.assertIn("Vespa crabro", self.values("vesp"))
        self.assertTrue(records.known_values(self.cx, "species")["Vespa crabro"]["listed"])

    def test_what_has_been_recorded_here_comes_before_what_has_not(self):
        records.import_terms(self.cx, "species", CHECKLIST)
        server.save_record(self.cx, self.ids[0], {"species": "Bombus lapidarius"})
        self.assertEqual(self.values("bomb")[0], "Bombus lapidarius")

    def test_more_recorded_comes_before_less_recorded(self):
        for pid in self.ids[:4]:
            server.save_record(self.cx, pid, {"species": "Bombus terrestris"})
        server.save_record(self.cx, self.ids[4], {"species": "Bombus lapidarius"})
        self.assertEqual(self.values("bomb"), ["Bombus terrestris", "Bombus lapidarius"])

    def test_an_empty_box_offers_the_most_recorded_first(self):
        records.import_terms(self.cx, "species", CHECKLIST)
        for pid in self.ids[:2]:
            server.save_record(self.cx, pid, {"species": "Volucella zonaria"})
        self.assertEqual(self.values("")[0], "Volucella zonaria")

    def test_it_works_for_any_field_that_learns(self):
        server.save_record(self.cx, self.ids[0], {"comments": "on ivy"})
        records.import_terms(self.cx, "host_plant", ["Hedera helix\tivy"])
        self.assertEqual(self.values("hed", field="host_plant"), ["Hedera helix"])

    def test_it_works_under_another_profile(self):
        P.set_active(self.cx, "moths", force=True)
        prof = P.active(self.cx)
        records.save(self.cx, prof, self.ids[0], {"taxon": "Noctua pronuba"})
        self.assertEqual(self.values("noc", field="taxon"), ["Noctua pronuba"])

    def test_nothing_is_written_by_asking(self):
        records.import_terms(self.cx, "species", CHECKLIST)
        before = self.cx.execute("SELECT COUNT(*) c FROM field_values").fetchone()["c"]
        self.values("vesp")
        self.assertEqual(self.cx.execute("SELECT COUNT(*) c FROM field_values")
                         .fetchone()["c"], before)


class Ranking(Base):
    def setUp(self):
        super().setUp()
        records.import_terms(self.cx, "species", CHECKLIST)

    def rank(self, value, q, note=""):
        return records.match_rank(value, note, q)

    def test_the_order_of_preference(self):
        self.assertEqual(self.rank("Vespa crabro", "vespa crabro"), records.EXACT)
        self.assertEqual(self.rank("Vespa crabro", "vesp"), records.STARTS)
        self.assertEqual(self.rank("Vespa crabro", "crab"), records.WORD)
        self.assertEqual(self.rank("Vespa crabro", "horn", "hornet"), records.NOTE_STARTS)
        self.assertEqual(self.rank("Vespa crabro", "vecr"), records.INITIALS)
        self.assertEqual(self.rank("Vespa crabro", "espa"), records.CONTAINS)
        self.assertIsNone(self.rank("Vespa crabro", "zzz"))

    def test_a_name_that_starts_with_it_beats_one_that_merely_contains_it(self):
        self.assertEqual(self.values("vesp")[0], "Vespa crabro")

    def test_the_second_word_is_searchable_because_that_is_how_people_type(self):
        self.assertEqual(self.values("crab"), ["Vespa crabro"])

    def test_a_common_name_finds_the_scientific_one(self):
        self.assertEqual(self.values("hornet")[0], "Vespa crabro")

    def test_an_abbreviation_of_initials_finds_it(self):
        self.assertEqual(self.values("vecr"), ["Vespa crabro"])

    def test_case_is_ignored(self):
        self.assertEqual(self.values("VESPA CR"), ["Vespa crabro"])

    def test_the_limit_is_respected(self):
        self.assertEqual(len(records.suggest(self.cx, "species", "", limit=2)), 2)


class NeverRewritten(Base):
    def setUp(self):
        super().setUp()
        records.import_terms(self.cx, "species", CHECKLIST)

    def test_exactly_one_possibility_resolves_and_says_so(self):
        value, note, cands = entry.resolve(self.cx, self.prof, "species", "vecr")
        self.assertEqual(value, "Vespa crabro")
        self.assertIn("->", note)
        self.assertEqual(cands, [])

    def test_more_than_one_possibility_writes_nothing(self):
        value, _note, cands = entry.resolve(self.cx, self.prof, "species", "bomb")
        self.assertEqual(value, "bomb")
        self.assertEqual(sorted(cands), ["Bombus lapidarius", "Bombus terrestris"])

    def test_a_name_recorded_here_can_be_resolved_even_if_it_is_on_no_list(self):
        server.save_record(self.cx, self.ids[0], {"species": "Andrena fulva"})
        self.assertEqual(entry.resolve(self.cx, self.prof, "species", "andr")[0],
                         "Andrena fulva")

    def test_only_the_case_is_corrected_for_a_name_already_known(self):
        self.assertEqual(entry.resolve(self.cx, self.prof, "species", "vespa crabro")[0],
                         "Vespa crabro")

    def test_a_name_typed_out_in_full_is_left_exactly_as_typed(self):
        for typed in ("Vespa germanica", "Andrena cf. fulva", "Bombus sp."):
            self.assertEqual(entry.resolve(self.cx, self.prof, "species", typed)[0], typed)

    def test_something_nothing_matches_is_kept(self):
        self.assertEqual(entry.resolve(self.cx, self.prof, "species", "qqqq")[0], "qqqq")

    def test_what_the_window_offers_and_what_the_terminal_resolves_agree(self):
        for q in ("vesp", "bomb", "vecr", "hornet"):
            offered = self.values(q)
            value, _n, cands = entry.resolve(self.cx, self.prof, "species", q)
            if cands:
                self.assertTrue(set(cands) <= set(offered), q)
            elif value != q:
                self.assertEqual(value, offered[0], q)


class OverHttp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import threading
        cls.tmp = Path(tempfile.mkdtemp())
        cx = db.connect(cls.tmp / "t.db")
        fixtures.write(cls.tmp / "a.jpg")
        scan.scan(cx, [cls.tmp])
        records.import_terms(cx, "species", CHECKLIST)
        pid = cx.execute("SELECT id FROM photos").fetchone()["id"]
        server.save_record(cx, pid, {"species": "Vespa crabro"})
        cx.close()
        cls.httpd, url = server.serve(cls.tmp / "t.db", port=8987)
        cls.base, _, cls.token = url.partition("?t=")
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()

    def get(self, path):
        return json.load(urllib.request.urlopen(
            f"{self.base.rstrip('/')}{path}&t={self.token}"))

    def test_the_window_gets_everything_it_needs_to_draw_a_row(self):
        rows = self.get("/api/suggest?field=species&q=vesp")
        self.assertTrue(rows)
        for key in ("value", "note", "n", "listed", "rank"):
            self.assertIn(key, rows[0])
        self.assertEqual(rows[0]["value"], "Vespa crabro")
        self.assertEqual(rows[0]["n"], 1)
        self.assertEqual(rows[0]["note"], "hornet")

    def test_an_empty_query_is_allowed_and_offers_what_is_used(self):
        self.assertEqual(self.get("/api/suggest?field=species&q=")[0]["value"],
                         "Vespa crabro")

    def test_a_field_with_nothing_in_it_returns_an_empty_list(self):
        self.assertEqual(self.get("/api/suggest?field=nothing_like_this&q=a"), [])


class TheWindowItself(unittest.TestCase):
    """The page cannot be exercised here, but these pieces must not be lost by
    accident. The interaction itself is checked in a real browser."""

    def setUp(self):
        self.html = (Path(__file__).resolve().parents[1]
                     / "entolog" / "web" / "app.html").read_text()

    def test_the_suggestion_list_is_reachable_without_a_mouse(self):
        for piece in ('role="listbox"', 'role="combobox"', 'aria-activedescendant',
                      'aria-expanded', "ArrowDown", "ArrowUp", "Escape"):
            self.assertIn(piece, self.html, piece)

    def test_it_says_what_enter_will_do_rather_than_guessing(self):
        self.assertIn("keeps <b>${esc(q)}</b> as typed", self.html)

    def test_a_clicked_chip_is_not_mistaken_for_someone_typing(self):
        # A chip carries data-field and becomes the focused element when clicked,
        # so the guard that skips redrawing while typing must look at the tag.
        self.assertIn("el.tagName === 'INPUT' || el.tagName === 'TEXTAREA'", self.html)
        self.assertNotIn("focused.dataset.field", self.html)

    def test_a_chip_shows_its_new_state_before_the_save_comes_back(self):
        self.assertIn("o.classList.toggle('on', o.dataset.val === want)", self.html)

    def test_motion_can_be_turned_off(self):
        self.assertIn("prefers-reduced-motion", self.html)

    def test_there_is_a_fallback_where_glass_is_not_supported(self):
        self.assertIn("@supports not ((backdrop-filter", self.html)


if __name__ == "__main__":
    unittest.main(verbosity=2)
