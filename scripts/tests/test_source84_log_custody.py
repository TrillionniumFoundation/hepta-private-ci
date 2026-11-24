"""Read the nine original source84 logs against their frozen acquisition manifest."""

import json
from pathlib import Path
import sys
import unittest

REPOSITORY = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY / "scripts"))
sys.path.insert(0, str(REPOSITORY / "qa/repository-consolidation/20261115"))

from restore_raw_evidence import entries, read_regular, read_verified
from verify_source_custody_container import identity


class Source84LogCustodyTests(unittest.TestCase):
    def test_complete_original_logs_and_sidecars(self):
        directory = "qualification/evaluated-current-read-20261112/source84-cross-platform-readback"
        raw = read_regular(REPOSITORY, f"{directory}/MANIFEST.json", 17160)
        self.assertEqual(
            identity(raw),
            {
                "bytes": 17160,
                "sha256": "135fcb2c427ff77b712559e352547ef0a0e0dcea47110849ecc3ebf65a75d280",
                "oid": "4b912eafb0f2be618454954e37762533fe894c62",
            },
        )
        manifest = json.loads(raw)
        inventory = entries(REPOSITORY)
        seen_parts = set()
        total_bytes = 0
        for log in manifest["logs"]:
            with self.subTest(job=log["job_id"]):
                whole = bytearray()
                for part in log["parts"]:
                    name = f"{directory}/{part['path']}"
                    self.assertNotIn(name, seen_parts)
                    seen_parts.add(name)
                    self.assertIn(name, inventory)
                    self.assertFalse((REPOSITORY / name).exists())
                    self.assertEqual(part["offset"], len(whole))
                    data = read_verified(REPOSITORY, name, part["bytes"], part["sha256"])
                    self.assertEqual(identity(data)["oid"], part["git_blob"])
                    whole.extend(data)
                self.assertEqual(
                    identity(whole),
                    {
                        "bytes": log["whole_bytes"],
                        "sha256": log["whole_sha256"],
                        "oid": log["whole_git_blob"],
                    },
                )
                total_bytes += len(whole)

        excerpt = f"{directory}/MAC_NEURON_ORIGINAL_BLOCK.log"
        self.assertFalse((REPOSITORY / excerpt).exists())
        self.assertEqual(
            seen_parts | {excerpt},
            {name for name in inventory if name.startswith(directory + "/")},
        )
        self.assertEqual(len(seen_parts), manifest["log_parts"])
        self.assertEqual(len(manifest["logs"]), manifest["original_full_logs"])
        self.assertEqual(total_bytes, manifest["original_full_log_bytes"])
        for sidecar in manifest["files"]:
            with self.subTest(sidecar=sidecar["path"]):
                name = f"{directory}/{sidecar['path']}"
                data = read_verified(REPOSITORY, name, sidecar["bytes"], sidecar["sha256"])
                self.assertEqual(identity(data)["oid"], sidecar["git_blob"])


if __name__ == "__main__":
    unittest.main()
