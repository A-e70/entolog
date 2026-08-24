"""The terminal loop, the viewer hooks and the editable table. Same profile,
same validation, same storage as the window."""

import json
import sys
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import fixtures
from entolog import db, entry, export, records, scan, server, tsvedit
from entolog import profile as P


def shoot(tmp, name, minutes=0, **kw):
    from datetime import datetime, timedelta
    t = datetime(2026, 6, 14, 9, 30) + timedelta(minutes=minutes)
    return fixtures.write(tmp / name, dt=t.strftime("%Y:%m:%d %H:%M:%S"), **kw)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.cx = db.connect(self.tmp / "t.db")
        self.addCleanup(self.cx.close)
        for i in range(3):                      # one event of three
            shoot(self.tmp, f"a{i}.jpg", i * 0.4)
        shoot(self.tmp, "b0.jpg", 30)           # a second event
        shoot(self.tmp, "b1.jpg", 30.3)
        shoot(self.tmp, "c0.jpg", 90)           # a third
        scan.scan(self.cx, [self.tmp])
        self.prof = P.active(self.cx)
        self.ids = [r["id"] for r in self.cx.execute("SELECT id FROM photos ORDER BY seq")]


class Grammar(Base):
    def p(self, line):
        return entry.parse(self.prof, line)

    def test_fields_in_order_separated_by_slashes(self):
        kind, out = self.p("Vespa crabro / adult / f / on ivy")
        self.assertEqual(kind, "fields")
        self.assertEqual(out, {"species": "Vespa crabro", "stage": "adult",
                               "sex": "f", "comments": "on ivy"})

    def test_an_empty_segment_leaves_that_field_as_it_was(self):
        _k, out = self.p("Andrena / / m")
        self.assertNotIn("stage", out)
        self.assertEqual(out["sex"], "m")

    def test_a_dash_clears_a_field(self):
        _k, out = self.p("Andrena / -")
        self.assertEqual(out["stage"], "")

    def test_too_many_segments_is_refused_rather_than_truncated(self):
        kind, msg = self.p("a/b/c/d/e/f/g")
        self.assertEqual(kind, "error")
        self.assertIn("7 parts", msg)

    def test_name_equals_value_in_any_order(self):
        _k, out = self.p("sex=female species='Bombus terrestris'")
        self.assertEqual(out, {"sex": "female", "species": "Bombus terrestris"})

    def test_an_unknown_field_name_is_refused(self):
        kind, msg = self.p("wingspan=40")
        self.assertEqual(kind, "error")
        self.assertIn("wingspan", msg)

    def test_a_bare_line_is_the_primary_field(self):
        self.assertEqual(self.p("Bombus lapidarius"), ("fields", {"species": "Bombus lapidarius"}))

    def test_commands_are_colon_or_punctuation_and_never_a_name(self):
        self.assertEqual(self.p(":q")[1][0], "q")
        self.assertEqual(self.p(":n 12")[1], ("n", "12"))
        self.assertEqual(self.p("#")[1][0], "#")
        self.assertEqual(self.p("?")[1][0], "h")
        # a name that starts with a letter is always a record, whatever it says
        self.assertEqual(self.p("q")[0], "fields")
        self.assertEqual(self.p("noctua : pale form")[0], "fields")

    def test_blank_line_is_a_skip(self):
        self.assertEqual(self.p("   ")[0], "blank")


class Resolving(Base):
    def setUp(self):
        super().setUp()
        records.import_terms(self.cx, "species",
                             ["Vespa crabro", "Vespula vulgaris", "Bombus terrestris"])

    def r(self, field, text):
        return entry.resolve(self.cx, self.prof, field, text)

    def test_an_abbreviation_of_initials_resolves(self):
        value, note, cands = self.r("species", "vecr")
        self.assertEqual(value, "Vespa crabro")
        self.assertIn("->", note)
        self.assertEqual(cands, [])

    def test_a_prefix_resolves(self):
        self.assertEqual(self.r("species", "bomb")[0], "Bombus terrestris")

    def test_an_ambiguous_abbreviation_writes_nothing_and_offers_the_choices(self):
        value, _note, cands = self.r("species", "ves")
        self.assertEqual(value, "ves")
        self.assertEqual(sorted(cands), ["Vespa crabro", "Vespula vulgaris"])

    def test_a_name_typed_out_in_full_is_never_rewritten(self):
        self.assertEqual(self.r("species", "Vespa germanica")[0], "Vespa germanica")

    def test_a_new_name_is_kept_as_typed(self):
        self.assertEqual(self.r("species", "Andrena fulva")[0], "Andrena fulva")

    def test_choices_take_a_prefix(self):
        self.assertEqual(self.r("stage", "lar")[0], "larva")
        self.assertEqual(self.r("sex", "f")[0], "female")

    def test_an_ambiguous_choice_prefix_is_offered_not_guessed(self):
        value, _n, cands = self.r("stage", "e")
        self.assertEqual(value, "e")
        self.assertEqual(sorted(cands), ["egg", "exuvia"])

    def test_case_does_not_matter(self):
        self.assertEqual(self.r("species", "VESPA CRABRO")[0], "Vespa crabro")


class Loop(Base):
    def sess(self, **kw):
        return entry.Session(self.cx, self.prof, **kw)

    def test_one_line_records_a_whole_event_and_moves_to_the_next(self):
        s = self.sess(flt="todo")
        first_event = s.photo["group_id"]
        out = s.handle("Vespa crabro / adult / f / on ivy")
        self.assertIn("saved 3 photographs", " ".join(out["say"]))
        self.assertNotEqual(s.photo["group_id"], first_event)
        n = self.cx.execute("SELECT COUNT(*) c FROM field_values WHERE field='species' "
                            "AND value='Vespa crabro'").fetchone()["c"]
        self.assertEqual(n, 3)

    def test_per_photo_mode_records_one_at_a_time(self):
        s = self.sess(flt="todo", per_photo=True)
        s.handle("Vespa crabro")
        n = self.cx.execute("SELECT COUNT(*) c FROM field_values WHERE field='species'"
                            " AND value!=''").fetchone()["c"]
        self.assertEqual(n, 1)

    def test_repeat_applies_the_last_record_again(self):
        s = self.sess(flt="todo")
        s.handle("Vespa crabro / adult")
        s.handle(".")
        vals = records.values(self.cx, s.photos[3]["id"])
        self.assertEqual(vals["species"], "Vespa crabro")

    def test_dash_clears_and_hash_flags(self):
        s = self.sess(flt="all")
        s.handle("Vespa crabro")
        s.handle(":n 1")
        s.handle("-")
        self.assertEqual(records.values(self.cx, self.ids[0]).get("species", ""), "")
        s.handle("#")
        self.assertEqual(len(records.list_photos(self.cx, self.prof, "flagged")), 1)
        s.handle("#")
        self.assertEqual(len(records.list_photos(self.cx, self.prof, "flagged")), 0)

    def test_star_switches_between_event_and_photograph(self):
        s = self.sess(flt="todo")
        self.assertTrue(s.group)
        say = s.handle("*")["say"]
        self.assertIn("off", " ".join(say))
        s.handle("Vespa crabro")
        self.assertEqual(len(records.list_photos(self.cx, self.prof, "done")), 1)

    def test_moving_about(self):
        s = self.sess(flt="all")
        s.handle(">")
        self.assertEqual(s.i, 1)
        s.handle("<")
        self.assertEqual(s.i, 0)
        self.assertIn("first", " ".join(s.handle("<")["say"]))
        s.handle(":n 5")
        self.assertEqual(s.i, 4)
        s.handle(":n 999")
        self.assertEqual(s.i, len(s.photos) - 1)

    def test_filter_command_and_quit(self):
        s = self.sess(flt="all")
        s.handle("Vespa crabro")
        self.assertIn("photographs", " ".join(s.handle(":f done")["say"]))
        self.assertEqual(s.filter, "done")
        self.assertIn("filters:", " ".join(s.handle(":f rubbish")["say"]))
        self.assertTrue(s.handle(":q")["quit"])

    def test_an_unknown_command_says_so_rather_than_recording_it(self):
        s = self.sess(flt="all")
        self.assertIn("no command", " ".join(s.handle(":zz")["say"]))
        self.assertEqual(records.counts(self.cx, self.prof)["done"], 0)

    def test_plus_jumps_to_what_the_viewer_is_showing(self):
        s = self.sess(flt="todo")
        entry.set_current(self.cx, str(self.tmp / "c0.jpg"))
        s.handle("+")
        self.assertEqual(s.photo["filename"], "c0.jpg")

    def test_plus_widens_the_filter_when_the_photograph_is_not_listed(self):
        s = self.sess(flt="todo")
        server.save_record(self.cx, self.ids[5], {"species": "Aglais urticae"})
        s.reload()
        entry.set_current(self.cx, str(self.tmp / "c0.jpg"))
        s.handle("+")
        self.assertEqual(s.filter, "all")
        self.assertEqual(s.photo["filename"], "c0.jpg")

    def test_write_command_writes_the_table(self):
        s = self.sess(flt="all")
        s.handle("Vespa crabro")
        out = self.tmp / "out.tsv"
        s.handle(f":w {out}")
        self.assertIn("Vespa crabro", out.read_text())
        self.assertIn("\t", out.read_text())

    def test_show_lists_every_field_of_the_profile(self):
        s = self.sess(flt="all")
        said = " ".join(s.handle(":s")["say"])
        for name in P.names(self.prof):
            self.assertIn(name.replace("_", " "), said)

    def test_a_validation_failure_reports_and_does_not_advance(self):
        P.set_active(self.cx, {"name": "counted", "primary": "species",
                               "fields": [{"name": "species"},
                                          {"name": "count", "type": "number", "min": 1}]},
                     force=True)
        s = entry.Session(self.cx, P.active(self.cx), flt="all")
        where = s.i
        say = s.handle("count=lots")["say"]
        self.assertIn("count takes a number", " ".join(say))
        self.assertEqual(s.i, where)

    def test_an_ambiguous_name_offers_the_choices_and_claims_nothing(self):
        records.import_terms(self.cx, "species",
                             ["Bombus terrestris", "Bombus lapidarius"])
        s = self.sess(flt="all")
        said = " ".join(s.handle("bomb")["say"])
        self.assertIn("could be", said)
        self.assertIn("Bombus terrestris", said)
        self.assertNotIn("saved", said)
        self.assertEqual(records.counts(self.cx, self.prof)["done"], 0)
        self.assertEqual(s.i, 0)

    def test_blank_line_steps_on(self):
        s = self.sess(flt="all")
        s.handle("")
        self.assertEqual(s.i, 1)


class Viewer(Base):
    def test_find_by_number_path_and_filename(self):
        self.assertEqual(entry.find(self.cx, str(self.ids[0]))["id"], self.ids[0])
        self.assertEqual(entry.find(self.cx, str(self.tmp / "b0.jpg"))["filename"], "b0.jpg")
        self.assertEqual(entry.find(self.cx, "b1.jpg")["filename"], "b1.jpg")

    def test_a_filename_in_two_folders_is_refused_rather_than_guessed(self):
        sub = self.tmp / "second"
        sub.mkdir()
        shoot(sub, "b0.jpg", 200)
        scan.scan(self.cx, [self.tmp])
        with self.assertRaises(LookupError) as e:
            entry.find(self.cx, "b0.jpg")
        self.assertIn("matches 2", str(e.exception))
        self.assertEqual(entry.find(self.cx, str(sub / "b0.jpg"))["rel_path"], "second/b0.jpg")

    def test_an_unscanned_file_says_so(self):
        with self.assertRaises(LookupError):
            entry.find(self.cx, "/nowhere/x.jpg")

    def test_current_round_trips(self):
        entry.set_current(self.cx, "b0.jpg")
        self.assertEqual(entry.get_current(self.cx)["filename"], "b0.jpg")

    def test_no_current_photograph_is_not_an_error(self):
        self.assertIsNone(entry.get_current(self.cx))

    def test_the_status_line_carries_what_a_viewer_needs(self):
        server.save_record(self.cx, self.ids[0], {"species": "Vespa crabro", "stage": "adult"})
        line = entry.status_line(self.cx, self.prof, entry.find(self.cx, str(self.ids[0])))
        self.assertIn("a0.jpg", line)
        self.assertIn("2026-06-14", line)
        self.assertIn("Vespa crabro adult", line)

    def test_the_format_is_the_users(self):
        server.save_record(self.cx, self.ids[0], {"species": "Vespa crabro"})
        line = entry.status_line(self.cx, self.prof, entry.find(self.cx, str(self.ids[0])),
                                 fmt="{filename}|{species}|{gridref}|{nothing_like_this}")
        self.assertTrue(line.startswith("a0.jpg|Vespa crabro|"))
        self.assertTrue(line.endswith("|"))

    def test_a_photograph_with_no_position_still_makes_a_line(self):
        bare = self.tmp / "nogps.jpg"
        fixtures.write(bare, gps=False)
        scan.scan(self.cx, [self.tmp])
        line = entry.status_line(self.cx, self.prof, entry.find(self.cx, "nogps.jpg"))
        self.assertIn("nogps.jpg", line)

    def test_record_one_writes_the_whole_event(self):
        photo = entry.find(self.cx, "a0.jpg")
        say, ids, clean, errors = entry.record_one(
            self.cx, self.prof, photo, "Vespa crabro / adult", group=True)
        self.assertEqual(errors, {})
        self.assertEqual(len(ids), 3)
        self.assertEqual(clean["stage"], "adult")

    def test_record_one_refuses_a_command(self):
        photo = entry.find(self.cx, "a0.jpg")
        _say, ids, _clean, errors = entry.record_one(self.cx, self.prof, photo, ":q")
        self.assertEqual(ids, [])
        self.assertTrue(errors)


class Table(Base):
    def setUp(self):
        super().setUp()
        server.save_record(self.cx, self.ids[0],
                           {"species": "Vespa crabro", "stage": "adult",
                            "comments": "on ivy"})

    def test_round_trip_through_an_edit(self):
        text = tsvedit.dump(self.cx, self.prof)
        edited = text.replace("Vespa crabro", "Vespula vulgaris")
        r = tsvedit.apply(self.cx, self.prof, edited)
        self.assertEqual(r["changed"], 1)
        self.assertEqual(records.values(self.cx, self.ids[0])["species"], "Vespula vulgaris")

    def test_columns_may_be_reordered_or_removed(self):
        text = "id\tcomments\tspecies\n" + f"{self.ids[0]}\tin the hedge\tAndrena fulva\n"
        r = tsvedit.apply(self.cx, self.prof, text)
        v = records.values(self.cx, self.ids[0])
        self.assertEqual((v["species"], v["comments"]), ("Andrena fulva", "in the hedge"))
        self.assertEqual(v["stage"], "adult")          # column absent, so untouched
        self.assertEqual(r["changed"], 1)

    def test_deleting_a_row_leaves_that_record_alone(self):
        lines = tsvedit.dump(self.cx, self.prof).splitlines()
        kept = [l for l in lines if "a0.jpg" not in l]
        tsvedit.apply(self.cx, self.prof, "\n".join(kept))
        self.assertEqual(records.values(self.cx, self.ids[0])["species"], "Vespa crabro")

    def test_a_short_line_leaves_the_missing_columns_alone(self):
        text = f"id\tspecies\tstage\tcomments\n{self.ids[0]}\tAndrena fulva\n"
        tsvedit.apply(self.cx, self.prof, text)
        v = records.values(self.cx, self.ids[0])
        self.assertEqual(v["species"], "Andrena fulva")
        self.assertEqual(v["stage"], "adult")

    def test_an_id_that_is_not_in_the_database_is_reported(self):
        r = tsvedit.apply(self.cx, self.prof, f"id\tspecies\n99999\tAnything\n")
        self.assertEqual(r["unknown_rows"], [99999])
        self.assertEqual(r["changed"], 0)

    def test_a_row_with_no_usable_id_is_reported_not_guessed(self):
        r = tsvedit.apply(self.cx, self.prof, "id\tspecies\nnotanumber\tAnything\n\tx\n")
        self.assertEqual(len(r["problems"]), 2)
        self.assertEqual(r["changed"], 0)

    def test_a_file_with_no_header_or_no_id_column_is_refused(self):
        self.assertIn("no header", tsvedit.apply(self.cx, self.prof, "")["problems"][0])
        self.assertIn("no 'id' column",
                      tsvedit.apply(self.cx, self.prof, "species\tstage\nx\ty\n")["problems"][0])

    def test_comments_and_blank_lines_are_ignored(self):
        text = (f"# a note\n\nid\tspecies\n# another\n{self.ids[0]}\tAndrena fulva\n")
        r = tsvedit.apply(self.cx, self.prof, text)
        self.assertEqual(r["changed"], 1)

    def test_tabs_and_newlines_inside_a_value_survive(self):
        server.save_record(self.cx, self.ids[1], {"comments": "line one\nline\ttwo"})
        text = tsvedit.dump(self.cx, self.prof)
        self.assertEqual(len([l for l in text.splitlines() if l and not l.startswith("#")]),
                         1 + len(self.ids))
        tsvedit.apply(self.cx, self.prof, text)
        self.assertEqual(records.values(self.cx, self.ids[1])["comments"], "line one\nline\ttwo")

    def test_a_value_that_fails_validation_is_reported_and_still_stored(self):
        P.set_active(self.cx, {"name": "counted", "primary": "species",
                               "fields": [{"name": "species"},
                                          {"name": "count", "type": "number", "min": 1}]},
                     force=True)
        prof = P.active(self.cx)
        r = tsvedit.apply(self.cx, prof, f"id\tcount\n{self.ids[0]}\tplenty\n")
        self.assertTrue(any("count" in p for p in r["problems"]))
        self.assertEqual(records.values(self.cx, self.ids[0])["count"], "plenty")

    def test_the_editable_columns_are_the_profiles(self):
        head = [l for l in tsvedit.dump(self.cx, self.prof).splitlines()
                if l.strip() and not l.startswith("#")][0].split("\t")
        self.assertEqual(head[:1 + len(P.names(self.prof))],
                         ["id"] + P.names(self.prof))


class ServerCurrent(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import threading
        cls.tmp = Path(tempfile.mkdtemp())
        cx = db.connect(cls.tmp / "t.db")
        fixtures.write(cls.tmp / "a.jpg")
        fixtures.write(cls.tmp / "b.jpg", dt="2026:06:14 12:00:00")
        scan.scan(cx, [cls.tmp])
        cx.close()
        cls.httpd, url = server.serve(cls.tmp / "t.db", port=8977)
        cls.base, _, cls.token = url.partition("?t=")
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()

    def call(self, path, payload=None):
        sep = "&" if "?" in path else "?"
        url = f"{self.base.rstrip('/')}{path}{sep}t={self.token}"
        data = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(url, data=data,
                                     headers={"Content-Type": "application/json"})
        return json.load(urllib.request.urlopen(req))

    def test_nothing_current_to_begin_with(self):
        cx = db.connect(self.tmp / "t.db")
        cx.execute("DELETE FROM meta WHERE k='current_photo'")
        cx.commit()
        cx.close()
        self.assertIsNone(self.call("/api/current")["id"])

    def test_a_viewer_can_say_what_it_is_showing_and_the_window_can_read_it(self):
        self.call("/api/current", {"target": "b.jpg"})
        got = self.call("/api/current")
        self.assertEqual(got["filename"], "b.jpg")
        self.assertIn("b.jpg", got["line"])

    def test_an_unknown_file_is_a_404_not_a_crash(self):
        with self.assertRaises(urllib.error.HTTPError) as e:
            self.call("/api/current", {"target": "ghost.jpg"})
        self.assertEqual(e.exception.code, 404)


class StillWorks(Base):
    """Backwards compatibility: the older ways in must keep behaving."""

    def test_the_window_api_and_the_terminal_write_the_same_records(self):
        server.save_record(self.cx, self.ids[0], {"species": "Vespa crabro"})
        s = entry.Session(self.cx, self.prof, flt="all")
        s.handle(":n 4")
        s.handle("Andrena fulva")
        rows = export.render(self.cx, "csv")
        self.assertIn("Vespa crabro", rows)
        self.assertIn("Andrena fulva", rows)

    def test_a_database_from_1_0_can_be_recorded_in_from_the_terminal(self):
        pid = self.ids[0]
        self.cx.execute("INSERT INTO records(photo_id, species) VALUES(?,?)",
                        (pid, "Bombus lapidarius"))
        self.cx.execute("DELETE FROM field_values")
        self.cx.execute("DELETE FROM meta WHERE k='carried_over'")
        self.cx.commit()
        self.cx.close()
        cx = db.connect(self.tmp / "t.db")
        self.addCleanup(cx.close)
        prof = P.active(cx)
        s = entry.Session(cx, prof, flt="all")
        self.assertIn("Bombus lapidarius",
                      entry.status_line(cx, prof, s.photos[0]))
        s.handle(":n 4")
        s.handle("Andrena fulva")
        self.assertIn("Andrena fulva", tsvedit.dump(cx, prof))


if __name__ == "__main__":
    unittest.main(verbosity=2)
