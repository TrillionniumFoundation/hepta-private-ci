from pathlib import Path
import subprocess
import tempfile
import unittest

from hepta_entrypoints import inventory, markdown


class EntrypointTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)

    def write(self, name, text, *, tracked=True):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        if tracked:
            subprocess.run(
                ["git", "-C", str(self.root), "add", "-f", "--", name], check=True
            )
        return path

    def rows(self):
        return {row["script"]: row for row in inventory(self.root)["scripts"]}

    def test_only_tracked_source_not_environments_or_lockfiles(self):
        self.write("scripts/real.py", "pass\n")
        self.write("scripts/untracked.py", "pass\n", tracked=False)
        self.write("scripts/.venv/bin/python3", "#!/usr/bin/python3\n")
        self.write("scripts/.venv/site-packages/v.py", "pass\n")
        self.write("scripts/uv.lock", "lock = 1\n")
        self.write("scripts/pyproject.toml", "[project]\n")
        self.assertEqual(set(self.rows()), {"scripts/real.py"})

    def test_bare_interpreter_name_does_not_resolve_to_repository_file(self):
        self.write("scripts/python3", "#!/bin/sh\n")
        self.write(".github/workflows/test.yml", "run: python3 -V\n")
        self.assertEqual(self.rows()["scripts/python3"]["references"], [])

    def test_explicit_discovery_matches_filename_not_all_test_files(self):
        self.write("scripts/test_hepta_x.py", "pass\n")
        self.write("scripts/test_other.py", "pass\n")
        self.write(
            ".github/workflows/test.yml",
            "run: python3 -m unittest discover -v -s scripts -p 'test_hepta_*.py'\n",
        )
        rows = self.rows()
        self.assertEqual(
            rows["scripts/test_hepta_x.py"]["references"],
            [{"caller": ".github/workflows/test.yml", "kind": "discovery-pattern"}],
        )
        self.assertEqual(rows["scripts/test_other.py"]["status"], "unknown")

    def test_static_import_is_resolved_without_executing_module(self):
        self.write("scripts/helper.py", "raise RuntimeError('must not execute')\n")
        self.write("scripts/main.py", "from helper import value\n")
        self.assertEqual(
            self.rows()["scripts/helper.py"]["references"],
            [{"caller": "scripts/main.py", "kind": "static-import"}],
        )

    def test_qualified_and_relative_imports(self):
        self.write("scripts/package/__init__.py", "")
        self.write("scripts/package/helper.py", "pass\n")
        self.write("scripts/package/main.py", "from . import helper\n")
        self.write("scripts/runner.py", "from scripts.package.helper import value\n")
        refs = self.rows()["scripts/package/helper.py"]["references"]
        self.assertEqual(
            {ref["caller"] for ref in refs},
            {"scripts/package/main.py", "scripts/runner.py"},
        )

    def test_unknown_is_not_a_deletion_recommendation(self):
        self.write("scripts/manual.sh", "#!/bin/sh\n")
        document = inventory(self.root)
        self.assertEqual(document["scripts"][0]["status"], "unknown")
        self.assertIn("Unknown never means safe to delete", markdown(document))
        self.assertNotIn("candidate-archive", str(document))

    def test_generated_navigation_does_not_make_a_script_live(self):
        self.write("scripts/manual.py", "pass\n")
        self.write("scripts/ENTRYPOINTS.md", "scripts/manual.py\n")
        self.write("scripts/ENTRYPOINTS.json", '{"script":"scripts/manual.py"}\n')
        self.assertEqual(self.rows()["scripts/manual.py"]["references"], [])

    def test_deleted_and_symlinked_scripts_are_not_read(self):
        path = self.write("scripts/deleted.py", "pass\n")
        path.unlink()
        link = self.root / "scripts/link.py"
        link.symlink_to(self.root / "outside.py")
        subprocess.run(
            ["git", "-C", str(self.root), "add", "scripts/link.py"], check=True
        )
        self.assertEqual(self.rows(), {})

    def test_full_path_references_do_not_match_prefixes(self):
        self.write("scripts/run.py", "pass\n")
        self.write("justfile", "run: python3 scripts/run.py.backup\n")
        self.assertEqual(self.rows()["scripts/run.py"]["references"], [])
        self.write("justfile", "run: python3 scripts/run.py\n")
        self.assertEqual(self.rows()["scripts/run.py"]["status"], "referenced")

    def test_generation_is_deterministic_and_does_not_write(self):
        self.write("scripts/run.py", "pass\n")
        first = inventory(self.root)
        self.assertEqual(inventory(self.root), first)
        self.assertFalse((self.root / "scripts/ENTRYPOINTS.json").exists())


if __name__ == "__main__":
    unittest.main()
