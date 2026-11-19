"""Archive integrity remains enforced under normal and optimized Python."""

import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest


EVIDENCE = Path(__file__).parent / "evidence"
SCRIPTS = {
    "bootstrap": EVIDENCE
    / "20261025-native-bootstrap-recovery"
    / "verify_bootstrap_evidence.py",
    "controlled": EVIDENCE
    / "20261025-native-controlled-success"
    / "verify_and_reassemble.py",
}


def checksum(data):
    return hashlib.sha256(data).hexdigest()


def add_member(archive, name, data):
    info = tarfile.TarInfo(name)
    info.size = len(data)
    info.mode = 0o600
    info.mtime = 0
    archive.addfile(info, io.BytesIO(data))


def make_fixture(directory, kind, case):
    payload = b"actual"
    name = "../payload.txt" if case == "parent-path" else "payload.txt"
    row = {"bytes": len(payload), "sha256": checksum(payload), "mode": 0o600}
    if kind == "bootstrap":
        row["kind"] = "file"
    if case == "member-hash":
        row["sha256"] = "0" * 64
    if case == "member-mode":
        row["mode"] = 0o640
    inventory = json.dumps({name: row}, sort_keys=True).encode()
    archive_path = directory / "fixture.tar.xz"
    with tarfile.open(archive_path, "w:xz", format=tarfile.USTAR_FORMAT) as archive:
        add_member(archive, name, payload)
        if case == "duplicate-member":
            add_member(archive, name, payload)
        inventory_name = (
            "member-inventory.json"
            if kind == "bootstrap"
            else "audit/member-inventory.json"
        )
        add_member(archive, inventory_name, inventory)
    raw = archive_path.read_bytes()
    common = {
        "bytes": len(raw) + (1 if case == "archive-size" else 0),
        "sha256": "0" * 64 if case == "archive-hash" else checksum(raw),
        "member_inventory_sha256": checksum(inventory),
    }
    if kind == "bootstrap":
        manifest = {
            "archive": {
                **common,
                "file": archive_path.name,
                "payload_files": 1,
                "payload_directories": 0,
                "payload_file_bytes": len(payload),
            }
        }
    else:
        part = directory / "part000"
        part.write_bytes(raw)
        manifest = {
            "archive": {
                **common,
                "filename": archive_path.name,
                "regular_members": 2,
                "directory_members": 0,
            },
            "parts": [
                {"filename": part.name, "bytes": len(raw), "sha256": checksum(raw)}
            ],
            "raw_runs": {},
        }
    manifest_path = directory / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return manifest_path


class ArchiveEvidenceIntegrityTests(unittest.TestCase):
    def test_valid_and_corrupted_archives_in_both_python_modes(self):
        cases = (
            "good",
            "archive-hash",
            "archive-size",
            "member-hash",
            "member-mode",
            "parent-path",
            "duplicate-member",
        )
        for kind, script in SCRIPTS.items():
            self.assertTrue(script.is_file())
            for case in cases:
                for optimized in (False, True):
                    with self.subTest(kind=kind, case=case, optimized=optimized):
                        with tempfile.TemporaryDirectory(
                            prefix="hepta-archive-integrity-"
                        ) as temp:
                            directory = Path(temp)
                            manifest = make_fixture(directory, kind, case)
                            argv = [sys.executable, "-B"]
                            if optimized:
                                argv.append("-O")
                            argv += [str(script.resolve()), str(manifest)]
                            if kind == "controlled":
                                argv += [
                                    "--output",
                                    str(directory / "reassembled.tar.xz"),
                                ]
                            result = subprocess.run(
                                argv,
                                cwd=directory,
                                capture_output=True,
                                text=True,
                                timeout=20,
                                check=False,
                            )
                            if case != "good":
                                self.assertNotEqual(result.returncode, 0, result.stdout)
                                self.assertIn("ValueError", result.stderr)
                                self.assertEqual(result.stdout, "")
                                continue
                            self.assertEqual(result.returncode, 0, result.stderr)
                            observed = json.loads(result.stdout)
                            if kind == "bootstrap":
                                self.assertTrue(observed["all_bytes_modes_verified"])
                                self.assertEqual(observed["payload_files"], 1)
                                self.assertEqual(observed["payload_file_bytes"], 6)
                            else:
                                self.assertTrue(
                                    observed["all_member_bytes_and_modes_verified"]
                                )
                                self.assertEqual(observed["raw_original_files"], 0)
                                self.assertEqual(observed["raw_original_bytes"], 0)
                                self.assertFalse(observed["extraction_performed"])


if __name__ == "__main__":
    unittest.main()
