"""Pure-Python L1 assembly tests; synthetic logits are NOT model evidence."""
import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from decision_421m import SOURCES, input_fingerprint
from decision_arm_bundle import assemble, sha256_file


class DecisionArmBundleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.dataset = {}
        for split in ("train", "calibration", "held_out", "future_1",
                      "future_2", "ood"):
            for i in range(2):
                case = split + str(i)
                self.dataset[case] = {
                    "sample_id": case, "source_group": case,
                    "episode_id": case, "split": split, "label": i,
                    "scope": "authorized", "language": "en",
                    "state": "state " + case, "question": "choose?",
                    "options": ["first", "second"],
                    "event_time": "2026-01-01T00:00:00Z",
                }
        self.plan = {
            "checkpoints": {
                model: {
                    "sha256": hashlib.sha256(model.encode()).hexdigest(),
                    "upstream_revision": "a" * 40,
                } for model in SOURCES
            },
            "dataset_sha256": "b" * 64,
            "training_sample_groups_sha256": "c" * 64,
            "device": "cpu", "dtype": "fp32",
            "batch_size": 16, "context_tokens": 512,
            "seed": 7347, "train_steps": 100,
            "trainable_parameter_budget": 262144,
            "input_contract": "state_question_all_ordered_options",
            "classes": 2,
        }
        self.entries = []
        for model in sorted(SOURCES):
            arm = model + ":equal_budget"
            weights = hashlib.sha256((arm + "weights").encode()).hexdigest()
            pred_file = self.root / (model + ".jsonl")
            with pred_file.open("x", encoding="utf-8") as f:
                for sid, row in self.dataset.items():
                    if row["split"] == "train":
                        continue
                    f.write(json.dumps({
                        "arm": arm, "sample_id": sid,
                        "input_digest": input_fingerprint(row),
                        "logits": [1.5, -.5], "weights_sha256": weights,
                        "latency_ms": 1.25,
                    }, sort_keys=True) + "\n")
            run = {
                "arm": arm,
                "model_source": SOURCES[model][0],
                "checkpoint_sha256": self.plan["checkpoints"][model]["sha256"],
                "upstream_revision": "a" * 40,
                "dataset_sha256": "b" * 64,
                "training_sample_groups_sha256": "c" * 64,
                "runtime_profile": {"device": "cpu", "dtype": "fp32",
                                    "batch_size": 16, "context_tokens": 512},
                "seed": 7347,
                "truncated_input_count": 0,
                "input_contract": self.plan["input_contract"],
                "production_promotion_permitted": False,
                "weights_sha256": weights,
                "trainable_parameters": 250000,
                "train_steps": 100,
                "training_split": "train",
                "optimizer": "adamw",
                "output_predictions_sha256": sha256_file(pred_file),
            }
            if model in ("deberta_v3_large", "modernbert_large"):
                run.update({
                    "schema": "hepta.stem-cell-actual-hf-joint-decision.v1",
                    "runner_source_sha256": sha256_file(
                        Path(__file__).with_name("hf_joint_decision_runner.py")),
                    "verified_encoder_loading": {
                        "schema": "hepta.local-hf-encoder-weight-load.v1",
                        "complete": True,
                        "missing_keys": 0, "unexpected_keys": 0,
                        "mismatched_keys": 0, "error_msgs": 0,
                    },
                    "verified_exact_tensor_materialization": {
                        "schema": "hepta.local-hf-exact-tensor-materialization.v1",
                        "complete": True,
                        "all_state_dict_tensors_compared": True,
                        "tensor_count": 1, "tensor_elements": 1,
                        "safetensors_shards": 1,
                        "production_authorization": False,
                    },
                    "checkpoint_and_dataset_reverified_before_scoring_output": True,
                    "pretrained_typed_decision_head_existed": False,
                    "checkpoint_zero_shot_score_emitted": False,
                })
            meta = self.root / (model + ".run.json")
            meta.write_text(json.dumps(run, sort_keys=True))
            self.entries.append({
                "arm": arm,
                "prediction_path": pred_file.name,
                "run_manifest_path": meta.name,
            })

    def build(self, entries=None):
        return assemble(self.plan, self.root,
                        self.entries if entries is None else entries,
                        self.dataset, "equal_budget")

    def test_four_real_arm_files_are_byte_paired_but_not_authorized(self):
        runs, logits, receipt = self.build()
        self.assertEqual(len(runs), 4)
        self.assertEqual(len(logits), 4 * 10)
        self.assertEqual(receipt["comparison_scope"], "equal_budget")
        self.assertEqual(receipt["paired_sample_count_per_arm"], 10)
        self.assertFalse(receipt["complete_checkpoint_comparison"])
        self.assertFalse(receipt["owner_signatures_verified"])
        self.assertFalse(receipt["production_promotion_permitted"])

    def test_mutated_predictions_cannot_inherit_prior_run_digest(self):
        bad = self.root / self.entries[0]["prediction_path"]
        bad.write_text(bad.read_text() + " \n")
        with self.assertRaisesRegex(ValueError, "bind prediction bytes"):
            self.build()

    def test_rehashed_model_generated_gold_label_still_rejected(self):
        first = self.entries[0]
        pred_file = self.root / first["prediction_path"]
        data = [json.loads(line) for line in pred_file.read_text().splitlines()]
        data[0]["label"] = 0
        pred_file.write_text(
            "".join(json.dumps(row, sort_keys=True) + "\n" for row in data))
        meta_file = self.root / first["run_manifest_path"]
        run = json.loads(meta_file.read_text())
        run["output_predictions_sha256"] = sha256_file(pred_file)
        meta_file.write_text(json.dumps(run))
        with self.assertRaisesRegex(ValueError, "outcome or authority"):
            self.build()

    def test_partial_duplicate_and_cross_root_files_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "one execution"):
            self.build(self.entries[:-1])
        duplicate = copy.deepcopy(self.entries)
        duplicate[-1] = duplicate[0]
        with self.assertRaisesRegex(ValueError, "duplicate or extra"):
            self.build(duplicate)
        invalid = copy.deepcopy(self.entries)
        invalid[0]["prediction_path"] = "../outside.jsonl"
        with self.assertRaisesRegex(ValueError, "strictly relative"):
            self.build(invalid)
        fake = copy.deepcopy(self.entries)
        fake[0]["run_manifest_path"] = "/tmp/foreign.json"
        with self.assertRaisesRegex(ValueError, "strictly relative"):
            self.build(fake)

    def test_rehashed_source_input_mismatch_is_still_rejected(self):
        item = self.entries[0]
        prediction = self.root / item["prediction_path"]
        rows = [json.loads(line) for line in prediction.read_text().splitlines()]
        rows[0]["input_digest"] = "f" * 64
        prediction.write_text(
            "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows))
        manifest_path = self.root / item["run_manifest_path"]
        run = json.loads(manifest_path.read_text())
        run["output_predictions_sha256"] = sha256_file(prediction)
        manifest_path.write_text(json.dumps(run))
        with self.assertRaisesRegex(ValueError, "source/options digest"):
            self.build()

    def test_model_source_and_token_envelope_are_bound(self):
        item = self.entries[0]
        manifest = self.root / item["run_manifest_path"]
        document = json.loads(manifest.read_text())
        document["model_source"] = "different/provider"
        manifest.write_text(json.dumps(document))
        with self.assertRaisesRegex(ValueError, "immutable model/data plan"):
            self.build()
        document["model_source"] = SOURCES[item["arm"].split(":")[0]][0]
        manifest.write_text(json.dumps(document))
        prediction = self.root / item["prediction_path"]
        rows = [json.loads(line) for line in prediction.read_text().splitlines()]
        rows[0]["token_count"] = 513
        prediction.write_text(
            "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows))
        document["output_predictions_sha256"] = sha256_file(prediction)
        manifest.write_text(json.dumps(document))
        with self.assertRaisesRegex(ValueError, "token budget"):
            self.build()

    def test_hf_runner_cannot_claim_success_without_complete_pretrained_weights(self):
        entry = next(row for row in self.entries
                     if row["arm"] == "deberta_v3_large:equal_budget")
        path = self.root / entry["run_manifest_path"]
        original = json.loads(path.read_text())
        for field, replacement in (
                ("runner_source_sha256", "0" * 64),
                ("verified_encoder_loading", {
                    **original["verified_encoder_loading"], "missing_keys": 1,
                }),
                ("checkpoint_zero_shot_score_emitted", True),
                ("checkpoint_and_dataset_reverified_before_scoring_output", False),
                ("verified_exact_tensor_materialization", {
                    **original["verified_exact_tensor_materialization"],
                    "all_state_dict_tensors_compared": False,
                })):
            forged = copy.deepcopy(original)
            forged[field] = replacement
            path.write_text(json.dumps(forged))
            with self.assertRaisesRegex(ValueError, "audited safetensors"):
                self.build()
        path.write_text(json.dumps(original))

    def test_model_cannot_mark_research_as_production(self):
        item = self.entries[0]
        manifest = self.root / item["run_manifest_path"]
        receipt = json.loads(manifest.read_text())
        receipt["production_promotion_permitted"] = True
        manifest.write_text(json.dumps(receipt))
        with self.assertRaisesRegex(ValueError, "immutable model/data plan"):
            self.build()


if __name__ == "__main__":
    unittest.main()
