"""Real lifecycle recovery and durable migration regressions."""

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from v6.lifecycle import _copy_bundle, run_lifecycle_study


class LifecycleTests(unittest.TestCase):
    def test_real_release_migration_update_and_recovery(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "study"
            result = run_lifecycle_study(1723, output)
            self.assertEqual(result["status"], "passed", result.get("error"))
            self.assertTrue(result["all_child_processes_reaped"])
            self.assertTrue(all(row["passed"] for row in result["checks"]))
            self.assertEqual(json.loads((output / "LIFECYCLE.json").read_bytes()), result)
            reads = {row["name"]: row["readout"] for row in result["trials"] if "readout" in row}
            self.assertEqual(reads["killed-node"]["value"], None)
            self.assertEqual(reads["restart-recovered"]["value"], reads["three-node"]["value"])
            self.assertNotEqual(reads["corrected-after-release"]["value"], reads["three-node"]["value"])
            self.assertEqual(reads["new-entity-after-release"]["value"], 216)
            self.assertTrue(result["mixed_release"]["rejected"])
            self.assertTrue(result["source_update"]["unobserved_writer_change_can_serve_old_value"])
            self.assertGreater(result["cost"]["application_bundle_copied_bytes"], 0)
            self.assertGreater(result["cost"]["rpc_body_bytes"], 0)
            self.assertEqual(result["cost"]["actual_cell_fits"], 4)
            self.assertEqual(
                result["cost"]["rpc_body_bytes"],
                result["cost"]["rpc"]["sent_bytes"] + result["cost"]["rpc"]["received_bytes"],
            )

    def test_full_bundle_copy_is_independent_and_hash_bound(self):
        with tempfile.TemporaryDirectory() as temporary:
            source, target = Path(temporary) / "writer", Path(temporary) / "replica"
            (source / "objects").mkdir(parents=True)
            payloads = {
                "source.sqlite": b"source-fixture",
                "owner.sqlite": b"owner-fixture",
                "objects/model": b"model-fixture",
            }
            for name, raw in payloads.items():
                (source / name).write_bytes(raw)
            receipt = _copy_bundle(source, target)
            self.assertEqual({row["path"] for row in receipt["files"]}, set(payloads))
            self.assertEqual(receipt["copied_bytes"], sum(map(len, payloads.values())))
            (source / "objects/model").write_bytes(b"changed-source")
            for row in receipt["files"]:
                raw = (target / row["path"]).read_bytes()
                self.assertEqual(raw, payloads[row["path"]])
                self.assertEqual(hashlib.sha256(raw).hexdigest(), row["sha256"])
                self.assertTrue(row["independent_inode"])


if __name__ == "__main__":
    unittest.main()
