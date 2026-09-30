"""Bounded observation archive regressions; fixtures are not execution evidence."""

import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import platform_wire_performance_intake as shared
import platform_wire_production_intake as production


PERFORMANCE = {
    "performance-plan.json": 256 * 1024,
    "paired-measurements.json": 16 * 1024 * 1024,
}


def archive(rows, compression=zipfile.ZIP_DEFLATED):
    raw = BytesIO()
    with zipfile.ZipFile(raw, "w", compression=compression) as package:
        for name, contents in rows:
            package.writestr(name, contents)
    return raw.getvalue()


class ArtifactIntakeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.destination = self.root / "input"

    def test_valid_production_and_performance_archives_preserve_exact_files(self):
        for limits in (PERFORMANCE, production.LIMITS):
            with self.subTest(files=tuple(limits)):
                rows = [(name, b"{}\n") for name in limits]
                shared.extract_archive(
                    archive(rows), self.destination, limits, production.MAXIMUM
                )
                for name, contents in rows:
                    path = self.destination / name
                    self.assertEqual(path.read_bytes(), contents)
                    self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
                    path.unlink()

    def test_compressed_bomb_is_rejected_before_opening_any_entry(self):
        # 17 MiB collapses into a small archive, below the 20 MiB compressed cap.
        for limits in (PERFORMANCE, production.LIMITS):
            with self.subTest(files=tuple(limits)):
                plan, report = limits
                raw = BytesIO()
                with zipfile.ZipFile(raw, "w", zipfile.ZIP_DEFLATED) as package:
                    package.writestr(plan, b"{}")
                    with package.open(report, "w") as output:
                        for _ in range(17):
                            output.write(b" " * (1024 * 1024))
                payload = raw.getvalue()
                self.assertLess(len(payload), production.MAXIMUM)
                with patch.object(
                    zipfile.ZipFile,
                    "open",
                    side_effect=AssertionError("decompressed before bounds"),
                ):
                    with self.assertRaises(SystemExit):
                        shared.extract_archive(
                            payload, self.destination, limits, production.MAXIMUM
                        )
                self.assertFalse(self.destination.exists())

    def test_oversize_plan_is_rejected_before_opening_any_entry(self):
        rows = [
            (name, b" " * (limit + 1) if "plan" in name else b"{}")
            for name, limit in production.LIMITS.items()
        ]
        payload = archive(rows)
        with patch.object(
            zipfile.ZipFile,
            "open",
            side_effect=AssertionError("decompressed before bounds"),
        ):
            with self.assertRaises(SystemExit):
                shared.extract_archive(
                    payload, self.destination, production.LIMITS, production.MAXIMUM
                )
        self.assertFalse(self.destination.exists())

    def test_compressed_archive_download_cap_is_enforced(self):
        with patch.object(
            shared.urllib.request, "urlopen", return_value=BytesIO(b"x" * 65)
        ):
            with self.assertRaises(SystemExit):
                shared.download("fixture/repo", "fixture-token", 7, 64)

    def test_downloaded_bytes_must_match_the_selected_artifact_digest(self):
        payload = archive([(name, b"{}") for name in production.LIMITS])
        digest = hashlib.sha256(payload).hexdigest()
        with patch.object(shared, "download", return_value=payload):
            self.assertEqual(
                shared.verified_archive(
                    "fixture/repo", "fixture-token", 7, digest, production.MAXIMUM
                ),
                payload,
            )
            with self.assertRaises(SystemExit):
                shared.verified_archive(
                    "fixture/repo", "fixture-token", 7, "0" * 64, production.MAXIMUM
                )

    def test_closed_entries_reject_foreign_and_nonregular_files(self):
        valid = [(name, b"{}") for name in production.LIMITS]
        for rows in (
            valid + [("extra.json", b"{}")],
            [("../production-plan.json", b"{}"), valid[1]],
        ):
            with self.subTest(rows=rows), self.assertRaises(SystemExit):
                shared.extract_archive(
                    archive(rows),
                    self.destination,
                    production.LIMITS,
                    production.MAXIMUM,
                )
        raw = BytesIO()
        with zipfile.ZipFile(raw, "w") as package:
            for name in production.LIMITS:
                entry = zipfile.ZipInfo(name)
                entry.create_system = 3
                entry.external_attr = (stat.S_IFLNK | 0o777) << 16
                package.writestr(entry, b"target")
        with self.assertRaises(SystemExit):
            shared.extract_archive(
                raw.getvalue(), self.destination, production.LIMITS, production.MAXIMUM
            )

    def test_destination_symlink_cannot_redirect_observation_writes(self):
        real = self.root / "real"
        real.mkdir()
        self.destination.symlink_to(real, target_is_directory=True)
        with self.assertRaises(SystemExit):
            shared.extract_archive(
                archive([(name, b"{}") for name in production.LIMITS]),
                self.destination,
                production.LIMITS,
                production.MAXIMUM,
            )
        self.assertEqual(list(real.iterdir()), [])

    def test_performance_intake_keeps_existing_metadata_and_outputs(self):
        payload = archive([(name, b"{}") for name in PERFORMANCE])
        digest = hashlib.sha256(payload).hexdigest()
        source = "a" * 40
        run = {
            "id": 7,
            "head_sha": source,
            "status": "completed",
            "conclusion": "success",
            "event": "workflow_dispatch",
            "path": ".github/workflows/producer.yml",
            "repository": {"full_name": "fixture/repo"},
            "run_attempt": 2,
        }
        item = {
            "id": 9,
            "name": "observations",
            "size_in_bytes": len(payload),
            "expired": False,
            "digest": "sha256:" + digest,
            "workflow_run": {"head_sha": source},
        }
        records = self.root / "records"
        environment = {
            "GH_TOKEN": "fixture-token",
            "REPOSITORY": "fixture/repo",
            "SOURCE_SHA": source,
            "MEASUREMENT_RUN_ID": "7",
            "MEASUREMENT_WORKFLOW_PATH": run["path"],
            "MEASUREMENT_ARTIFACT": "observations",
            "RECORDS": str(records),
            "INPUT_DIR": str(self.destination),
            "MAX_ARTIFACT_BYTES": str(production.MAXIMUM),
            "GITHUB_ENV": str(self.root / "env"),
        }
        with (
            patch.dict(os.environ, environment),
            patch.object(shared, "json_get", side_effect=[run, {"artifacts": [item]}]),
            patch.object(shared, "download", return_value=payload),
        ):
            shared.intake()
        self.assertEqual(
            json.loads((records / "measurement-artifact.json").read_text())["digest"],
            "sha256:" + digest,
        )
        self.assertEqual(
            json.loads((records / "measurement-run.json").read_text())["attempt"], 2
        )
        self.assertIn(
            "MEASUREMENT_RUN_IDENTITY=github-actions:fixture/repo:7:2",
            (self.root / "env").read_text(),
        )

    def test_production_intake_binds_selected_metadata_and_retains_digest(self):
        payload = archive([(name, b"{}") for name in production.LIMITS])
        digest = hashlib.sha256(payload).hexdigest()
        records = self.root / "records"
        records.mkdir()
        metadata = records / "producer.json"
        metadata.write_text(
            json.dumps({"run": 7, "artifact_id": 9, "artifact_digest": digest})
        )
        environment = {
            "GH_TOKEN": "fixture-token",
            "REPOSITORY": "fixture/repo",
            "OBSERVATION_RUN_ID": "7",
            "RECORDS": str(records),
            "INPUT_DIR": str(self.destination),
        }
        with (
            patch.dict(os.environ, environment),
            patch.object(shared, "download", return_value=payload) as downloader,
        ):
            production.intake()
        downloader.assert_called_once_with(
            "fixture/repo", "fixture-token", 9, production.MAXIMUM
        )
        self.assertIn(digest, (records / "observation-archive.sha256").read_text())
        metadata.write_text(
            json.dumps({"run": 8, "artifact_id": 9, "artifact_digest": digest})
        )
        with (
            patch.dict(os.environ, environment),
            patch.object(shared, "download") as downloader,
        ):
            with self.assertRaises(SystemExit):
                production.intake()
        downloader.assert_not_called()


if __name__ == "__main__":
    unittest.main()
