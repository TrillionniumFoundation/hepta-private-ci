"""Synthetic sparse-index admission tests; not a dependency upgrade verdict."""

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from matrix_sdk_registry_index import envelope


def index(*, sha=None, version="0.19.0", yanked=False, crate="matrix-sdk-sqlite"):
    release = {
        "name": crate,
        "vers": version,
        "cksum": sha or "a" * 64,
        "yanked": yanked,
        "deps": [],
        "features": {},
    }
    earlier = release | {"vers": "0.18.0", "cksum": "b" * 64}
    return (json.dumps(earlier) + "\n" + json.dumps(release) + "\n").encode()


class RegistryIndexTests(unittest.TestCase):
    def test_official_sparse_index_exact_checksum_envelope(self):
        raw = index(sha="1" * 64)
        body, receipt = envelope(raw)
        self.assertEqual(
            json.loads(body), {"version": {"num": "0.19.0", "checksum": "1" * 64}}
        )
        self.assertEqual(
            receipt["registry_record_sha256"], hashlib.sha256(raw).hexdigest()
        )
        self.assertFalse(receipt["archive_bytes_verified_here"])
        self.assertFalse(receipt["cargo_deny_qualified"])
        self.assertFalse(receipt["production_accepted"])

    def test_missing_or_wrong_target_refuses_weak_fallback(self):
        for raw in (index(version="0.19.1"), index(yanked=True), b""):
            with self.subTest(raw=raw[:12]), self.assertRaises(ValueError):
                envelope(raw)

    def test_duplicate_release_different_checksum_fails(self):
        raw = index()
        duplicated = (
            raw
            + json.dumps(
                {
                    "name": "matrix-sdk-sqlite",
                    "vers": "0.19.0",
                    "cksum": "0" * 64,
                    "yanked": False,
                }
            ).encode()
            + b"\n"
        )
        with self.assertRaises(ValueError):
            envelope(duplicated)

    def test_invalid_publisher_and_malformed_rows_reject(self):
        samples = (
            index(crate="other-crate"),
            (
                b'{"name":"matrix-sdk-sqlite","name":"matrix-sdk-sqlite",'
                b'"vers":"0.19.0","cksum":"' + b"a" * 64 + b'","yanked":false}\n'
            ),
            index(sha="bad"),
            index().replace(b'"yanked": false', b'"yanked": 0'),
            b"\xff\n",
            b"{}\n",
        )
        for raw in samples:
            with (
                self.subTest(raw=raw[:16]),
                self.assertRaises((ValueError, UnicodeError)),
            ):
                envelope(raw)

    def test_bounded_index_and_zero_length_reject(self):
        for raw in (
            b"x" * (2 * 1024 * 1024 + 1),
            b"\n" * 513,
            b"",
            b"x" * (64 * 1024 + 1),
        ):
            with self.assertRaises(ValueError):
                envelope(raw)

    def test_cli_refuses_partial_publication_if_one_output_exists(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            (home / "index.jsonl").write_bytes(index())
            (home / "report.json").write_text("existing")
            cmd = [
                sys.executable,
                str(Path(__file__).with_name("matrix_sdk_registry_index.py")),
                "--index",
                str(home / "index.jsonl"),
                "--metadata",
                str(home / "api.json"),
                "--report",
                str(home / "report.json"),
            ]
            run = subprocess.run(cmd, capture_output=True, text=True)
            self.assertNotEqual(run.returncode, 0)
            self.assertFalse((home / "api.json").exists())
            self.assertEqual((home / "report.json").read_text(), "existing")

    def test_cli_writes_exact_nonoverwriting_metadata_and_report(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            (home / "index.jsonl").write_bytes(index())
            cmd = [
                sys.executable,
                str(Path(__file__).with_name("matrix_sdk_registry_index.py")),
                "--index",
                str(home / "index.jsonl"),
                "--metadata",
                str(home / "api.json"),
                "--report",
                str(home / "report.json"),
            ]
            run = subprocess.run(cmd, capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual(
                json.loads((home / "api.json").read_text())["version"]["checksum"],
                "a" * 64,
            )
            again = subprocess.run(cmd, capture_output=True, text=True)
            self.assertNotEqual(again.returncode, 0)


if __name__ == "__main__":
    unittest.main()
