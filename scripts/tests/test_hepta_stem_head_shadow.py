"""Offline Head smoke tests; fixture performance is NOT Encoder evidence."""

import importlib.util
import json
from pathlib import Path
import tempfile
from datetime import datetime, timedelta, timezone
import unittest

SOURCE = Path(__file__).resolve().parents[1] / "hepta-stem-head-shadow.py"
SPEC = importlib.util.spec_from_file_location("headshadow", SOURCE)
assert SPEC and SPEC.loader
MOD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MOD)


def now_plus(seconds):
    return (datetime.now(timezone.utc) + timedelta(
        seconds=seconds
    )).isoformat().replace("+00:00", "Z")


def packet(case, split, label=None, *, group=None, fence=2, width=384):
    row = {
        "case_id": case, "scope_id": "demo", "task_id": "binary",
        "encoder_digest": "a" * 64, "model_revision": "b" * 40,
        "tokenizer_digest": "c" * 64, "normalization_digest": "d" * 64,
        "quantization_digest": "e" * 64, "generation": 3, "fence": fence,
        "group_id": group or ("g" + case),
        "feature_q24": [MOD.Q // 2] * width,
        "event_time": now_plus(-120 if split == "train" else -10),
        "label_available_at": now_plus(-90 if split == "train" else 600),
        "split": split,
    }
    if label is not None:
        row["label"] = label
    return row


def cases():
    train = [
        packet("train0", "train", 0),
        packet("train1", "train", 1),
    ]
    predict = [
        packet("pred0", "future"),
        packet("pred1", "future"),
    ]
    return train, predict


class HeadTests(unittest.TestCase):
    def setUp(self):
        self.cutoff = now_plus(-60)
        self.now = now_plus(0)

    def test_complete_head_budget_and_reproducible_weights(self):
        train, predict = cases()
        for budget, count in ((2048, 1923), (8192, 7299), (16384, 13443)):
            with self.subTest(budget=budget):
                a, ap, af = MOD.train(
                    train, predict, budget=budget, seed=9, steps=2,
                    cutoff=self.cutoff, now=self.now,
                )
                b, bp, bf = MOD.train(
                    train, predict, budget=budget, seed=9, steps=2,
                    cutoff=self.cutoff, now=self.now,
                )
                self.assertEqual(a["trainable_head_parameters"], count)
                self.assertEqual(a["head_fp32_parameter_payload_bytes"], count * 4)
                self.assertGreater(
                    a["optimizer_tensor_payload_bytes"], count * 8
                )
                self.assertEqual(
                    a["head_plus_optimizer_tensor_payload_bytes"],
                    a["head_fp32_parameter_payload_bytes"]
                    + a["optimizer_tensor_payload_bytes"],
                )
                self.assertEqual(a["trained_head_sha256"], b["trained_head_sha256"])
                self.assertEqual(a["frozen_head_sha256"], b["frozen_head_sha256"])
                self.assertFalse(a["production_promotion_permitted"])
                self.assertFalse(a["frozen_head_is_production_no_change"])
                self.assertFalse(a["runtime_worker_receipts_verified"])
                self.assertEqual(len(ap), 2)
                self.assertTrue(all("label" not in row for row in ap))
                self.assertEqual(
                    [row["head_digest"] for row in ap],
                    [row["head_digest"] for row in bp],
                )

    def test_reject_future_labels_and_stale_fence(self):
        train, predict = cases()
        predict[0]["label"] = 1
        with self.assertRaisesRegex(ValueError, "heldout labels forbidden"):
            MOD.validate_packets(train, predict, self.cutoff, self.now)
        predict[0].pop("label")
        predict[0]["fence"] = 3
        with self.assertRaisesRegex(ValueError, "generation/fence"):
            MOD.validate_packets(train, predict, self.cutoff, self.now)

    def test_group_leak_bad_shape_and_late_train_label(self):
        train, predict = cases()
        predict[0]["group_id"] = train[0]["group_id"]
        with self.assertRaisesRegex(ValueError, "leakage"):
            MOD.validate_packets(train, predict, self.cutoff, self.now)
        predict[0]["group_id"] = "new"
        predict[0]["feature_q24"] = predict[0]["feature_q24"][:-1]
        with self.assertRaisesRegex(ValueError, "feature dimension"):
            MOD.validate_packets(train, predict, self.cutoff, self.now)
        predict[0]["feature_q24"] = [0] * 384
        train[0]["label_available_at"] = now_plus(300)
        with self.assertRaisesRegex(ValueError, "train label after cutoff"):
            MOD.validate_packets(train, predict, self.cutoff, self.now)

    def test_no_momentum_sgd_can_omit_adamw_optimizer_state(self):
        train, predict = cases()
        adam, _, _ = MOD.train(
            train, predict, budget=8192, seed=3, steps=2,
            cutoff=self.cutoff, now=self.now, optimizer_kind="adamw",
        )
        sgd, _, _ = MOD.train(
            train, predict, budget=8192, seed=3, steps=2,
            cutoff=self.cutoff, now=self.now, optimizer_kind="sgd",
        )
        self.assertGreater(adam["optimizer_tensor_payload_bytes"], 0)
        self.assertEqual(sgd["optimizer_tensor_payload_bytes"], 0)
        self.assertEqual(
            adam["trainable_head_parameters"],
            sgd["trainable_head_parameters"],
        )
        self.assertEqual(sgd["optimizer_kind"], "sgd")
        self.assertFalse(sgd["production_promotion_permitted"])

    def test_bad_json_and_oversized_cohorts_rejected(self):
        train, predict = cases()
        with self.assertRaisesRegex(ValueError, "bounded experimental limit"):
            MOD.validate_packets(
                train * 4097, predict, self.cutoff, self.now,
            )
        with tempfile.TemporaryDirectory() as folder:
            malformed = Path(folder) / "bad.jsonl"
            malformed.write_text('{"case_id":"one","case_id":"two"}\n', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "duplicate JSON key"):
                MOD.read_rows(malformed)

    def test_cli_outputs_and_refuses_overwrite(self):
        train, predict = cases()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name, rows in (("train", train), ("predict", predict)):
                (root / f"{name}.jsonl").write_text(
                    "".join(json.dumps(row) + "\n" for row in rows),
                    encoding="utf-8",
                )
            args = [
                "--train", str(root / "train.jsonl"),
                "--predict", str(root / "predict.jsonl"),
                "--train-cutoff", self.cutoff, "--steps", "2",
                "--output-prefix", str(root / "exp"),
            ]
            self.assertEqual(MOD.main(args), 0)
            self.assertTrue((root / "exp.manifest.json").exists())
            manifest = json.loads((root / "exp.manifest.json").read_text())
            import hashlib

            for stem in ("learned", "frozen"):
                self.assertEqual(
                    manifest[stem + "_predictions_sha256_unverified"],
                    hashlib.sha256(
                        (root / ("exp." + stem + ".jsonl")).read_bytes()
                    ).hexdigest(),
                )
            self.assertTrue(manifest["manifest_written_after_prediction_files"])
            self.assertFalse(
                manifest["prediction_file_hashes_cryptographically_signed"]
            )
            learned = [
                json.loads(line) for line in
                (root / "exp.learned.jsonl").read_text().splitlines()
            ]
            self.assertEqual(len(learned), 2)
            self.assertEqual(MOD.main(args), 2)


if __name__ == "__main__":
    unittest.main()
