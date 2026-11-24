"""Read back the original MEM8 blocking run from both acquisition snapshots."""

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


DIRECTORY = "qualification/memory-cell-mem8-ci-followup/v17/blocking-d0f-recovered"


class Mem8LogCustodyTests(unittest.TestCase):
    def manifest(self, name, size, sha256):
        raw = read_regular(REPOSITORY, f"{DIRECTORY}/{name}.json", size)
        self.assertEqual(len(raw), size)
        self.assertEqual(hashlib.sha256(raw).hexdigest(), sha256)
        return json.loads(raw)

    def read_record(self, record):
        name = f"{DIRECTORY}/{record['path']}"
        raw = read_verified(REPOSITORY, name, record["bytes"], record["sha256"])
        self.assertEqual(identity(raw)["oid"], record["git_blob"])
        return raw

    def test_original_job_logs(self):
        early = self.manifest(
            "STORE_RECOVERY_MANIFEST",
            53221,
            "fe32da678934ee4e6b29c31ad1353302f3ffde58dfb0189c1365747227eb9b0a",
        )
        terminal = self.manifest(
            "TERMINAL_MANIFEST",
            76246,
            "63d71f124cc28417b4f322c2daba571191041836344e0f11f272d29b8ed03ad9",
        )
        jobs = {job["path"]: job for job in terminal["all_original_full_raw_files"]}
        for job in early["raw_files"]:
            for field in ("full_pin", "parts"):
                self.assertEqual(job[field], jobs[job["path"]][field])
        self.assertEqual(
            (len(early["raw_files"]), sum(len(j["parts"]) for j in early["raw_files"])),
            (26, 62),
        )
        seen = set()
        total = 0
        for name, job in jobs.items():
            with self.subTest(job=name):
                whole = bytearray()
                characters = 0
                for sequence, part in enumerate(job["parts"], start=1):
                    path = f"{DIRECTORY}/{part['path']}"
                    self.assertNotIn(path, seen)
                    seen.add(path)
                    self.assertEqual(part["sequence"], sequence)
                    raw = self.read_record(part)
                    if "char_start" in part:
                        # The acquisition recorded JavaScript UTF-16 string offsets.
                        self.assertEqual(part["char_start"], characters)
                        characters += len(raw.decode("utf-8").encode("utf-16-le")) // 2
                        self.assertEqual(part["char_end"], characters)
                    whole.extend(raw)
                pin = job["full_pin"]
                self.assertEqual(
                    identity(whole),
                    {
                        "bytes": pin["bytes"],
                        "sha256": pin["sha256"],
                        "oid": pin["git_blob"],
                    },
                )
                total += len(whole)
        stored = {
            path for path in entries(REPOSITORY) if path.startswith(DIRECTORY + "/")
        }
        self.assertEqual(stored, seen)
        self.assertEqual((len(jobs), len(seen), total), (28, 64, 13751922))
        for record in terminal["original_terminal_objects"]:
            with self.subTest(metadata=record["path"]):
                self.read_record(record)


if __name__ == "__main__":
    unittest.main()
