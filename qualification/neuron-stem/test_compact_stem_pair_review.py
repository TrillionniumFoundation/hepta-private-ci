"""Fixture-only negative and fairness tests; no pretrained model result."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from compact_stem_trial import STEMS
from compact_stem_pair_review import compare
from qualified_eval import digest


def dataset():
    parts = ("train", "train", "calibration", "test", "future", "ood")
    return [{"case_id": f"p-{i}", "group_id": f"g-{i}",
             "task_id": "classify", "scope_id": "scope-a",
             "split": split, "language": "en", "state": f"unique state {i}",
             "question": f"unique question {i}", "options": ["no", "yes"],
             "label": i % 2, "event_time": f"2026-0{i + 1}-01T00:00:00Z"}
            for i, split in enumerate(parts)]


def write(path, content, jsonl=False):
    Path(path).write_text(("".join(json.dumps(x, sort_keys=True) + "\n" for x in content)
                           if jsonl else json.dumps(content, sort_keys=True) + "\n"), encoding="utf-8")


def arm(root, name, revision, rows):
    spec = STEMS[name]
    prefix = Path(root) / name
    heads = []
    for suffix in ("", "/frozen-head"):
        packet = []
        for row in rows:
            if row["split"] == "train":
                continue
            packet.append({"case_id": row["case_id"], "scope_id": row["scope_id"],
                           "model_id": name + suffix, "model_revision": revision,
                           "encoder_digest": digest([spec.repository, revision, spec.pooling,
                                                     512, "l2->nearest-even-q24"]),
                           "head_digest": "a" * 64 if not suffix else "b" * 64,
                           "status": "Succeeded", "runtime_generation": 1,
                           "probabilities": [.4, .6], "execution_path": "encoder_warm",
                           "backend_batch_size": 1, "shadow_feature_sha256": digest([name, row["case_id"]])})
        heads.append(packet)
    files = [str(prefix) + ".learned.jsonl", str(prefix) + ".frozen.jsonl"]
    for file, payload in zip(files, heads):
        write(file, payload, jsonl=True)
    manifest = {"schema": "hepta.compact-stem-head-only-shadow.v1",
                "model_id": name, "model_repository": spec.repository, "license": spec.license,
                "model_revision": revision, "pooling": spec.pooling, "feature_width": 384,
                "feature_q24_rounded": True, "trainable_encoder_parameters": 0,
                "trainable_shared_projection_parameters": 0,
                "actual_complete_trainable_head_parameters": 1538,
                "head_parameter_ceiling": 2048, "head_kind": "film",
                "scope_id": "scope-a", "dataset_digest": digest(rows),
                "selected_train_case_digest": digest(["p-0", "p-1"]),
                "training_minibatch_indices_sha256": "c" * 64,
                "shots": 2, "steps": 2, "batch_size": 2, "seed": 11,
                "max_tokens_per_model": 512, "device": "cpu", "threads": 1,
                "truncated_cases": 0, "cross_model_nontruncated_comparability": True,
                "authority": "DENY_ALL", "production_promotion_permitted": False,
                "production_no_change_supplied": False, "independent_future_ndu_verified": False,
                "frozen_head_is_production_no_change": False,
                "publisher_weight_bytes_authenticated": False,
                "model_execution_is_research_backend_only": True,
                "learned_head_sha256": "a" * 64, "frozen_head_sha256": "b" * 64,
                "learned_predictions_sha256": digest(heads[0]),
                "frozen_predictions_sha256": digest(heads[1])}
    manifest_file = str(prefix) + ".manifest.json"
    write(manifest_file, manifest)
    return {"manifest": manifest_file, "learned": files[0], "frozen": files[1]}


class PairReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        rows = dataset()
        self.rows = rows
        self.m = arm(self.temp.name, "mmbert-small", "a" * 40, rows)
        self.g = arm(self.temp.name, "granite-97m-multilingual-r2", "b" * 40, rows)

    def review(self):
        return compare(self.rows, scope_id="scope-a", task_id="classify",
                       mmbert_manifest=self.m["manifest"], mmbert_learned=self.m["learned"],
                       mmbert_frozen=self.m["frozen"], granite_manifest=self.g["manifest"],
                       granite_learned=self.g["learned"], granite_frozen=self.g["frozen"])

    def test_valid_pair_never_promotes_or_selects(self):
        report = self.review()
        self.assertTrue(report["matched_training_and_head_budget"])
        self.assertEqual(report["complete_head_parameters_each"], 1538)
        self.assertFalse(report["production_promotion_permitted"])
        self.assertFalse(report["research_winner_selected"])
        self.assertFalse(report["future_predictions_sealed_before_outcomes"])
        self.assertFalse(report["no_change_prediction_file_supplied"])
        self.assertEqual(report["authority"], "DENY_ALL")
        self.assertIn("granite_learned", report["ood_diagnostics"])

    def test_budget_and_scope_and_truncation_tamper_fail_closed(self):
        original = json.loads(Path(self.g["manifest"]).read_text())
        for key, new in (("actual_complete_trainable_head_parameters", 1800),
                         ("scope_id", "scope-b"),
                         ("truncated_cases", 1),
                         ("authority", "ALLOW"),
                         ("trainable_shared_projection_parameters", 200)):
            modified = copy.deepcopy(original)
            modified[key] = new
            write(self.g["manifest"], modified)
            with self.subTest(field=key), self.assertRaises(ValueError):
                self.review()
        write(self.g["manifest"], original)

    def test_modified_prediction_and_feature_controls_are_detected(self):
        pkt = [json.loads(line) for line in Path(self.g["learned"]).read_text().splitlines()]
        pkt[0]["probabilities"] = [.9, .1]
        write(self.g["learned"], pkt, jsonl=True)
        with self.assertRaisesRegex(ValueError, "prediction packet hash mismatch"):
            self.review()
        manifest = json.loads(Path(self.g["manifest"]).read_text())
        manifest["learned_predictions_sha256"] = digest(pkt)
        write(self.g["manifest"], manifest)
        with self.assertRaises(ValueError):
            pkt[0]["shadow_feature_sha256"] = "d" * 64
            write(self.g["learned"], pkt, jsonl=True)
            manifest["learned_predictions_sha256"] = digest(pkt)
            write(self.g["manifest"], manifest)
            self.review()


if __name__ == "__main__":
    unittest.main()
