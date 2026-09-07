"""Real subprocess discovery against disposable rootfs trees, never the host root."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest


CONTROL_ROOT = Path(__file__).resolve().parents[3]
RESULT_SCHEMA = "hepta.assimilation.discovery-cli-result.v1"
SCOPE_SCHEMA = "hepta.assimilation.discovery-scope-input.v1"


@unittest.skipUnless(sys.platform == "linux", "Linux-only descriptor semantics")
class DiscoveryCliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.root = self.base / "rootfs"
        self.root.mkdir()
        self.write("etc/os-release", b"ID=debian\nVERSION_ID=13\n")
        self.write(
            "var/lib/dpkg/status",
            b"Package: example-app\nStatus: install ok installed\n"
            b"Architecture: amd64\nVersion: 1.0-1\n",
        )
        self.write(
            "etc/systemd/system/api.service",
            b"[Unit]\nAfter=network.target\n[Service]\nExecStart=/bin/false --secret=NO_ECHO\n",
        )
        self.write("etc/systemd/system/unselected.service", b"[Unit]\nDescription=UNSELECTED_MARKER\n")
        self.write("etc/shadow", b"ROOTFS_SECRET_MARKER")
        root = self.root.stat()
        self.scope_path = self.base / "scope.json"
        self.scope = {
            "schema": SCOPE_SCHEMA,
            "rootDevice": root.st_dev,
            "rootInode": root.st_ino,
            "hostIdentityDigest": "1" * 64,
            "enrollmentReceiptDigest": "2" * 64,
            "expiresUnixNs": time.time_ns() + 60_000_000_000,
            "osReleasePath": "etc/os-release",
            "unitPaths": ["etc/systemd/system/api.service"],
        }
        self.write_scope(self.scope)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, relative: str, data: bytes) -> None:
        target = self.root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

    def write_scope(self, value: object) -> None:
        self.scope_path.write_text(json.dumps(value), encoding="utf-8")

    def run_cli(
        self,
        *extra: str,
        root: str | Path | None = None,
        scope_path: Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        command = [
            sys.executable, "-m", "assimilation.discovery",
            "--root", str(self.root if root is None else root),
            "--scope-receipt", str(scope_path or self.scope_path),
            "--unit", "etc/systemd/system/api.service",
            *extra,
        ]
        environment = os.environ.copy()
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        return subprocess.run(
            command,
            cwd=CONTROL_ROOT,
            env=environment,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )

    def assert_rejected(self, result: subprocess.CompletedProcess[str], code: str, exit_code: int) -> None:
        self.assertEqual(result.returncode, exit_code, result)
        payload = json.loads(result.stdout)
        self.assertEqual(payload, {
            "activation": False,
            "authorityGranted": False,
            "error": {"code": code},
            "partialCandidate": False,
            "schema": RESULT_SCHEMA,
            "status": "REJECTED",
        })
        self.assertEqual(result.stderr, f"hepta-assimilation-discovery: {code}\n")

    def test_real_subprocess_emits_bounded_non_authoritative_candidate(self):
        before = {
            str(path.relative_to(self.root)): (path.read_bytes(), path.stat().st_mtime_ns)
            for path in self.root.rglob("*") if path.is_file()
        }
        result = self.run_cli()
        self.assertEqual(result.returncode, 0, result)
        self.assertEqual(result.stderr, "")
        payload = json.loads(result.stdout)
        candidate_bytes = json.dumps(
            payload["candidate"], sort_keys=True, separators=(",", ":"),
            ensure_ascii=True, allow_nan=False,
        ).encode("utf-8")
        self.assertEqual(payload["schema"], RESULT_SCHEMA)
        self.assertEqual(payload["status"], "DISCOVERED_CANDIDATE")
        self.assertEqual(payload["candidateBytes"], len(candidate_bytes))
        self.assertEqual(payload["candidateSha256"], hashlib.sha256(candidate_bytes).hexdigest())
        self.assertEqual(payload["candidate"]["scope"]["unit_paths"], ["etc/systemd/system/api.service"])
        self.assertEqual(payload["coverage"]["class"], "selected_metadata_only")
        self.assertIn("selected_units_only", payload["coverage"]["omissions"])
        self.assertIn("unresolved_service_dependencies", payload["coverage"]["omissions"])
        self.assertFalse(payload["authorityGranted"])
        self.assertFalse(payload["activation"])
        self.assertEqual(set(payload["trustBoundary"].values()), {False})
        self.assertNotIn("ROOTFS_SECRET_MARKER", result.stdout)
        self.assertNotIn("UNSELECTED_MARKER", result.stdout)
        self.assertNotIn("NO_ECHO", result.stdout)
        after = {
            str(path.relative_to(self.root)): (path.read_bytes(), path.stat().st_mtime_ns)
            for path in self.root.rglob("*") if path.is_file()
        }
        self.assertEqual(before, after)

    def test_scope_and_selection_fail_closed_with_machine_errors(self):
        expired = {**self.scope, "expiresUnixNs": 1}
        self.write_scope(expired)
        self.assert_rejected(self.run_cli(), "expired_scope", 3)
        mismatch = {**self.scope, "rootInode": self.scope["rootInode"] + 1}
        self.write_scope(mismatch)
        self.assert_rejected(self.run_cli(), "root_identity_mismatch", 3)
        self.write_scope(self.scope)
        self.assert_rejected(
            self.run_cli("--unit", "etc/systemd/system/unselected.service"),
            "selected_units_scope_mismatch", 2,
        )

    def test_malformed_unknown_duplicate_and_symlink_scope_inputs_reject(self):
        self.scope_path.write_text("{", encoding="utf-8")
        self.assert_rejected(self.run_cli(), "invalid_scope_json", 2)
        self.scope_path.write_text('{"rootDevice":' + "9" * 5000 + "}", encoding="utf-8")
        self.assert_rejected(self.run_cli(), "invalid_scope_json", 2)
        self.write_scope({**self.scope, "unexpected": True})
        self.assert_rejected(self.run_cli(), "invalid_scope_shape", 2)
        self.write_scope({**self.scope, "hostIdentityDigest": "not-a-digest"})
        self.assert_rejected(self.run_cli(), "invalid_scope_digest", 3)
        self.scope_path.write_text(
            '{"schema":"first","schema":"second"}', encoding="utf-8",
        )
        self.assert_rejected(self.run_cli(), "duplicate_json_member", 2)
        real_scope = self.base / "real-scope.json"
        real_scope.write_text(json.dumps(self.scope), encoding="utf-8")
        self.scope_path.unlink()
        self.scope_path.symlink_to(real_scope)
        self.assert_rejected(self.run_cli(), "scope_receipt_rejected", 2)

    def test_all_operational_inputs_are_required_and_absolute(self):
        environment = os.environ.copy()
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        result = subprocess.run(
            [sys.executable, "-m", "assimilation.discovery"],
            cwd=CONTROL_ROOT,
            env=environment,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        self.assert_rejected(result, "invalid_arguments", 2)
        self.assert_rejected(self.run_cli(root="relative-root"), "root_path_not_absolute", 2)


if __name__ == "__main__":
    unittest.main()
