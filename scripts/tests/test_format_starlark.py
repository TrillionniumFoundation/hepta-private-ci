"""Exercise formatter selection with Git inventories and the pinned buildifier."""

import hashlib
import importlib.util
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = (
    "qualification/hcsn_currentstate_n256_corrected_t0_capsule_v1/"
    "evidence/attempt002_hosted/BUILD.json",
    "qualification/hcsn_currentstate_n256_corrected_t0_capsule_v1/"
    "evidence/precommit_attempt001/BUILD.json",
)


def load_formatter(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class StarlarkSelectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original = load_formatter(ROOT / "scripts/format.py", "format_original")
        # This is an integration test: absence of the installed formatter fails.
        # The CI setup action installs DotSlash; its wrapper verifies the binary.
        subprocess.run(
            ["dotslash", str(ROOT / "tools/buildifier"), "-version"],
            check=True,
            capture_output=True,
            text=True,
        )

    @classmethod
    def tearDownClass(cls):
        sys.modules.pop("format_original", None)

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="hepta-starlark-format-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        for relative in ("scripts/format.py", "tools/buildifier", *EVIDENCE):
            destination = self.root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / relative, destination)
        self.formatter = load_formatter(
            self.root / "scripts/format.py", "format_subject"
        )
        self.addCleanup(sys.modules.pop, "format_subject", None)
        # Test the real byte guards against a task-owned fixture instead of
        # duplicating unrelated historical records in this temporary repository.
        self.formatter.VERBATIM_FIXTURES = {}
        self.archived_source = self.formatter.ORIGINAL_EVIDENCE_PREFIX + "/example.bzl"
        original = b"archived=struct(values=[1,2])\n"
        archived_path = self.root / self.archived_source
        archived_path.parent.mkdir(parents=True, exist_ok=True)
        archived_path.write_bytes(original)
        self.formatter.ORIGINAL_EVIDENCE_FILES = {
            self.archived_source: (hashlib.sha256(original).hexdigest(), len(original))
        }
        self.sources = ("BUILD.bazel", "nested sources/rules.bzl")
        for relative in self.sources:
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"result=struct(values=[1,2])\n")
        self.metadata = {
            relative: (self.root / relative).read_bytes() for relative in EVIDENCE
        }
        self.metadata[self.archived_source] = original
        for relative in ("WORKSPACE.json", "MODULE.bazel.json", "rules.bzl.json"):
            self.metadata[relative] = b'{ "immutable":true,"values":[1, 2] }\n'
            (self.root / relative).write_bytes(self.metadata[relative])
        subprocess.run(["git", "init", "--quiet", str(self.root)], check=True)
        # Keep one source and one evidence file untracked: full formatting must
        # select from both inventories without changing either metadata record.
        subprocess.run(
            ["git", "add", "--", self.sources[0], EVIDENCE[0]],
            cwd=self.root,
            check=True,
        )

    def exercise(self, *, scoped):
        def groups(check):
            if scoped:
                return self.formatter.scoped_formatter_groups(
                    [*self.sources, *self.metadata], check=check
                )
            return (self.formatter.buildifier_formatter_group(check=check),)

        initial = {
            relative: (self.root / relative).read_bytes() for relative in self.sources
        }
        checked = [self.formatter.run_formatter_group(group) for group in groups(True)]
        self.assertEqual(len(checked), 1)
        self.assertNotEqual(checked[0].returncode, 0, checked[0].output)
        for group in groups(False):
            result = self.formatter.run_formatter_group(group)
            self.assertEqual(result.returncode, 0, result.output)
        for relative, before in initial.items():
            self.assertNotEqual((self.root / relative).read_bytes(), before, relative)
        self.assertEqual(
            {
                relative: (self.root / relative).read_bytes()
                for relative in self.metadata
            },
            self.metadata,
        )
        self.assertEqual(
            {relative: (ROOT / relative).read_bytes() for relative in EVIDENCE},
            {relative: self.metadata[relative] for relative in EVIDENCE},
        )
        for group in groups(True):
            result = self.formatter.run_formatter_group(group)
            self.assertEqual(result.returncode, 0, result.output)

    def test_full_git_inventory_formats_sources_and_preserves_execution_records(self):
        self.exercise(scoped=False)

    def test_scoped_formatting_formats_sources_and_preserves_execution_records(self):
        self.exercise(scoped=True)

    def test_metadata_only_scope_does_not_dispatch_a_formatter(self):
        metadata = [path for path in self.metadata if path != self.archived_source]
        for check in (False, True):
            self.assertEqual(
                self.formatter.scoped_formatter_groups(metadata, check=check),
                (),
            )


if __name__ == "__main__":
    unittest.main()
