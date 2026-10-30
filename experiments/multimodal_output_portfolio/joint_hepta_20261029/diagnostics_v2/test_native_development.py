"""Unit source-admission checks; no fixture claims real native-owner execution."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from experiments.multimodal_output_portfolio.joint_hepta_20261029.diagnostics_v2.native_development import (
    HERE, registered_study,
)
from experiments.multimodal_output_portfolio.joint_hepta_20261029.runtime import make_profile


class NativeDevelopmentAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root, self.study = Path(self.temp.name), Path(self.temp.name) / "run"
        self.study.mkdir()
        protocol = json.loads((HERE / "controller_v2_protocol.json").read_text())
        profile = make_profile()
        self.result = {"schema": "hepta.joint-generation.controller-v2.development.v1",
            "stage": "development", "smoke": False, "seed": 17, "width": 32,
            "confirmation_sources_consumed": 0,
            "protocol_sha256": hashlib.sha256((HERE / "controller_v2_protocol.json").read_bytes()).hexdigest(),
            "profile_sha256": profile.digest,
            "source_sha256": {n: hashlib.sha256((HERE / n).read_bytes()).hexdigest()
                              for n in ("controller_v2.py", "runtime.py", "controller_v2_protocol.json")},
            "pretraining": {m: {"updates": 384, "loss_history": [1] * 384} for m in ("dual", "ordinary")},
            "arms": {a: {"training": {"actual_episodes": 512, "updates": [{}] * 64,
                                     "final_parameters_sha256": "1" * 64},
                         "evaluation": {"actual_draws": 64, "rows": [{"source": s, "draw": d}
                                                     for s in range(32) for d in range(2)]},
                         "checkpoint": {"model_sha256": "1" * 64}} for a in protocol["arms"]},
            "distillation": {"actual_training_episodes": 36, "rounds": [{}, {}, {}],
                              "generator_and_critics_unchanged": True}}
        files = {"experiments/multimodal_output_portfolio/joint_hepta_20261029/" + n: v
                 for n, v in self.result["source_sha256"].items()}
        snapshot = {"files": files, "commit": "a" * 40,
                    "sha256": hashlib.sha256(json.dumps(files, sort_keys=True, separators=(",", ":")).encode()).hexdigest()}
        self.source = {"before": snapshot, "after": deepcopy(snapshot), "source_bytes_unchanged": True}
        (self.study / "PROFILE.json").write_text(json.dumps(profile.to_dict()))
        (self.study / "EXECUTED_PROTOCOL.json").write_text(json.dumps(protocol))
        (self.root / "PROCESS_RECEIPT.json").write_text(json.dumps({"exit_code": 0, "timed_out": False, "child_reaped": True}))
        self.flush()

    def flush(self):
        (self.study / "RESULTS.json").write_text(json.dumps(self.result))
        (self.root / "SOURCE_RECEIPT.json").write_text(json.dumps(self.source))

    def test_unit_fixture_checks_metadata_only_not_checkpoint_or_native_success(self):
        path, result, _, _, _, _ = registered_study(self.root)
        self.assertEqual(path, self.study)
        self.assertEqual(result["seed"], 17)
        self.assertFalse((self.root / "SUMMARY.json").exists())

    def test_smoke_or_other_configuration_is_rejected(self):
        for field, value in (("smoke", True), ("seed", 29), ("width", 64)):
            original = self.result[field]
            self.result[field] = value; self.flush()
            with self.assertRaisesRegex(ValueError, "first registered"):
                registered_study(self.study)
            self.result[field] = original

    def test_missing_draw_and_partial_training_rejected(self):
        arm = self.result["arms"]["hepta_dynamic_risk"]
        arm["evaluation"]["rows"].pop(); self.flush()
        with self.assertRaisesRegex(ValueError, "incomplete"):
            registered_study(self.study)
        arm["evaluation"]["rows"].append({"source": 31, "draw": 1})
        arm["training"]["actual_episodes"] = 511; self.flush()
        with self.assertRaisesRegex(ValueError, "incomplete"):
            registered_study(self.study)

    def test_changed_source_receipt_rejected_even_if_flag_claims_unchanged(self):
        self.source["after"]["commit"] = "b" * 40; self.flush()
        with self.assertRaisesRegex(ValueError, "completed frozen"):
            registered_study(self.study)


if __name__ == "__main__":
    unittest.main()
