"""Adversarial tests of artifact parsing; synthetic fixtures are not execution evidence."""

from __future__ import annotations

import copy
import io
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
import zipfile

import hepta_inference_artifact_acceptor as accept

SOURCE = "a" * 40
BASE = "b" * 40
TESTED = "c" * 40


def source_archive():
    payload = b"fixture bytes, not executable code\n"
    buffer = io.BytesIO()
    with tarfile.open(
        fileobj=buffer,
        mode="w:gz",
        format=tarfile.PAX_FORMAT,
        pax_headers={"comment": TESTED},
    ) as archive:
        member = tarfile.TarInfo("source.txt")
        member.size, member.mode = len(payload), 0o644
        archive.addfile(member, io.BytesIO(payload))
    blob = accept.object_id("blob", payload)
    tree = accept.object_id("tree", b"100644 source.txt\0" + bytes.fromhex(blob))
    return buffer.getvalue(), tree


class AcceptorTests(unittest.TestCase):
    def setUp(self):
        archive, tree = source_archive()
        self.identities = dict(
            lane="base-merge",
            source=SOURCE,
            base=BASE,
            tested=TESTED,
            tree=tree,
            run_id="7",
            attempt="1",
        )
        self.files = {
            "source-input.tar.gz": archive,
            "toolchain.txt": b"rustc 1.95.0\ncargo 1.95.0\nimage_os=ubuntu24\nimage_version=fixture\nworkflow_sha=fixture\n",
        }
        for name, command in accept.EXPECTED.items():
            log = b"fixture log, not execution proof\n"
            snapshot = {
                "commit": TESTED,
                "tree": tree,
                "parents": [BASE, SOURCE],
                "dirty": False,
            }
            record = {
                "schema_version": 1,
                "command": command,
                "source_sha": SOURCE,
                "base_sha": BASE,
                "tested_sha": TESTED,
                "lane": "base-merge",
                "run_id": "7",
                "run_attempt": "1",
                "status": "passed",
                "exit_code": 0,
                "returncode": 0,
                "command_exit_code": 0,
                "timed_out": False,
                "output_limit_exceeded": False,
                "observed_passed_tests": 1,
                "observed_failed_tests": 0,
                "before": snapshot,
                "after": snapshot,
                "started_at": "2026-09-28T00:00:00+00:00",
                "finished_at": "2026-09-28T00:00:01+00:00",
                "elapsed_seconds": 1.0,
                "log_file": name + ".log",
                "log_bytes": len(log),
                "log_sha256": accept.sha256(log),
            }
            self.files["commands/" + name + ".json"] = json.dumps(record).encode()
            self.files["commands/" + name + ".log"] = log

    def validate(self, files=None):
        return accept.validate_bundle(
            files if files is not None else self.files, **self.identities
        )

    def modify(self, **changes):
        key = "commands/07-tests.json"
        value = json.loads(self.files[key])
        value.update(changes)
        self.files[key] = json.dumps(value).encode()

    def test_complete_synthetic_bundle_only_proves_integrity(self):
        result = self.validate()
        self.assertTrue(result["artifactIntegrityVerified"])
        for key in (
            "independentExecutionProved",
            "independentAcceptance",
            "activation",
            "release",
        ):
            self.assertFalse(result[key])
        self.assertEqual(len(result["commands"]), 12)

    def test_recorded_failure_and_boolean_zero_are_rejected(self):
        for value in (1, False, "0", None):
            self.modify(exit_code=value)
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.validate()

    def test_missing_and_extra_command_records_are_rejected(self):
        del self.files["commands/08-crash.json"]
        with self.assertRaisesRegex(ValueError, "inventory"):
            self.validate()
        self.files["commands/unknown.json"] = b"{}"
        with self.assertRaisesRegex(ValueError, "inventory"):
            self.validate()

    def test_successful_non_test_helper_build_is_required(self):
        key = "commands/06a-worker-helper-build.json"
        record = json.loads(self.files[key])
        record["observed_passed_tests"] = 0
        self.files[key] = json.dumps(record).encode()
        self.assertTrue(self.validate()["artifactIntegrityVerified"])
        del self.files[key]
        with self.assertRaisesRegex(ValueError, "inventory"):
            self.validate()
        record.update(status="failed", exit_code=1, returncode=1, command_exit_code=1)
        self.files[key] = json.dumps(record).encode()
        with self.assertRaises(ValueError):
            self.validate()

    def test_command_substitution_is_rejected(self):
        self.modify(command=["echo", "cargo test passed"])
        with self.assertRaisesRegex(ValueError, "command/schema"):
            self.validate()

    def test_log_tampering_is_rejected(self):
        self.files["commands/07-tests.log"] = b"forged log"
        with self.assertRaisesRegex(ValueError, "log size|log digest"):
            self.validate()

    def test_wrong_source_run_or_merge_parents_are_rejected(self):
        for changes in (
            {"source_sha": "d" * 40},
            {"run_id": "8"},
            {
                "after": {
                    "commit": TESTED,
                    "tree": self.identities["tree"],
                    "dirty": False,
                    "parents": [SOURCE, BASE],
                }
            },
        ):
            original = self.files["commands/07-tests.json"]
            self.modify(**changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.validate()
            self.files["commands/07-tests.json"] = original

    def test_zero_tests_or_incomplete_execution_is_rejected(self):
        for changes in (
            {"observed_passed_tests": 0},
            {"timed_out": True},
            {"output_limit_exceeded": True},
            {"status": "skipped"},
        ):
            original = self.files["commands/07-tests.json"]
            self.modify(**changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.validate()
            self.files["commands/07-tests.json"] = original

    def test_duplicate_json_keys_are_rejected(self):
        self.files["commands/07-tests.json"] = (
            b'{"schema_version":1,"schema_version":1}'
        )
        with self.assertRaisesRegex(ValueError, "duplicate JSON"):
            self.validate()

    def test_log_path_escape_is_rejected(self):
        self.modify(log_file="../../outside")
        with self.assertRaisesRegex(ValueError, "log name"):
            self.validate()

    def test_source_archive_tree_is_recomputed(self):
        self.identities["tree"] = "e" * 40
        with self.assertRaisesRegex(ValueError, "archive tree"):
            self.validate()

    def test_tar_links_and_paths_are_never_extracted(self):
        for name, kind in (
            ("../escape", tarfile.REGTYPE),
            ("device", tarfile.CHRTYPE),
            ("hardlink", tarfile.LNKTYPE),
        ):
            buffer = io.BytesIO()
            with tarfile.open(
                fileobj=buffer,
                mode="w:gz",
                format=tarfile.PAX_FORMAT,
                pax_headers={"comment": TESTED},
            ) as archive:
                member = tarfile.TarInfo(name)
                member.type = kind
                archive.addfile(member)
            with self.subTest(name=name), self.assertRaises(ValueError):
                accept.git_tree_from_archive(buffer.getvalue(), TESTED)

    def test_zip_digest_and_path_escape_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "artifact.zip"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("../escape", b"bad")
            with self.assertRaisesRegex(ValueError, "digest"):
                accept.read_zip(path, "0" * 64)
            with self.assertRaisesRegex(ValueError, "escape"):
                accept.read_zip(path, accept.sha256(path.read_bytes()))

    def test_real_git_archive_tree_agrees_including_modes_and_symlinks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            def git(*args):
                return subprocess.check_output(["git", "-C", directory, *args]).strip()

            git("init", "-q")
            git("config", "user.name", "fixture")
            git("config", "user.email", "fixture@example.invalid")
            (root / "a").mkdir()
            (root / "a" / "script").write_text("not executed\n")
            (root / "a" / "script").chmod(0o755)
            (root / "a.txt").write_text("sort before a-directory\n")
            (root / "link").symlink_to("a/script")
            git("add", ".")
            git("-c", "commit.gpgsign=false", "commit", "-qm", "fixture")
            commit = git("rev-parse", "HEAD").decode()
            tree = git("rev-parse", "HEAD^{tree}").decode()
            archive = subprocess.check_output(
                ["git", "-C", directory, "archive", "--format=tar.gz", "HEAD"]
            )
            self.assertEqual(accept.git_tree_from_archive(archive, commit), tree)


if __name__ == "__main__":
    unittest.main()
