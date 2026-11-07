"""Short real subprocess containment/export checks; no GPU or model downloads."""

import json
import hashlib
import io
import os
from pathlib import Path
import signal
import sys
import tarfile
import tempfile
import time
from types import SimpleNamespace
import unittest
import zipfile
from unittest.mock import patch

from .cloud_pilot import (
    Commands,
    artifact_manifest,
    pack_evidence,
    run,
    sha,
    transfer_images,
    verify_source,
    write,
)


class CloudPilotContracts(unittest.TestCase):
    def test_real_failed_and_timed_out_commands_retain_terminal_meters(self):
        for script, status, cap in (
            ("print('actual output')", "completed", 2.0),
            ("raise SystemExit(7)", "failed", 2.0),
            ("import time; time.sleep(2)", "timed_out", 0.05),
        ):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                report = {
                    "stages": [
                        {
                            "name": "probe",
                            "wall_cap_seconds": cap,
                            "status": "not_started",
                        }
                    ]
                }
                commands = Commands(root, report, time.perf_counter() + 100)
                if status == "completed":
                    commands.execute("probe", [sys.executable, "-c", script])
                else:
                    with self.assertRaises(RuntimeError):
                        commands.execute("probe", [sys.executable, "-c", script])
                receipt = json.loads((root / "probe.meter.json").read_text())
                self.assertEqual(receipt["status"], status)
                self.assertGreater(receipt["wall_seconds"], 0)
                self.assertIsNotNone(receipt["child_return_code"])

    def test_no_remaining_global_budget_cannot_start_another_child(self):
        with tempfile.TemporaryDirectory() as folder:
            report = {
                "stages": [
                    {"name": "probe", "wall_cap_seconds": 20, "status": "not_started"}
                ]
            }
            with self.assertRaises(TimeoutError):
                Commands(folder, report, time.perf_counter()).execute(
                    "probe", ["unreachable-command"]
                )
            self.assertEqual(
                report["stages"][0]["status"], "not_started_total_budget_exhausted"
            )
            self.assertEqual(list(Path(folder).iterdir()), [])

    def test_source_rejects_modified_and_unlisted_files(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "source"
            source.mkdir()
            code = source / "a.py"
            code.write_text("x=1\n")
            manifest = root / "manifest.json"
            write(
                manifest,
                {
                    "source_sha": "a" * 40,
                    "files": [
                        {
                            "path": "a.py",
                            "bytes": code.stat().st_size,
                            "sha256": sha(code),
                        }
                    ],
                },
            )
            verify_source(source, manifest, sha(manifest), "a" * 40)
            (source / "extra.py").write_text("x=2\n")
            with self.assertRaisesRegex(ValueError, "Unlisted"):
                verify_source(source, manifest, sha(manifest), "a" * 40)
            (source / "extra.py").unlink()
            code.write_text("x=3\n")
            with self.assertRaisesRegex(ValueError, "differs"):
                verify_source(source, manifest, sha(manifest), "a" * 40)

    def test_cas_pack_preserves_duplicate_paths_and_manifest_covers_every_export(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            evidence = root / "evidence"
            evidence.mkdir()
            output = root / "output"
            output.mkdir()
            for name in ("first.txt", "second.txt"):
                (evidence / name).write_bytes(b"same actual bytes")
            result = pack_evidence(
                {"execution": evidence},
                output / "evidence.tar.gz",
                time.perf_counter() + 10,
            )
            self.assertEqual((result["file_paths"], result["unique_blobs"]), (2, 1))
            with tarfile.open(output / "evidence.tar.gz") as archive:
                index = json.load(archive.extractfile("index.json"))
                for item in index["files"]:
                    self.assertEqual(
                        archive.extractfile("blobs/" + item["sha256"]).read(),
                        b"same actual bytes",
                    )
            write(output / "BOOTSTRAP_RESULT.json", {"scientific_acceptance": False})
            manifest = artifact_manifest(output, "fixture-request")
            self.assertEqual(
                {r["path"] for r in manifest["files"]},
                {"evidence.tar.gz", "BOOTSTRAP_RESULT.json"},
            )
            self.assertTrue(
                all(sha(output / r["path"]) == r["sha256"] for r in manifest["files"])
            )

    def test_transport_zero_preserves_experiment_failure_and_no_setup(self):
        with tempfile.TemporaryDirectory(dir="/tmp") as folder:
            root = Path(folder)
            source = root / "source"
            source.mkdir()
            (source / "a.py").write_text("x=1\n")
            manifest = root / "SOURCE.json"
            write(
                manifest,
                {
                    "source_sha": "a" * 40,
                    "files": [
                        {"path": "a.py", "bytes": 4, "sha256": sha(source / "a.py")}
                    ],
                },
            )
            profile = root / "PROFILE.json"
            write(profile, {"device": "cuda:0", "dtype": "float16"})
            pool = root / "pool"
            pool.mkdir()
            (pool / "subset.txt").write_text("explicit fixture, no human data")
            args = SimpleNamespace(
                output=str(root / "output"),
                workspace=str(root / "work"),
                source_root=str(source),
                pool=str(pool),
                source_manifest=str(manifest),
                source_manifest_sha256=sha(manifest),
                source_sha="a" * 40,
                profile=str(profile),
                request_id="fixture-request",
                budget_seconds=60,
            )
            method = Commands.execute
            handler = signal.getsignal(signal.SIGALRM)

            def fail_driver(instance, name, command):
                self.assertEqual(name, "driver")
                return method(
                    instance, name, [sys.executable, "-c", "raise SystemExit(7)"]
                )

            with patch.object(Commands, "execute", fail_driver), patch.dict(os.environ):
                code = run(args)
            result = json.loads((root / "output/BOOTSTRAP_RESULT.json").read_text())
            self.assertEqual(code, 0)
            self.assertEqual(result["experiment_status"], "Failed")
            self.assertFalse(result["scientific_acceptance"])
            self.assertTrue(result["artifact_complete"])
            self.assertEqual(result["stages"][0]["return_code"], 7)
            self.assertTrue(
                all(r["status"] == "not_started" for r in result["stages"][1:])
            )
            self.assertEqual(signal.getsignal(signal.SIGALRM), handler)

    def test_image_transfer_inherits_prior_byte_budget_and_preserves_metadata(self):
        from . import pilot_data
        from ndu_semantic_state import acquire_vizwiz

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            pool = root / "pool"
            pool.mkdir()
            prior = pool / "PRIOR.json"
            write(
                prior,
                {
                    "cumulative_body_bytes_read": 11064483,
                    "cumulative_body_byte_cap": 26214400,
                },
            )
            payload = b"explicit transfer fixture bytes, not an image"
            cases = [
                {
                    "id": name,
                    "image": {
                        "path": f"data/{i}/input.jpg",
                        "bytes": len(payload),
                        "sha256": hashlib.sha256(payload).hexdigest(),
                    },
                }
                for i, name in enumerate(pilot_data.CASE_IDS)
            ]
            write(
                pool / "CANDIDATES.json",
                {
                    "cases": cases,
                    "acquisition_receipt": {
                        "path": prior.name,
                        "bytes": prior.stat().st_size,
                        "sha256": sha(prior),
                    },
                },
            )
            write(pool / "HISTORY.json", {"fixture": True})
            manifest_pin, history_pin = (
                sha(pool / "CANDIDATES.json"),
                sha(pool / "HISTORY.json"),
            )
            archive = io.BytesIO()
            with zipfile.ZipFile(archive, "w") as stream:
                for name in pilot_data.CASE_IDS:
                    stream.writestr(name.split(":", 1)[1], payload)
            archive_bytes = archive.getvalue()

            def remote(download, url):
                self.assertEqual(download.bytes_read, 11064483)
                self.assertEqual(url, acquire_vizwiz.IMAGES)
                download.bytes_read += len(archive_bytes)
                return io.BytesIO(archive_bytes)

            with (
                patch.object(pilot_data, "MANIFEST_SHA", manifest_pin),
                patch.object(pilot_data, "HISTORY_SHA", history_pin),
                patch.object(
                    pilot_data,
                    "load_pool",
                    return_value=(cases, {"scientific_admission": False}),
                ),
                patch.object(acquire_vizwiz, "RangeArchive", side_effect=remote),
            ):
                transfer_images(pool, root / "transfer")
            receipt = json.loads((root / "transfer/TRANSFER.json").read_text())
            self.assertEqual(
                receipt["cumulative_body_bytes"], 11064483 + len(archive_bytes)
            )
            self.assertEqual(receipt["new_body_bytes"], len(archive_bytes))
            self.assertEqual(len(receipt["images"]), 9)
            self.assertFalse(receipt["original_metadata_regenerated"])
            self.assertFalse(receipt["full_annotation_archive_present"])
            self.assertEqual(
                (sha(pool / "CANDIDATES.json"), sha(pool / "HISTORY.json")),
                (manifest_pin, history_pin),
            )


if __name__ == "__main__":
    unittest.main()
