"""Reject forged parent/closure inputs without running any model or training."""

import argparse
import copy
import json
from pathlib import Path
import tempfile
import unittest

import make_ordinary_qualification as tested


def parent():
    digest = "17" * 32
    receipt = {
        "schema": "hepta.cell-learning.v13.content-binding.v1",
        "authority": "DENY_ALL", "verification_mode": "reference",
        "synthetic": False, "training_executed": False,
        "inference_executed": False, "adoption_performed": False,
        "checkpoint": {"sha256": digest, "legacy_state_sha256": digest},
        "context": {"encoder_hash": digest, "source_version": digest, "data_id": digest},
        "release": {"artifact_id": digest},
        "training_data": {"artifact_sha256": digest},
        "source": {"snapshot_sha256": digest},
        "encoder": {
            "manifest_file_sha256": digest,
            "manifest": {"files": {name: {"sha256": digest} for name in tested.protocol.ENCODER_SIZES}},
        },
        "member_sha256": {name: digest for name in tested.protocol.LEARNING_MEMBERS},
        "binding": {"kind": "resumable", **{name: [23] * 32 for name in tested.protocol.LEARNING_MEMBERS}},
    }
    return {"phase": "bootstrap", "status": "completed", "result": {"engineering_passed": True, "epoch": 1, "artifact": digest, "closure": receipt}}


class OrdinaryQualificationTests(unittest.TestCase):
    def test_parent_receipt_cannot_substitute_publication_or_learning_state(self):
        original = parent()
        receipt, closure = tested.parent_closure(original)
        self.assertEqual(closure["learning"], receipt["binding"])
        mutations = [
            ((), "phase", "publish"), ((), "status", "failed"),
            (("result",), "engineering_passed", False),
            (("result",), "epoch", 2), (("result",), "artifact", "18" * 32),
            *((('result', 'closure'), key, value) for key, value in {
                "authority": "ALLOW", "verification_mode": "synthetic", "synthetic": True,
                "training_executed": True, "inference_executed": True, "adoption_performed": True,
            }.items()),
            (("result", "closure", "binding"), "weights", [24] * 32),
        ]
        for path, key, value in mutations:
            with self.subTest(path=path, key=key), self.assertRaises(ValueError):
                changed = copy.deepcopy(original)
                target = changed
                for segment in path:
                    target = target[segment]
                target[key] = value
                tested.parent_closure(changed)

    def test_complete_catalog_refuses_missing_extra_duplicate_and_changed_pins(self):
        receipt, _ = tested.parent_closure(parent())
        names = set(tested.protocol.expected_files("verify")) | set(tested.protocol.expected_files("infer"))
        assets = [{"name": name, "sha256": tested.protocol.SOURCE_HASHES[name[7:]] if name.startswith("vendor/") else "17" * 32} for name in sorted(names)]
        tested.check_assets(receipt, assets)
        changed = copy.deepcopy(assets)
        changed[0]["sha256"] = "18" * 32
        renamed = copy.deepcopy(assets)
        renamed[0]["name"] = "unknown-model.onnx"
        for altered in (assets[:-1], assets + [assets[0]], [assets[0], *assets[2:], assets[0]], changed, renamed):
            with self.subTest(assets=altered), self.assertRaises(ValueError):
                tested.check_assets(receipt, altered)

    def test_novelty_requires_both_text_and_payload_to_be_new(self):
        tested.check_new_task([{"text": "older task", "payload": ["different"]}])
        for rows in ([], [{"text": tested.TASK["text"], "payload": []}], [{"text": "older task", "payload": tested.TASK["payload"]}]):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                tested.check_new_task(rows)

    def test_raw_bootstrap_pin_is_checked_before_any_output_is_created(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "phase_results").mkdir()
            (root / "phase_results/bootstrap.json").write_text(json.dumps(parent()))
            output = root / "new-output"
            arguments = argparse.Namespace(historical_run=root, bootstrap_sha256="19" * 32, output_directory=output)
            with self.assertRaisesRegex(ValueError, "bootstrap pin differs"):
                tested.assemble(arguments)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
