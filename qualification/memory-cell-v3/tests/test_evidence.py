"""Evidence verification rejects changed bytes and incomplete stage claims."""

import json
from pathlib import Path
import tempfile
import unittest

from v3.evidence import fingerprint, seal_run, source_snapshot, verify_run, write_json


class EvidenceTests(unittest.TestCase):
    def fixture(self, directory):
        source = directory / "source"
        source.mkdir()
        protocol_path = source / "qualification/memory-cell-v3/PROTOCOL.json"
        protocol_path.parent.mkdir(parents=True)
        protocol = {
            "development_seeds": [8011],
            "seeds": [307],
            "stages": ["native"],
            "native": {"rows": 2},
        }
        write_json(protocol_path, protocol)
        identity = {
            "schema": "memory-cell-v3.source.v1",
            "commit": "1" * 40,
            "files": {
                "qualification/memory-cell-v3/PROTOCOL.json": fingerprint(
                    protocol_path.read_bytes()
                )
            },
        }
        output = directory / "run"
        output.mkdir()
        (output / "protocol.json").write_bytes(protocol_path.read_bytes())
        write_json(output / "source_identity.json", identity)
        write_json(
            output / "environment.json",
            {"mode": "development_only", "selected_seeds": [8011], "stage": "all"},
        )
        write_json(
            output / "execution_status.json",
            {"execution": "completed", "completed_stages": ["native"]},
        )
        receipt = {"queries": 2}
        data = {
            "seeds": [8011],
            "source_commit": identity["commit"],
            "development": True,
            "protocol": {"rows": 2},
            "results": [{"seed": 8011, "native": receipt}],
        }
        write_json(
            output / "results.json",
            {
                "native": {
                    "selected_seeds": [8011],
                    "source_commit": identity["commit"],
                    "development_only": True,
                    "data": data,
                }
            },
        )
        write_json(output / "native/native.json", data)
        write_json(output / "native/seed-8011/native/native-receipt.json", receipt)
        source_snapshot(output / "source_snapshot.zip", identity, source)
        seal_run(output, identity)
        return source, output, identity

    def test_original_snapshot_survives_later_source_edits(self):
        with tempfile.TemporaryDirectory() as temporary:
            source, output, _ = self.fixture(Path(temporary))
            (source / "qualification/memory-cell-v3/PROTOCOL.json").write_text(
                "changed source after the run"
            )
            self.assertTrue(verify_run(output, source)["verified"])

    def test_changed_bytes_and_uninventoried_files_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            source, output, _ = self.fixture(Path(temporary))
            extra = output / "unlisted.bin"
            extra.write_bytes(b"new")
            with self.assertRaises(ValueError):
                verify_run(output, source)
            extra.unlink()
            (output / "results.json").write_text("{}")
            with self.assertRaises(ValueError):
                verify_run(output, source)

    def test_self_consistent_seal_does_not_hide_missing_experiment_stage(self):
        with tempfile.TemporaryDirectory() as temporary:
            source, output, identity = self.fixture(Path(temporary))
            write_json(output / "results.json", {})
            (output / "MANIFEST.json").unlink()
            seal_run(output, identity)
            with self.assertRaises(ValueError):
                verify_run(output, source)

    def test_resealed_completed_stage_cannot_omit_its_actual_training_members(self):
        with tempfile.TemporaryDirectory() as temporary:
            source, output, identity = self.fixture(Path(temporary))
            result = json.loads((output / "results.json").read_text())
            result["native"]["data"]["results"] = []
            write_json(output / "results.json", result)
            write_json(output / "native/native.json", result["native"]["data"])
            (output / "MANIFEST.json").unlink()
            seal_run(output, identity)
            with self.assertRaises(ValueError):
                verify_run(output, source)


if __name__ == "__main__":
    unittest.main()
