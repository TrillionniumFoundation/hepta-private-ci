"""Executable verifier regressions. Fixtures are not signed deployment evidence."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "verify-deployment-evidence.py"
spec = importlib.util.spec_from_file_location("browser_evidence", SCRIPT)
verifier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verifier)


class EvidenceRuntimeTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.addCleanup(self.temporary.cleanup)

    def test_regular_file_is_accepted_at_exact_limit(self):
        path = self.root / "receipt"
        path.write_bytes(b"1234")
        self.assertEqual(verifier.require_file(path, 4), path)

    def test_empty_and_oversized_files_rejected(self):
        path = self.root / "receipt"
        for value in (b"", b"12345"):
            with self.subTest(value=value):
                path.write_bytes(value)
                with self.assertRaises(SystemExit):
                    verifier.require_file(path, 4)

    def test_directory_missing_symlink_and_fifo_rejected(self):
        regular = self.root / "regular"
        regular.write_bytes(b"ok")
        link = self.root / "link"
        link.symlink_to(regular)
        fifo = self.root / "fifo"
        os.mkfifo(fifo)
        for path in (self.root, self.root / "missing", link, fifo):
            with self.subTest(path=path), self.assertRaises(SystemExit):
                verifier.require_file(path)

    def test_invalid_capacity_rejected(self):
        for limit in (0, -1, True, "4", 4.0):
            with self.subTest(limit=limit), self.assertRaises(SystemExit):
                verifier.require_file(self.root, limit)

    def test_duplicate_json_keys_and_nonfinite_numbers_rejected(self):
        path = self.root / "receipt.json"
        for value in ('{"ok":false,"ok":true}', '{"outer":{"a":1,"a":2}}',
                      '{"n":NaN}', '{"n":Infinity}', '{"n":-Infinity}'):
            path.write_text(value)
            with self.subTest(value=value), self.assertRaises(SystemExit):
                verifier.load_json(path)

    def test_valid_json_and_utf8_failure(self):
        path = self.root / "receipt.json"
        path.write_text('{"observed":true,"count":2}')
        self.assertEqual(verifier.load_json(path), {"observed": True, "count": 2})
        path.write_bytes(b"\xff")
        with self.assertRaises(SystemExit):
            verifier.load_json(path)

    def test_json_types_cannot_substitute_for_flags_or_counts(self):
        for actual, wanted in ((1, True), (True, 1), (0, False), (2.0, 2), ("2", 2)):
            with self.subTest(actual=actual, wanted=wanted), self.assertRaises(SystemExit):
                verifier.require_fields({"field": actual}, {"field": wanted}, "receipt")
        verifier.require_fields({"count": 2, "pass": True}, {"count": 2, "pass": True}, "receipt")

    def test_pending_and_wrong_workflow_runs_rejected(self):
        run = {"id": 1, "head_sha": "a" * 40, "head_branch": "main",
               "name": "primary", "path": "workflow.yml", "conclusion": "success",
               "status": "completed", "event": "push",
               "repository": {"full_name": verifier.REPOSITORY}}
        options = dict(run_id="1", source_sha="a" * 40, name="primary", path="workflow.yml")
        verifier.verify_run(run, **options)
        for field, value in (("status", "queued"), ("conclusion", "cancelled"),
                             ("id", True), ("head_sha", "b" * 40),
                             ("head_branch", "candidate"), ("event", "pull_request")):
            with self.subTest(field=field), self.assertRaises(SystemExit):
                verifier.verify_run({**run, field: value}, **options)

    def test_aliased_run_identifiers_rejected(self):
        self.assertEqual(verifier.require_run_id("123"), "123")
        for value in ("0", "01", "+1", "-1", "1.0", "１", "", " 1"):
            with self.subTest(value=value), self.assertRaises(SystemExit):
                verifier.require_run_id(value)

    def test_exact_committed_lock_is_compared_to_builder_bytes(self):
        def git(*args):
            return subprocess.check_output(["git", *args], cwd=self.root, text=True).strip()
        git("init", "-q")
        git("config", "user.name", "Browser fixture")
        git("config", "user.email", "fixture@example.invalid")
        path = self.root / "apps/hepta-browser/servo-worker/Cargo.lock"
        path.parent.mkdir(parents=True)
        path.write_text("# exact source lock fixture\nversion = 4\n")
        git("add", ".")
        git("commit", "-qm", "fixture")
        head = git("rev-parse", "HEAD")
        artifact = self.root / "builder.lock"
        artifact.write_bytes(path.read_bytes())
        original = os.getcwd()
        try:
            os.chdir(self.root)
            verifier.verify_source_lock(head, artifact)
            artifact.write_text("# a different builder lock\n")
            with self.assertRaises(SystemExit):
                verifier.verify_source_lock(head, artifact)
            with self.assertRaises(SystemExit):
                verifier.verify_source_lock("b" * 40, artifact)
        finally:
            os.chdir(original)

    def test_finalize_cannot_relabel_old_successful_receipts(self):
        target = self.root / "deployment-evidence"
        target.mkdir()
        names = ("multi-builder-receipt", "signed-attestation-verification", "linux-sandbox-probe",
                 "real-worker-smoke", "real-browser-e2e", "public-egress-probe", "real-browser-soak")
        for name in names:
            (target / f"{name}.json").write_text('{}')
        multi = {"schema": "hepta.browser.servo-multi-builder-receipt.v1",
                 "sourceSha": "b" * 40, "sourceTree": "c" * 40, "workerSha256": "d" * 64,
                 "servoPin": "e" * 40, "primaryBuildRunId": "1", "independentBuildRunId": "2",
                 "independentRunnerBuildCount": 2, "reproducibleIndependentBuilds": True,
                 "byteIdentical": True}
        (target / "multi-builder-receipt.json").write_text(json.dumps(multi))
        env = {"SOURCE_SHA": "a" * 40, "EXPECTED_WORKER_SHA256": "d" * 64,
               "SERVO_PIN": "e" * 40, "BUILD_RUN_ID": "1", "INDEPENDENT_BUILD_RUN_ID": "2"}
        original = os.getcwd()
        try:
            os.chdir(self.root)
            with patch.dict(os.environ, env), patch.object(verifier, "git_tree", return_value="c" * 40):
                with self.assertRaisesRegex(SystemExit, "multiBuilder.sourceSha mismatch"):
                    verifier.finalize()
            self.assertFalse((target / "target-qualification-receipt.json").exists())
        finally:
            os.chdir(original)


if __name__ == "__main__":
    unittest.main(verbosity=2)
