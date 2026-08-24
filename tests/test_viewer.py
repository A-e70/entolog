"""The zoom arithmetic, run as the window runs it.

The window cannot be exercised from Python, but the part that decides how far a
wheel turns and where the photograph ends up is pure arithmetic. It is lifted out
of app.html and run in node, so it is the shipped code being tested rather than a
copy of it. Skipped where node is not installed.
"""

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "entolog" / "web" / "app.html"
BEGIN = "/* ---------- viewer maths ---------- begin testable"
END = "/* ---------- viewer maths ---------- end testable */"
NODE = shutil.which("node")


def maths() -> str:
    text = APP.read_text()
    start = text.index(BEGIN)
    end = text.index(END)
    return text[start:end]


class Extraction(unittest.TestCase):
    def test_the_window_still_carries_a_testable_block(self):
        block = maths()
        for name in ("wheelFactor", "maxZoom", "clampZoom", "toLocal", "panFor",
                     "clampPan"):
            self.assertIn(f"function {name}", block, name)

    def test_the_block_touches_no_browser(self):
        block = maths()
        for forbidden in ("document", "window", "getBoundingClientRect", "requestAnimationFrame"):
            self.assertNotIn(forbidden, block, forbidden)


@unittest.skipUnless(NODE, "node is not installed")
class Arithmetic(unittest.TestCase):
    def run_js(self, body: str):
        script = maths() + "\nconst out = {};\n" + body + "\nconsole.log(JSON.stringify(out));\n"
        path = Path(tempfile.mkdtemp()) / "check.js"
        path.write_text(script)
        done = subprocess.run([NODE, str(path)], capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads(done.stdout.strip().splitlines()[-1])

    def test_a_mouse_notch_is_a_quarter_and_a_trackpad_tick_is_a_hair(self):
        got = self.run_js("""
          out.notch = wheelFactor(-100, 0, false);
          out.tick = wheelFactor(-4, 0, false);
          out.line = wheelFactor(-3, 1, false);
          out.pinch = wheelFactor(-20, 0, true);
        """)
        self.assertAlmostEqual(got["notch"], 1.246, places=2)
        self.assertLess(got["tick"], 1.02)          # ten of these is still gentle
        self.assertGreater(got["line"], 1.05)       # a line mode wheel still moves
        self.assertLess(got["line"], 1.3)
        self.assertGreater(got["pinch"], 1.1)

    def test_zooming_in_then_out_by_the_same_amount_comes_back(self):
        got = self.run_js("""
          out.round = wheelFactor(-100, 0, false) * wheelFactor(100, 0, false);
        """)
        self.assertAlmostEqual(got["round"], 1.0, places=6)

    def test_one_violent_flick_is_still_one_step(self):
        got = self.run_js("""
          out.flick = wheelFactor(-4000, 0, false);
          out.capped = wheelFactor(-160, 0, false);
        """)
        self.assertEqual(got["flick"], got["capped"])
        self.assertLess(got["flick"], 1.5)

    def test_how_far_it_may_be_zoomed_follows_the_photograph(self):
        got = self.run_js("""
          out.big = maxZoom(6000, 850);      // a real photograph, fitted
          out.small = maxZoom(400, 400);     // already at its own pixels
          out.huge = maxZoom(60000, 850);    // absurd, but must not be
          out.unknown = maxZoom(0, 850);     // not loaded yet
        """)
        self.assertEqual(got["big"], 32)                  # 4.5 times its own pixels
        self.assertEqual(got["small"], 8)                 # 8 times its own pixels
        self.assertEqual(got["huge"], 32)
        self.assertEqual(got["unknown"], 12)

    def test_every_photograph_can_be_magnified_well_past_its_own_pixels(self):
        got = self.run_js("""
          out.cases = [[400, 400], [1200, 850], [4000, 850], [6000, 850]]
            .map(([n, f]) => (maxZoom(n, f) * f) / n);   // times its own pixels
        """)
        for times in got["cases"]:
            self.assertGreaterEqual(times, 4, got["cases"])

    def test_zoom_never_goes_below_fitting_or_above_the_limit(self):
        got = self.run_js("""
          out.under = clampZoom(0.2, 8);
          out.over = clampZoom(99, 8);
          out.inside = clampZoom(3, 8);
        """)
        self.assertEqual((got["under"], got["over"], got["inside"]), (1, 8, 3))

    def test_the_point_under_the_pointer_stays_under_the_pointer(self):
        got = self.run_js("""
          // a photograph 2000 wide laid out at 30 inside the stage, viewport 900
          const base = 30, point = 512;
          let z = 1, ox = 0;
          out.drift = [];
          for (let i = 0; i < 12; i++){
            const local = toLocal(point, base, ox, z);
            const next = clampZoom(z * wheelFactor(-100, 0, false), 12);
            ox = panFor(point, base, local, next);
            z = next;
            out.drift.push(toLocal(point, base, ox, z) - local);
          }
          out.worst = Math.max(...out.drift.map(Math.abs));
        """)
        self.assertLess(got["worst"], 1e-9)

    def test_a_photograph_smaller_than_the_window_sits_in_the_middle(self):
        got = self.run_js("""
          // 400 wide, laid out at 250 in a 900 viewport, so already centred
          out.centred = clampPan(0, 250, 400, 900, 1);
          out.pulled = clampPan(500, 250, 400, 900, 1);
          out.scaled = clampPan(0, 250, 400, 900, 2);
        """)
        self.assertEqual(got["centred"], 0)
        self.assertEqual(got["pulled"], 0)          # cannot be dragged off centre
        self.assertEqual(got["scaled"], -200)       # 800 wide in 900, still centred

    def test_a_photograph_larger_than_the_window_cannot_be_dragged_past_its_edges(self):
        got = self.run_js("""
          // 400 laid out at 250 in a 900 viewport, zoomed to 4 so it is 1600 wide
          out.left = clampPan(99999, 250, 400, 900, 4);
          out.right = clampPan(-99999, 250, 400, 900, 4);
          out.free = clampPan(-300, 250, 400, 900, 4);
        """)
        self.assertEqual(got["left"], -250)                 # left edge against the wall
        self.assertEqual(got["right"], 900 - 250 - 1600)    # right edge against it
        self.assertEqual(got["free"], -300)                 # in between, untouched

    def test_the_clamp_leaves_no_gap_at_either_side(self):
        got = self.run_js("""
          const base = 250, size = 400, view = 900, z = 4;
          const ox = clampPan(99999, base, size, view, z);
          out.leftGap = base + ox;
          out.rightGap = view - (base + ox + size * z);
        """)
        self.assertEqual(got["leftGap"], 0)
        self.assertLessEqual(got["rightGap"], 0)
