"""Stdlib-only transport and owned-process tests; no provider or model calls."""
from contextlib import contextmanager
from dataclasses import asdict, dataclass
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from qualification.hcsn_regenerative.colab_qualification_v4 import asset_transport as a
from qualification.hcsn_regenerative.colab_qualification_v4.qualification_runner import ChildScope, semantic_check


@dataclass
class FakeProfile:
    endpoint: str = "offline-endpoint"
    kernel_id: str = "offline-kernel"
    session_id: str = "offline-session"
    remote_root: str = "/content/offline-assets"
    max_artifact_bytes: int = 33554432

    @property
    def fingerprint(self):
        return a.sha(a.canonical(asdict(self)))


class FakeLedger:
    def __init__(self, root, profile):
        self.root, self.path = root, root / "jobs.sqlite3"
        root.mkdir()
        with self.connection() as db:
            db.execute("CREATE TABLE jobs(job_id TEXT, endpoint TEXT, kernel_id TEXT, session_id TEXT, remote_dir TEXT, state TEXT, code_sha256 TEXT, payload_sha256 TEXT, profile TEXT, receipt TEXT)")
            db.execute("INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?,?)", (
                "anchor", profile.endpoint, profile.kernel_id, profile.session_id,
                profile.remote_root + "/anchor", "succeeded", "a" * 64, "b" * 64,
                json.dumps(asdict(profile)), json.dumps(dict(cloud_execution_stopped=True,
                cloud_process_group_alive=False))))

    def connection(self):
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        return db

    @staticmethod
    def decoded(row):
        value = dict(row)
        for key in ("profile", "receipt"):
            value[key] = json.loads(value[key])
        return value


class FakeProvider:
    def __init__(self):
        self.profile, self.files, self.puts = FakeProfile(), {}, []
        self.contents, self.mode = self, "normal"

    def list_dir(self, path):
        if self.mode == "list-unknown":
            raise TimeoutError("sensitive dummy message must not survive")
        return dict(type="directory", path=path)

    def read_bytes(self, path):
        if path not in self.files:
            raise FileNotFoundError(path)
        return self.files[path]

    def write_bytes(self, path, raw):
        if len(raw) > 65536:
            raise AssertionError("Fixture exceeded bounded SDK input")
        self.puts.append((path, raw))
        if self.mode != "lost-before-effect":
            self.files[path] = raw
        if self.mode in ("lost-before-effect", "lost-after-effect"):
            raise TimeoutError("sensitive dummy message must not survive")


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="hcsn-assets-offline-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.data = self.root / "input.bin"
        self.data.write_bytes(os.urandom(135000))
        self.entry = self.root / "entry.py"
        self.entry.write_text("raise SystemExit(0)\n")
        self.helper = Path(a.__file__)
        self.provider = FakeProvider()
        self.ledger = FakeLedger(self.root / "ledger", self.provider.profile)
        self.prepared = a.prepare_archive({"input.bin": self.data, "entry.py": self.entry,
            a.PUBLIC_PATH: self.helper}, self.root / "assets", "offline-assets-01",
            self.provider.profile.remote_root)
        self.raw = Path(self.prepared["manifest_path"]).read_bytes()
        self.manifest = self.prepared["manifest"]

    def stage(self, **kwargs):
        return a.stage_assets(self.provider, self.raw, a.sha(self.raw), self.prepared["parts_dir"],
            self.root / "upload.json", self.provider.profile.fingerprint,
            adapter_ledger=self.ledger, expected_ledger_root=self.ledger.root,
            anchor_job_id="anchor", **kwargs)

    def fill_remote(self):
        for part in self.manifest["parts"]:
            self.provider.files[part["remote_path"]] = (Path(self.prepared["parts_dir"]) / part["local_name"]).read_bytes()

    @contextmanager
    def remote_reads(self):
        original = a.regular_bytes
        def read(path, limit=a.MAX_ARCHIVE):
            path = str(path)
            return self.provider.read_bytes(path) if path.startswith("/content/") else original(path, limit)
        with patch.object(a, "regular_bytes", side_effect=read):
            yield

    def test_exact_materialization_and_exclusive_destination(self):
        self.fill_remote()
        with self.remote_reads():
            result = a.materialize_assets(self.raw, a.sha(self.raw), self.root / "output")
            self.assertEqual(result["status"], "VERIFIED")
            self.assertEqual((self.root / "output/input.bin").read_bytes(), self.data.read_bytes())
            with self.assertRaises(FileExistsError):
                a.materialize_assets(self.raw, a.sha(self.raw), self.root / "output")
        self.assertEqual(result["network_operations"], 0)

    def test_corrupt_part_cannot_write_destination(self):
        self.fill_remote()
        path = self.manifest["parts"][0]["remote_path"]
        self.provider.files[path] = b"corrupt"
        with self.remote_reads(), self.assertRaises(a.AssetError):
            a.materialize_assets(self.raw, a.sha(self.raw), self.root / "output")
        self.assertFalse((self.root / "output").exists())

    def test_missing_part_cannot_write_destination(self):
        self.fill_remote()
        self.provider.files.pop(self.manifest["parts"][-1]["remote_path"])
        with self.remote_reads(), self.assertRaises(FileNotFoundError):
            a.materialize_assets(self.raw, a.sha(self.raw), self.root / "output")
        self.assertFalse((self.root / "output").exists())

    def test_manifest_traversal_and_reordered_parts_rejected(self):
        for change in ("traversal", "parts", "prefix"):
            manifest = json.loads(self.raw)
            if change == "traversal":
                manifest["files"]["../escape"] = dict(bytes=0, sha256=a.sha(b""))
            elif change == "prefix":
                manifest["files"]["input.bin/child"] = dict(bytes=0, sha256=a.sha(b""))
            else:
                manifest["parts"].reverse()
            raw = a.canonical(manifest)
            with self.subTest(change=change), self.assertRaises(a.AssetError):
                a.validate_manifest(raw, a.sha(raw))

    def test_duplicate_json_and_source_hash_rejected(self):
        with self.assertRaises(a.AssetError):
            a._json(b'{"a":1,"a":2}')
        with self.assertRaises(a.AssetError):
            a.validate_manifest(self.raw, "0" * 64)

    def test_manifest_and_archive_size_bounds(self):
        with self.assertRaises(a.AssetError):
            a.prepare_archive({"input.bin": self.data}, self.root / "too-small", "tiny", "/content/offline", 100)
        self.assertFalse((self.root / "too-small").exists())
        self.assertTrue(all(p["bytes"] <= 65536 for p in self.manifest["parts"]))

    def test_successful_upload_exact_readback_and_no_repeated_put(self):
        result = self.stage()
        self.assertEqual(result["status"], "VERIFIED")
        count = len(self.provider.puts)
        self.assertEqual(count, len(self.manifest["parts"]))
        self.assertEqual(self.stage(reconcile_only=True)["status"], "VERIFIED")
        self.assertEqual(len(self.provider.puts), count)

    def test_put_effect_then_lost_response_resolves_exact_get(self):
        self.provider.mode = "lost-after-effect"
        result = self.stage()
        self.assertEqual(result["status"], "VERIFIED")
        self.assertTrue(all(r["verified_after_uncertain_put"] for r in result["parts"]))
        self.assertEqual(len(self.provider.puts), len(self.manifest["parts"]))
        self.assertNotIn("sensitive dummy", json.dumps(result))

    def test_unknown_put_never_replayed_or_released(self):
        self.provider.mode = "lost-before-effect"
        self.assertEqual(self.stage()["status"], "UNKNOWN")
        self.assertEqual(len(self.provider.puts), 1)
        with self.assertRaisesRegex(a.AssetError, "READONLY_RECONCILIATION"):
            self.stage()
        self.assertEqual(self.stage(reconcile_only=True)["status"], "UNKNOWN")
        self.assertEqual(len(self.provider.puts), 1)

    def test_identical_preexisting_remote_path_is_not_adopted(self):
        self.fill_remote()
        with self.assertRaisesRegex(a.AssetError, "PREEXISTING_REMOTE_PATH"):
            self.stage()
        self.assertEqual(self.provider.puts, [])
        with self.assertRaisesRegex(a.AssetError, "PRIOR_UPLOAD_CONFLICT"):
            self.stage(reconcile_only=True)

    def test_unknown_same_kernel_blocks_before_transport(self):
        with self.ledger.connection() as db:
            db.execute("UPDATE jobs SET state='unknown'")
        with self.assertRaisesRegex(a.AssetError, "BUSY_OR_UNKNOWN"):
            self.stage()
        self.assertFalse((self.root / "upload.json").exists())
        self.assertEqual(self.provider.puts, [])

    def test_wrong_ledger_and_unstopped_anchor_rejected(self):
        with self.assertRaisesRegex(a.AssetError, "AUTHORITATIVE_LEDGER_PATH"):
            a.stage_assets(self.provider, self.raw, a.sha(self.raw), self.prepared["parts_dir"],
                self.root / "upload.json", self.provider.profile.fingerprint,
                adapter_ledger=self.ledger, expected_ledger_root=self.root / "different", anchor_job_id="anchor")
        with self.ledger.connection() as db:
            db.execute("UPDATE jobs SET receipt=?", (json.dumps(dict(cloud_execution_stopped=False)),))
        with self.assertRaisesRegex(a.AssetError, "ANCHOR_NOT_STOPPED_SUCCESS"):
            self.stage()
        self.assertEqual(self.provider.puts, [])

    def test_parent_unknown_is_recorded_without_put(self):
        self.provider.mode = "list-unknown"
        result = self.stage()
        self.assertEqual(result["status"], "UNKNOWN")
        self.assertEqual(self.provider.puts, [])
        self.assertNotIn("sensitive dummy", json.dumps(result))

    def test_launcher_compiles_and_rejects_code_overflow(self):
        result = a.make_launcher(self.raw, a.sha(self.raw), "materialized", "entry.py", self.helper.read_bytes())
        self.assertLessEqual(result["code_bytes"], 262144)
        compile(result["source_text"], "<offline-launcher>", "exec")
        with self.assertRaisesRegex(a.AssetError, "LAUNCHER_CODE_LIMIT"):
            a.make_launcher(self.raw, a.sha(self.raw), "materialized", "entry.py",
                            self.helper.read_bytes(), argv=["x" * 270000])
        with self.assertRaisesRegex(a.AssetError, "SOURCE_NOT_PINNED"):
            a.make_launcher(self.raw, a.sha(self.raw), "materialized", "entry.py", b"changed")

    def test_explicit_prefixed_helper_never_uses_implicit_alias(self):
        logical = "source/" + a.PUBLIC_PATH
        prepared = a.prepare_archive({logical: self.helper, "bootstrap_entry.py": self.entry},
            self.root / "prefixed", "offline-prefixed-01", self.provider.profile.remote_root)
        raw = Path(prepared["manifest_path"]).read_bytes()
        with self.assertRaisesRegex(a.AssetError, "SOURCE_NOT_PINNED"):
            a.make_launcher(raw, a.sha(raw), "prefixed", "bootstrap_entry.py", self.helper.read_bytes())
        launcher = a.make_launcher(raw, a.sha(raw), "prefixed", "bootstrap_entry.py",
            self.helper.read_bytes(), transport_logical=logical)
        self.assertIn(logical, launcher["source_text"])
        with self.assertRaisesRegex(a.AssetError, "SOURCE_NOT_PINNED"):
            a.make_launcher(raw, a.sha(raw), "prefixed", "bootstrap_entry.py", b"changed",
                            transport_logical=logical)

    def test_budget_gate_retains_original_strict_450_seconds(self):
        stage = dict(name="mechanism-nontask-budget-cuda", result_json="budget.json",
                     accepted_statuses=["completed"])
        for wall, expected in [(449.999, True), (450, False), (479, False), (-1, False),
                               (None, False), (True, False), (float("nan"), False)]:
            value = dict(status="completed", optimizer_updates_completed=400, formal_training_fits=0,
                         task_datasets_read=False, within_480_second_probe_window=True, wall_seconds=wall)
            (self.root / "budget.json").write_text(json.dumps(value))
            with self.subTest(wall=wall):
                self.assertIs(semantic_check(stage, self.root)["pass_"], expected)

    def test_read_atime_change_allowed_symlink_rejected(self):
        os.utime(self.data, (1, 1))
        expected = self.data.read_bytes()
        os.utime(self.data, (1, 1))
        self.assertEqual(a.regular_bytes(self.data), expected)
        link = self.root / "link"
        link.symlink_to(self.data)
        with self.assertRaises(OSError):
            a.regular_bytes(link)


class OwnedProcessTests(unittest.TestCase):
    def run_owned(self, code, timeout=2.0):
        scope = ChildScope()
        process = subprocess.Popen([sys.executable, "-B", "-c", code], start_new_session=True,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        timed_out = False
        try:
            try:
                process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
            proof = scope.finish(process, timed_out=timed_out, grace_seconds=.4)
            self.assertTrue(proof["child_execution_stopped"])
            self.assertFalse(proof["process_group_alive"])
            self.assertEqual(proof["remaining_owned"], [])
            return proof
        finally:
            if process.poll() is None or scope.snapshot()[1]:
                scope.finish(process, timed_out=True, grace_seconds=.4)
            scope.close()

    def test_normal_exit_has_actual_empty_descendants(self):
        proof = self.run_owned("raise SystemExit(0)")
        self.assertEqual(proof["returncode"], 0)
        self.assertFalse(proof["unexpected_live_descendant_after_main_exit"])
        self.assertEqual(proof["actions"], [])

    def test_timeout_stops_owned_process(self):
        proof = self.run_owned("import time; time.sleep(10)", timeout=.1)
        self.assertTrue(proof["timed_out"])
        self.assertLess(proof["returncode"], 0)
        self.assertTrue(proof["actions"])

    def test_escaped_session_after_zero_exit_is_detected_and_reaped(self):
        code = "import os,time\npid=os.fork()\nif pid==0:\n os.setsid();time.sleep(10);os._exit(0)\nelse:\n time.sleep(.15);os._exit(0)\n"
        proof = self.run_owned(code)
        self.assertEqual(proof["returncode"], 0)
        self.assertTrue(proof["unexpected_live_descendant_after_main_exit"])
        self.assertTrue(proof["actions"])
        self.assertTrue(proof["reaped"])


if __name__ == "__main__":
    unittest.main()
