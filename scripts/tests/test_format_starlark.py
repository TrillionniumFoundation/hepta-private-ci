"""Exercise formatter selection with Git inventories and the pinned buildifier."""

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
        custody = (
            *self.original.VERBATIM_FIXTURES,
            *self.original.ORIGINAL_EVIDENCE_FILES,
            *self.original.retained_rust.INVENTORY["archived"],
            *self.original.retained_rust.INVENTORY["companions"],
            "scripts/hepta_retained_rust.py",
            "scripts/format_provenance/retained_rust.json",
        )
        for relative in ("scripts/format.py", "tools/buildifier", *custody, *EVIDENCE):
            destination = self.root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / relative, destination)
        self.formatter = load_formatter(
            self.root / "scripts/format.py", "format_subject"
        )
        self.addCleanup(sys.modules.pop, "format_subject", None)
        self.sources = ("BUILD.bazel", "nested sources/rules.bzl")
        for relative in self.sources:
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"result=struct(values=[1,2])\n")
        self.metadata = {
            relative: (self.root / relative).read_bytes() for relative in EVIDENCE
        }
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
        for check in (False, True):
            self.assertEqual(
                self.formatter.scoped_formatter_groups(
                    list(self.metadata), check=check
                ),
                (),
            )


if __name__ == "__main__":
    unittest.main()
