"""Verify all source0a5 log parts and original job captures against their acquisition records."""

import hashlib
import json
from pathlib import Path
import sys
import unittest

REPOSITORY = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY / "scripts"))
sys.path.insert(0, str(REPOSITORY / "qa/repository-consolidation/20261115"))

from restore_raw_evidence import entries, read_regular, read_verified
from verify_source_custody_container import identity


DIRECTORY = (
    "qualification/evaluated-current-read-20261112/source0a5-cross-platform-readback"
)


class Source0a5LogCustodyTests(unittest.TestCase):
    def manifest(self, name, size, digest):
        raw = read_regular(REPOSITORY, f"{DIRECTORY}/{name}.json", size)
        self.assertEqual(len(raw), size)
        self.assertEqual(hashlib.sha256(raw).hexdigest(), digest)
        return json.loads(raw)

    def read_record(self, record):
        name = f"{DIRECTORY}/{record['path']}"
        data = read_verified(REPOSITORY, name, record["bytes"], record["sha256"])
        self.assertEqual(identity(data)["oid"], record["git_blob"])
        return data

    def test_original_snapshots_read_back(self):
        early = self.manifest(
            "MANIFEST_INITIAL",
            8545,
            "00518555c90444d79cade7b93e73eed156f97d4cdec56b5a1eb7e3300d369db3",
        )
        progress = self.manifest(
            "MANIFEST_PROGRESS",
            74833,
            "66eeba73d8cd22eddb411205d7c865216131eec0b5a8f36374bc8663c3e3877f",
        )
        receipt = self.manifest(
            "GIT_READBACK",
            15201,
            "13d38d59e991eff0ad555c78eb4ab222c17f97daab57492c26b6b65b7e6082e3",
        )
        by_job = {job["job_id"]: job for job in progress["logs_retrieved"]}
        for job in early["logs_retrieved"]:
            for field in ("log", "parts", "characters", "lines"):
                self.assertEqual(job[field], by_job[job["job_id"]][field])

        seen = set()
        total = 0
        for job in by_job.values():
            with self.subTest(job=job["job_id"]):
                whole = bytearray()
                characters = 0
                for part in job["parts"]:
                    self.assertEqual(part["start_character"], characters)
                    name = f"{DIRECTORY}/{part['path']}"
                    self.assertNotIn(name, seen)
                    seen.add(name)
                    self.assertFalse((REPOSITORY / name).exists())
                    data = self.read_record(part)
                    self.assertEqual(len(data.decode("utf-8")), part["characters"])
                    characters += part["characters"]
                    whole.extend(data)
                self.assertEqual(characters, job["characters"])
                original = job["log"]
                self.assertEqual(
                    identity(whole),
                    {
                        "bytes": original["bytes"],
                        "sha256": original["sha256"],
                        "oid": original["git_blob"],
                    },
                )
                total += len(whole)

        inventory = entries(REPOSITORY)
        self.assertEqual(
            seen, {name for name in inventory if name.startswith(DIRECTORY + "/")}
        )
        self.assertEqual((len(by_job), len(seen), total), (12, 50, 8072868))
        self.assertEqual(
            (
                receipt["original_logs"],
                receipt["parts"],
                receipt["complete_original_log_bytes"],
            ),
            (len(by_job), len(seen), total),
        )
        for record in receipt["files"]:
            with self.subTest(file=record["path"]):
                self.assertTrue(record["full_content_exact"])
                self.read_record(record)


if __name__ == "__main__":
    unittest.main()
