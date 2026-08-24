"""The point of a profile is that entolog never needs to know what the fields are.
These tests use fields the code has never heard of."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import fixtures
from entolog import db, export, records, scan, server
from entolog import profile as P

MOTHS = {
    "name": "moths",
    "title": "Light trap catch",
    "primary": "taxon",
    "fields": [
        {"name": "taxon", "type": "text", "learn": True, "dwc": "scientificName"},
        {"name": "count", "type": "number", "min": 1, "dwc": "individualCount"},
        {"name": "trap", "type": "choice", "digits": True, "open": False,
         "choices": ["actinic", "MV", "LED", "sugar", "net"]},
        {"name": "worn", "type": "choice", "key": "w", "choices": ["", "fresh", "worn"]},
        {"name": "retained", "type": "bool", "key": "r"},
        {"name": "notes", "type": "multiline", "dwc": "occurrenceRemarks"},
    ],
    "export": {"columns": ["filename", "date", "gridref", "taxon", "count", "trap", "notes"]},
}


class Validation(unittest.TestCase):
    def bad(self, **over):
        prof = dict(MOTHS, **over)
        with self.assertRaises(P.ProfileError) as e:
            P.load(prof)
        return str(e.exception)

    def test_a_field_cannot_be_named_after_something_the_photo_provides(self):
        self.assertIn("comes from the photograph",
                      self.bad(fields=[{"name": "date"}, {"name": "taxon"}]))

    def test_two_fields_cannot_share_a_name(self):
        self.assertIn("defined twice",
                      self.bad(fields=[{"name": "taxon"}, {"name": "taxon"}]))

    def test_a_field_cannot_steal_a_key_entolog_uses(self):
        msg = self.bad(fields=[{"name": "taxon"}, {"name": "x", "type": "choice",
                                                   "choices": ["a"], "key": "j"}])
        self.assertIn("is not free", msg)

    def test_two_fields_cannot_share_a_key(self):
        msg = self.bad(fields=[
            {"name": "taxon"},
            {"name": "a", "type": "choice", "choices": ["1"], "key": "z"},
            {"name": "b", "type": "choice", "choices": ["1"], "key": "z"}])
        self.assertIn("already taken", msg)

    def test_only_one_field_can_own_the_number_keys(self):
        msg = self.bad(fields=[
            {"name": "taxon"},
            {"name": "a", "type": "choice", "choices": ["1"], "digits": True},
            {"name": "b", "type": "choice", "choices": ["1"], "digits": True}])
        self.assertIn("only one field", msg)

    def test_a_choice_field_needs_choices(self):
        self.assertIn("needs a list of choices",
                      self.bad(fields=[{"name": "taxon"}, {"name": "c", "type": "choice"}]))

    def test_export_columns_must_exist(self):
        self.assertIn("neither a field nor part of the photograph",
                      self.bad(export={"columns": ["filename", "wingspan"]}))

    def test_a_bare_string_is_a_valid_field(self):
        prof = P.load({"name": "quick", "fields": ["species", "notes"]})
        self.assertEqual(P.names(prof), ["species", "notes"])
        self.assertEqual(prof["primary"], "species")

    def test_builtins_all_load(self):
        for name in P.BUILTIN:
            self.assertTrue(P.load(name)["fields"])


class CustomFields(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.cx = db.connect(self.tmp / "t.db")
        self.addCleanup(self.cx.close)
        for i in range(3):
            fixtures.write(self.tmp / f"m{i}.jpg", dt=f"2026:07:0{i + 1} 23:1{i}:00",
                           lat=(52, 39, 28.7), lon=(1, 42, 57.8), lon_ref="E")
        scan.scan(self.cx, [self.tmp])
        self.prof = P.set_active(self.cx, MOTHS)
        self.ids = [r["id"] for r in self.cx.execute("SELECT id FROM photos ORDER BY seq")]

    def test_fields_the_code_has_never_seen_round_trip(self):
        records.save(self.cx, self.prof, self.ids[0],
                     {"taxon": "Deilephila elpenor", "count": "2", "trap": "actinic",
                      "worn": "fresh", "notes": "in the egg boxes"})
        v = records.values(self.cx, self.ids[0])
        self.assertEqual(v["taxon"], "Deilephila elpenor")
        self.assertEqual(v["trap"], "actinic")
        self.assertEqual(v["notes"], "in the egg boxes")

    def test_the_export_columns_are_the_profiles(self):
        records.save(self.cx, self.prof, self.ids[0], {"taxon": "Noctua pronuba", "count": "4"})
        head = export.render(self.cx, "csv").splitlines()[0]
        self.assertEqual(head, "filename,date,gridref,taxon,count,trap,notes")
        self.assertIn("Noctua pronuba", export.render(self.cx, "csv"))

    def test_the_grid_reference_is_worked_out_from_the_position(self):
        row = self.cx.execute("SELECT gridref FROM photos LIMIT 1").fetchone()
        self.assertTrue(row["gridref"].startswith("TG"))

    def test_darwin_core_uses_each_fields_own_term(self):
        records.save(self.cx, self.prof, self.ids[0], {"taxon": "Noctua pronuba", "count": "4"})
        text = export.render(self.cx, "dwc")
        head, row = text.splitlines()[0], text.splitlines()[1]
        self.assertIn("scientificName", head)
        self.assertIn("individualCount", head)
        self.assertNotIn("lifeStage", head)          # this profile has no such field
        self.assertIn("Noctua pronuba", row)

    def test_a_number_field_refuses_words_but_keeps_what_was_typed(self):
        ids, errors = records.save(self.cx, self.prof, self.ids[0], {"count": "a few"})
        self.assertIn("count", errors)
        self.assertEqual(records.values(self.cx, self.ids[0])["count"], "a few")

    def test_a_closed_choice_refuses_anything_else(self):
        _ids, errors = records.save(self.cx, self.prof, self.ids[0], {"trap": "moonlight"})
        self.assertIn("trap", errors)
        _ids, ok = records.save(self.cx, self.prof, self.ids[0], {"trap": "MV"})
        self.assertEqual(ok, {})

    def test_an_unknown_field_is_reported_not_written(self):
        _ids, errors = records.save(self.cx, self.prof, self.ids[0], {"wingspan": "40"})
        self.assertIn("wingspan", errors)
        self.assertNotIn("wingspan", records.values(self.cx, self.ids[0]))

    def test_bool_fields_normalise(self):
        records.save(self.cx, self.prof, self.ids[0], {"retained": "true"})
        self.assertEqual(records.values(self.cx, self.ids[0])["retained"], "yes")

    def test_done_and_todo_follow_the_profiles_primary_field(self):
        records.save(self.cx, self.prof, self.ids[0], {"taxon": "Xestia c-nigrum"})
        self.assertEqual(records.counts(self.cx, self.prof)["done"], 1)
        self.assertEqual(len(records.list_photos(self.cx, self.prof, "todo")), 2)
        self.assertEqual(len(records.list_photos(self.cx, self.prof, "all", q="c-nigrum")), 1)

    def test_flagging_is_kept_apart_from_the_recorders_fields(self):
        records.save(self.cx, self.prof, self.ids[1], {"_flag": "1"})
        self.assertEqual(len(records.list_photos(self.cx, self.prof, "flagged")), 1)
        self.assertNotIn("_flag", export.render(self.cx, "csv", only_determined=False))


class Switching(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.cx = db.connect(self.tmp / "t.db")
        self.addCleanup(self.cx.close)
        fixtures.write(self.tmp / "a.jpg")
        scan.scan(self.cx, [self.tmp])
        self.pid = self.cx.execute("SELECT id FROM photos").fetchone()["id"]
        server.save_record(self.cx, self.pid,
                           {"species": "Vespa crabro", "confidence": "certain"})

    def test_switching_profile_refuses_to_orphan_a_field_that_holds_records(self):
        with self.assertRaises(P.ProfileError) as e:
            P.set_active(self.cx, "wildlife")
        self.assertIn("confidence (1 record)", str(e.exception))

    def test_force_switches_and_the_values_are_still_there_afterwards(self):
        P.set_active(self.cx, "wildlife", force=True)
        self.assertNotIn("confidence", export.render(self.cx, "csv"))
        P.set_active(self.cx, "insects", force=True)
        self.assertIn("certain", export.render(self.cx, "full"))

    def test_a_profile_that_only_adds_fields_switches_freely(self):
        plus = P.load("insects")
        plus["fields"].append({"name": "host_plant", "type": "text", "learn": True,
                               "dwc": "associatedTaxa"})
        plus["export"]["columns"].append("host_plant")
        P.set_active(self.cx, plus)
        server.save_record(self.cx, self.pid, {"host_plant": "Hedera helix"})
        self.assertIn("Hedera helix", export.render(self.cx, "csv"))

    def test_the_database_carries_its_own_definition(self):
        stored = json.loads(self.cx.execute(
            "SELECT v FROM meta WHERE k='profile'").fetchone()["v"])
        self.assertEqual(stored["name"], "insects")


class OldDatabase(unittest.TestCase):
    """A 1.0 database kept its record in fixed columns. Opening it must move
    those across without anyone asking."""

    def test_records_made_before_profiles_are_carried_over(self):
        tmp = Path(tempfile.mkdtemp())
        cx = db.connect(tmp / "old.db")
        fixtures.write(tmp / "a.jpg")
        scan.scan(cx, [tmp])
        pid = cx.execute("SELECT id FROM photos").fetchone()["id"]
        cx.execute("INSERT INTO records(photo_id, species, stage, sex, comments, flagged) "
                   "VALUES(?,?,?,?,?,1)", (pid, "Bombus lapidarius", "adult", "worker", "on knapweed"))
        cx.execute("DELETE FROM field_values")
        cx.execute("DELETE FROM meta WHERE k='carried_over'")
        cx.commit()
        cx.close()

        cx = db.connect(tmp / "old.db")
        self.addCleanup(cx.close)
        v = records.values(cx, pid)
        self.assertEqual(v["species"], "Bombus lapidarius")
        self.assertEqual(v["sex"], "worker")
        self.assertEqual(v["_flag"], "1")
        self.assertIn("Bombus lapidarius", export.render(cx, "csv"))


class Checklists(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.cx = db.connect(self.tmp / "t.db")
        self.addCleanup(self.cx.close)

    def test_a_checklist_can_be_loaded_into_any_field(self):
        n = records.import_terms(self.cx, "host_plant",
                                 ["Hedera helix\tivy", "Urtica dioica\tcommon nettle", ""])
        self.assertEqual(n, 2)
        hits = records.suggest(self.cx, "host_plant", "nettle")
        self.assertEqual(hits[0]["value"], "Urtica dioica")

    def test_what_gets_typed_is_offered_first_next_time(self):
        prof = P.active(self.cx)
        records.import_terms(self.cx, "species", ["Bombus terrestris", "Bombus lucorum"])
        records.learn(self.cx, "species", "Bombus lucorum", uses=5)
        self.assertEqual(records.suggest(self.cx, "species", "Bombus")[0]["value"],
                         "Bombus lucorum")


if __name__ == "__main__":
    unittest.main(verbosity=2)
