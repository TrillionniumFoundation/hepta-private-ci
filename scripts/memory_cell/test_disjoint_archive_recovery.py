"""Original failed workflow cannot be promoted without exact archive pins."""

import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from disjoint_archive_recovery import (
    EVALUATION,
    REQUIRED,
    RUN_ID,
    SOURCE,
    WORKFLOW,
    extract_one,
    qualify,
    unpack,
    validate_pins,
)


def population():
    names = sorted(REQUIRED)
    pins = {
        "run_id": RUN_ID,
        "source_commit": SOURCE,
        "artifacts": {
            name: {
                "id": index + 1,
                "sha256": "a" * 64,
                "size": 100,
            }
            for index, name in enumerate(names)
        },
    }
    run = {
        "id": RUN_ID,
        "head_sha": SOURCE,
        "name": WORKFLOW,
        "run_attempt": 16,
        "status": "completed",
        "conclusion": "failure",
    }
    jobs = {
        "jobs": [
            {"name": name, "conclusion": "success"}
            for name in (
                "preflight",
                "prepare",
                "calibration-collect",
                *(
                    f"calibration-shard ({i}, {part})"
                    for i in range(8)
                    for part in range(2)
                ),
                *(
                    f"evaluation-shard ({i}, {part})"
                    for i in range(8)
                    for part in range(2)
                ),
            )
        ]
        + [
            {"name": "evaluation-collect", "conclusion": "failure"},
            {"name": "independent-replay", "conclusion": "skipped"},
        ],
    }
    jobs["total_count"] = len(jobs["jobs"])
    artifacts = {
        "artifacts": [
            {
                "name": name,
                "id": spec["id"],
                "digest": "sha256:" + spec["sha256"],
                "size_in_bytes": spec["size"],
                "expired": False,
                "workflow_run": {"head_sha": SOURCE},
            }
            for name, spec in pins["artifacts"].items()
        ],
    }
    artifacts["total_count"] = len(artifacts["artifacts"])
    return pins, run, jobs, artifacts


class DisjointArchivedRecoveryTests(unittest.TestCase):
    def test_complete_archive_census_remains_a_failed_original_run(self):
        pins, run, jobs, artifacts = population()
        report = qualify(pins, run, jobs, artifacts)
        self.assertEqual(len(EVALUATION), 16)
        self.assertEqual(report["sealed_archives_to_reopen"], 18)
        self.assertEqual(report["generating_workflow_conclusion"], "failure")
        self.assertEqual(report["successful_original_evaluation_jobs"], 16)
        self.assertEqual(report["new_model_calls"], 0)
        self.assertFalse(report["production_accepted"])

    def test_missing_or_tampered_outer_artifact_fails_closed(self):
        for flaw in ("missing", "digest", "expired", "wrong_source", "bad_size"):
            with self.subTest(flaw=flaw):
                pins, run, jobs, artifacts = population()
                first = artifacts["artifacts"][0]
                if flaw == "missing":
                    artifacts["artifacts"].pop(0)
                    artifacts["total_count"] -= 1
                elif flaw == "digest":
                    first["digest"] = "sha256:" + "b" * 64
                elif flaw == "expired":
                    first["expired"] = True
                elif flaw == "wrong_source":
                    first["workflow_run"]["head_sha"] = "f" * 40
                else:
                    first["size_in_bytes"] += 1
                with self.assertRaises(ValueError):
                    qualify(pins, run, jobs, artifacts)

    def test_generation_failure_and_fake_workflow_success_both_reject(self):
        for flaw in ("run_success", "attempt", "failed_shard", "fake_replay"):
            with self.subTest(flaw=flaw):
                pins, run, jobs, artifacts = population()
                if flaw == "run_success":
                    run["conclusion"] = "success"
                elif flaw == "attempt":
                    run["run_attempt"] = 1
                elif flaw == "failed_shard":
                    jobs["jobs"][3]["conclusion"] = "cancelled"
                else:
                    jobs["jobs"][-1]["conclusion"] = "success"
                with self.assertRaises(ValueError):
                    qualify(pins, run, jobs, artifacts)

    def test_pin_population_rejects_duplicates_and_unregistered_shards(self):
        pins, _, _, _ = population()
        del pins["artifacts"]["memory-evaluation-6-0"]
        with self.assertRaises(ValueError):
            validate_pins(pins)
        pins, _, _, _ = population()
        pins["artifacts"]["memory-evaluation-6-0"]["id"] = pins["artifacts"][
            "memory-evaluation-0-0"
        ]["id"]
        with self.assertRaises(ValueError):
            validate_pins(pins)

    def test_exact_outer_bytes_and_safe_zip_members(self):
        name = "memory-evaluation-0-0"
        for file_name in ("raw-answers.jsonl", "../escape", "/root", "dup/../escape"):
            with self.subTest(file_name=file_name), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                archive = root / "source.zip"
                with zipfile.ZipFile(archive, "w") as stream:
                    stream.writestr(file_name, "original-answer\n")
                pins, _, _, _ = population()
                data = archive.read_bytes()
                pins["artifacts"][name] = {
                    "id": pins["artifacts"][name]["id"],
                    "sha256": hashlib.sha256(data).hexdigest(),
                    "size": len(data),
                }
                destination = root / "safe"
                if file_name == "raw-answers.jsonl":
                    self.assertEqual(extract_one(pins, name, archive, destination), 1)
                    self.assertEqual(
                        (destination / file_name).read_text(), "original-answer\n"
                    )
                else:
                    with self.assertRaises(ValueError):
                        extract_one(pins, name, archive, destination)
                    self.assertFalse(destination.exists())
                archive.write_bytes(data + b"tamper")
                with self.assertRaises(ValueError):
                    extract_one(pins, name, archive, root / "forged")

    def test_disallow_partial_population_before_any_unpack(self):
        pins, _, _, _ = population()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with self.assertRaises((FileNotFoundError, ValueError)):
                unpack(pins, root, root / "unpacked")


if __name__ == "__main__":
    unittest.main()
