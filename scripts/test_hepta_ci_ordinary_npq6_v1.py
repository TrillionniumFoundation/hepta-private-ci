#!/usr/bin/env python3
"""Pure Python evidence-reader controls; no Rust, binary, service or paired run."""

import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest

import hepta_ci_ordinary_npq6_support_v1 as subject


class OrdinaryNpq6RunnerMechanisms(unittest.TestCase):
    def test_exact_registry_refuses_missing_duplicate_extra_and_non_test_rows(self):
        required = (*subject.CHAIN_CASES, subject.EXPORT)
        good = "\n".join(name + ": test" for name in required)
        self.assertEqual(subject.exact_registry(good, required), list(required))
        for bad in (
            good.replace(required[0] + ": test", "", 1),
            good + "\n" + required[0] + ": test",
            good + "\nextra::unreviewed: test",
            good.replace(required[0] + ": test", required[0] + ": benchmark"),
        ):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                subject.exact_registry(bad, required)

    def test_actual_compiler_artifact_requires_exact_target_kind_profile_and_unique_file(
        self,
    ):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            executable = root / "actual-node"
            executable.write_bytes(b"retained test data, never executed")
            other = root / "other-node"
            other.write_bytes(b"another unexecuted file")
            log = root / "build.log"
            row = {
                "reason": "compiler-artifact",
                "target": {"name": "node", "kind": ["bin"]},
                "profile": {"test": False},
                "executable": str(executable),
            }
            log.write_text("compiler diagnostic\n" + json.dumps(row) + "\n")
            self.assertEqual(subject.artifact(log, "node", "bin", False), executable)
            for field, value in (
                ("reason", "build-finished"),
                ("target", {"name": "node", "kind": ["test"]}),
                ("profile", {"test": True}),
                ("executable", None),
            ):
                bad = dict(row)
                bad[field] = value
                log.write_text(json.dumps(bad) + "\n")
                with self.subTest(field=field), self.assertRaises(ValueError):
                    subject.artifact(log, "node", "bin", False)
            duplicate = dict(row)
            duplicate["executable"] = str(other)
            log.write_text(json.dumps(row) + "\n" + json.dumps(duplicate) + "\n")
            with self.assertRaises(ValueError):
                subject.artifact(log, "node", "bin", False)

    def test_exact_pass_reader_refuses_missing_duplicate_extra_or_failed_terminal(self):
        with tempfile.TemporaryDirectory() as temporary:
            log = Path(temporary) / "run.log"
            good = "test actual::a ... ok\ntest actual::b ... ok\n"
            terminal = "test result: ok. 2 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out;\n"
            log.write_text(good + terminal)
            subject.passed_names(log, ("actual::a", "actual::b"))
            for bad in (
                good.replace("test actual::b ... ok\n", "") + terminal,
                good + "test actual::a ... ok\n" + terminal,
                good + "test different::case ... ok\n" + terminal,
                good + terminal.replace("0 failed", "1 failed"),
            ):
                log.write_text(bad)
                with self.subTest(bad=bad), self.assertRaises(ValueError):
                    subject.passed_names(log, ("actual::a", "actual::b"))

    def test_each_case_environment_restores_original_values_even_after_failure(self):
        keys = ("HEPTA_PON_NPQ6_FIXTURE_OUT", "HEPTA_PON_NPQ6_MATERIAL_SHA256")
        old = {key: os.environ.get(key) for key in keys}
        try:
            os.environ[keys[0]] = "/original"
            os.environ.pop(keys[1], None)
            for index in range(3):
                with self.assertRaisesRegex(ValueError, "fixture failure"):
                    with subject.environment(
                        {keys[0]: f"/case-{index}", keys[1]: str(index)}
                    ):
                        self.assertEqual(os.environ[keys[0]], f"/case-{index}")
                        self.assertEqual(os.environ[keys[1]], str(index))
                        raise ValueError("fixture failure")
                self.assertEqual(os.environ[keys[0]], "/original")
                self.assertNotIn(keys[1], os.environ)
        finally:
            for key, value in old.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    def test_retention_copies_cargo_hardlink_to_new_single_link_without_executing_it(
        self,
    ):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "cargo-artifact"
            raw = b"unexecuted compiler artifact fixture"
            source.write_bytes(raw)
            os.link(source, root / "cargo-alias")
            output = root / "retained"
            output.mkdir()
            row = subject.retain(output, source, "node")
            self.assertEqual(row["sha256"], hashlib.sha256(raw).hexdigest())
            self.assertEqual((output / "node").stat().st_nlink, 1)
            self.assertNotEqual((output / "node").stat().st_ino, source.stat().st_ino)
            with self.assertRaises(ValueError):
                subject.retain(output, source, "node")

    def test_hash_refuses_symlink_fifo_and_unapproved_hardlink_without_opening_special_file(
        self,
    ):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "regular"
            source.write_bytes(b"bounded fixture")
            symlink = root / "symlink"
            symlink.symlink_to(source)
            fifo = root / "fifo"
            os.mkfifo(fifo)
            for path in (symlink, fifo):
                with self.subTest(path=path), self.assertRaises(ValueError):
                    subject.digest_file(path)
            os.link(source, root / "hardlink")
            with self.assertRaises(ValueError):
                subject.digest_file(source)
            self.assertEqual(
                subject.digest_file(source, single_link=False)["bytes"],
                len(b"bounded fixture"),
            )


if __name__ == "__main__":
    unittest.main()
