import importlib.util
from pathlib import Path
import tempfile
import tomllib
import unittest


SPEC = importlib.util.spec_from_file_location("vendor_runner", Path(__file__).with_name("run_hepta_vendor_compatibility.py"))
RUNNER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNNER)


class VendorRunnerIntegrity(unittest.TestCase):
    def test_copy_verification_detects_modified_and_missing_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, copied = root / "source", root / "copied"
            source.mkdir()
            copied.mkdir()
            (source / "lib.rs").write_bytes(b"original source\n")
            (copied / "lib.rs").write_bytes(b"original source\n")
            self.assertEqual(len(RUNNER.verify_identity(source, copied)), 1)
            (copied / "lib.rs").write_bytes(b"changed source\n")
            with self.assertRaises(ValueError):
                RUNNER.verify_identity(source, copied)
            (copied / "lib.rs").unlink()
            with self.assertRaises(ValueError):
                RUNNER.verify_identity(source, copied)

    def test_junit_requires_exact_names_and_no_skips_or_failures(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "junit.xml"
            path.write_text('<testsuites><testsuite><testcase name="exact"/></testsuite></testsuites>')
            self.assertEqual(RUNNER.validate_junit(path, ["exact"])["passed"], 1)
            with self.assertRaises(ValueError):
                RUNNER.validate_junit(path, ["different"])
            for failure in ["skipped", "failure", "error"]:
                path.write_text(f'<testsuite><testcase name="exact"><{failure}/></testcase></testsuite>')
                with self.assertRaises(ValueError):
                    RUNNER.validate_junit(path, ["exact"])

    def test_preparation_copies_sources_and_keeps_manifests_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo, work, output = root / "repo", root / "work", root / "output"
            output.mkdir()
            for name, vendor in RUNNER.VENDORS.items():
                source = repo / "codex-rs/third_party" / vendor
                source.mkdir(parents=True)
                (source / "Cargo.toml").write_text(f'[package]\nname = "{name}"\nversion = "0.0.1"\n')
                (source / "HEPTA_SOURCE.json").write_text('{}\n')
                (source / "lib.rs").write_text(f'// {name} source\n')
            (repo / "codex-rs/Cargo.lock").write_text('# seed lock\n')
            records = RUNNER.prepare_workspace(repo, work, output)
            manifest = tomllib.loads((work / "Cargo.toml").read_text())
            self.assertEqual(set(records), set(RUNNER.VENDORS))
            for name, patch in manifest["patch"]["crates-io"].items():
                copied = work / patch["path"]
                self.assertEqual(tomllib.loads((copied / "Cargo.toml").read_text())["package"]["name"], name)
                self.assertEqual(records[name]["source_manifest_sha256"], records[name]["copied_manifest_sha256"])
            self.assertEqual((work / "Cargo.lock").read_bytes(), (repo / "codex-rs/Cargo.lock").read_bytes())
            with self.assertRaises(ValueError):
                RUNNER.prepare_workspace(repo, work, output)


if __name__ == "__main__":
    unittest.main()
