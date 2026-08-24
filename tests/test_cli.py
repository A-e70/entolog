"""Import everything and build the command line.

The rest of the suite exercises the modules directly, so nothing else imports
entolog.cli. Continuous integration found a line in it that no Python before 3.12
could parse, and these tests are why that will not happen twice.
"""

import io
import pkgutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import entolog
from entolog import cli
from entolog import profile as P


class EveryModule(unittest.TestCase):
    def test_all_of_them_import(self):
        missed = []
        for mod in pkgutil.iter_modules(entolog.__path__):
            if mod.name == "__main__":          # importing it would run entolog
                continue
            try:
                __import__(f"entolog.{mod.name}")
            except Exception as e:                       # a syntax error included
                missed.append(f"{mod.name}: {e}")
        self.assertEqual(missed, [])

    def test_the_version_is_set(self):
        self.assertRegex(entolog.__version__, r"^\d+\.\d+\.\d+$")


class CommandLine(unittest.TestCase):
    def run_cli(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            try:
                code = cli.main(argv)
            except SystemExit as e:             # how argparse and _open bow out
                code = e.code if isinstance(e.code, int) else 1
        return code, out.getvalue() + err.getvalue()

    def test_every_command_is_wired_to_something(self):
        parser = cli.build_parser()
        actions = [a for a in parser._actions if hasattr(a, "choices") and a.choices
                   and hasattr(a, "_name_parser_map")]
        self.assertTrue(actions, "no subcommands found")
        for name, sub in actions[0]._name_parser_map.items():
            self.assertTrue(sub.get_default("func"), f"{name} has no function")

    def test_bare_entolog_says_what_to_do_first(self):
        code, text = self.run_cli([])
        self.assertEqual(code, 0)
        self.assertIn("entolog demo", text)
        self.assertIn("--help", text)

    def test_help_and_version_do_not_need_a_database(self):
        for argv in (["--version"], ["--help"]):
            code, text = self.run_cli(argv)
            self.assertEqual(code, 0, argv)
            self.assertTrue(text.strip())

    def test_doctor_runs_anywhere(self):
        code, text = self.run_cli(["--db", str(Path(tempfile.mkdtemp()) / "x.db"),
                                   "doctor"])
        self.assertEqual(code, 0)
        self.assertIn("python", text)

    def test_a_command_needing_a_database_says_so_rather_than_crashing(self):
        missing = Path(tempfile.mkdtemp()) / "nothing.db"
        for argv in (["enter"], ["line"], ["check"], ["edit"]):
            code, text = self.run_cli(["--db", str(missing)] + argv)
            self.assertEqual(code, 1, argv)
            self.assertIn("entolog scan", text)

    def test_profile_list_needs_nothing_at_all(self):
        code, text = self.run_cli(["profile", "list"])
        self.assertEqual(code, 0)
        for name in P.BUILTIN:
            self.assertIn(name, text)

    def test_the_first_run_text_only_mentions_real_commands(self):
        names = set(cli.build_parser()._actions[-1].choices)
        for line in cli.FIRST_RUN.splitlines():
            line = line.strip()
            if not line.startswith("entolog "):
                continue
            word = line.split()[1]
            if not word.isalpha():              # the heading, and paths like ~/photos
                continue
            self.assertIn(word, names, line)


if __name__ == "__main__":
    unittest.main(verbosity=2)
