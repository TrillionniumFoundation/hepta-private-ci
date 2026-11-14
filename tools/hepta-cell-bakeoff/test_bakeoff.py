import json
import io
import base64
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from contextlib import contextmanager, redirect_stderr
from unittest import mock

import bakeoff
import run_live
import retrieval


def h64(c):
    return c * 64


def h40(c):
    return c * 40



@contextmanager
def replace_after_first_read(replacements):
    """Ordinary small-file fixture: replace each path after its first read returns."""
    real_open = Path.open
    replaced = set()

    class Reader:
        def __init__(self, source, path):
            self.source, self.path = source, path

        def __enter__(self):
            self.source.__enter__()
            return self

        def __exit__(self, *args):
            return self.source.__exit__(*args)

        def read(self, *args, **kwargs):
            value = self.source.read(*args, **kwargs)
            if self.path not in replaced:
                with real_open(self.path, "wb") as target:
                    target.write(replacements[self.path])
                replaced.add(self.path)
            return value

    def opening(path, *args, **kwargs):
        source = real_open(path, *args, **kwargs)
        mode = args[0] if args else kwargs.get("mode", "r")
        if path in replacements and path not in replaced and "r" in mode:
            return Reader(source, path)
        return source

    with mock.patch.object(Path, "open", opening):
        yield replaced

class BakeoffTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.data = []
        for n, split in enumerate(bakeoff.SPLITS):
            for j in range(8):
                self.data.append({"id": f"{split}-{j}", "source_group": f"s{n}-{j}",
                                  "split": split, "timestamp": (n + 1) * 100 + j,
                                  "language": "en" if j % 2 else "zh", "task_family": "routing", "ood": j == 7,
                                  "label": "yes" if j % 2 else "no", "options": ["yes", "no"]})
        self.dataset_file = self.folder / "gold.jsonl"
        self._write(self.dataset_file, self.data)
        self.models = []
        for i, name in enumerate(bakeoff.MODEL_NAMES):
            model = {"name": name, "kind": "encoder-head" if i >= 3 else "typed",
                     "repo": "owner/model", "revision": h40('a'), "weights_sha256": h64('b'),
                     "tokenizer_sha256": h64('c'), "runtime_sha256": h64('d'),
                     "head_sha256": h64('e'), "license_review": "approved",
                     "parameters": 421000000 if i < 2 else 270000000,
                     "head_steps": 100, "head_seed": 42, "head_optimizer": "sgd", "head_lr": 0.1,
                     "train_data_sha256": h64('f')}
            self.models.append(model)
        self.plan = {"schema": bakeoff.SCHEMA, "baseline": "laya-english",
                     "source_head": h40('f'), "dataset_sha256": bakeoff.digest(self.dataset_file),
                     "threshold": 0.6, "registered_before_utc": "2026-10-22T00:00:00Z", "models": self.models}
        self.preds = []
        for name in bakeoff.MODEL_NAMES:
            for row in self.data:
                if row["split"] == "train":
                    continue
                p = 0.9 if row["label"] == "yes" else 0.1
                self.preds.append({"model": name, "id": row["id"], "revision": h40('a'),
                                   "weights_sha256": h64('b'), "probabilities": {"yes": p, "no": 1-p},
                                   "abstain": row["ood"], "latency_ms": 2.5,
                                   "origin": "live-model-observation"})
        self.pred_file = self.folder / "pred.jsonl"
        self._write(self.pred_file, self.preds)

    def _write(self, path, items):
        path.write_text("".join(json.dumps(x) + "\n" for x in items), encoding="utf-8")

    def test_blind_input_rejects_gold_leakage(self):
        path = self.folder / "blind.jsonl"
        self._write(path, [{"id": "s1", "split": "future_1", "state": "x",
                            "options": ["yes", "no"], "label": "yes"}])
        with self.assertRaisesRegex(bakeoff.EvidenceError, "gold or unknown"):
            run_live.blind_rows(path)

    def test_local_model_files_fail_on_tamper(self):
        root = self.folder / "weights"
        root.mkdir()
        weight = root / "weights.safetensors"
        weight.write_bytes(b"some offline fixture")
        inventory = {"weights.safetensors": bakeoff.digest(weight)}
        expected = __import__("hashlib").sha256(json.dumps(list(inventory.items()),
                         separators=(",", ":")).encode("ascii")).hexdigest()
        entry = {"files_sha256": inventory, "weights_sha256": expected}
        self.assertEqual(run_live.verified_local_model(root, entry), root)
        weight.write_bytes(b"tampered")
        with self.assertRaisesRegex(bakeoff.EvidenceError, "artifact mismatch"):
            run_live.verified_local_model(root, entry)

    def test_valid_offline_score_does_not_mint_qualification(self):
        report = bakeoff.evaluate(bakeoff.load_plan(self._plan_file()), self.dataset_file, self.pred_file)
        self.assertFalse(report["production_qualified"])
        self.assertIn("missing-external-cas-fence-rollback-restart-attestation", report["blockers"])
        self.assertEqual(set(report["scores"]), set(bakeoff.MODEL_NAMES))
        self.assertEqual(set(report["scores"]["laya-english"]), {"future_1", "future_2"})
        self.assertGreater(report["scores"]["laya-english"]["future_1"]["accuracy"], 0.9)

    def _plan_file(self):
        file = self.folder / "plan.json"
        file.write_text(json.dumps(self.plan), encoding="utf-8")
        return file

    def test_unpinned_model_denied(self):
        self.plan["models"][0]["weights_sha256"] = None
        with self.assertRaisesRegex(bakeoff.EvidenceError, "missing weights_sha256"):
            bakeoff.load_plan(self._plan_file())

    def test_unequal_head_budget_denied(self):
        self.plan["models"][-1]["head_steps"] = 99
        with self.assertRaisesRegex(bakeoff.EvidenceError, "equal training budget"):
            bakeoff.load_plan(self._plan_file())

    def test_dataset_digest_tamper_denied(self):
        self.data[0]["label"] = "yes"
        self._write(self.dataset_file, self.data)
        with self.assertRaisesRegex(bakeoff.EvidenceError, "dataset digest mismatch"):
            bakeoff.evaluate(bakeoff.load_plan(self._plan_file()), self.dataset_file, self.pred_file)

    def test_group_leakage_denied(self):
        self.data[-1]["source_group"] = self.data[0]["source_group"]
        with self.assertRaisesRegex(bakeoff.EvidenceError, "source leakage"):
            bakeoff.validate_data(self.data)

    def test_future_time_leakage_denied(self):
        self.data[-1]["timestamp"] = 30
        with self.assertRaisesRegex(bakeoff.EvidenceError, "future_2 not held out"):
            bakeoff.validate_data(self.data)

    def test_missing_prediction_denied(self):
        self.preds.pop()
        self._write(self.pred_file, self.preds)
        with self.assertRaisesRegex(bakeoff.EvidenceError, "missing observations"):
            bakeoff.evaluate(bakeoff.load_plan(self._plan_file()), self.dataset_file, self.pred_file)

    def test_wrong_model_generation_denied(self):
        self.preds[0]["revision"] = h40('1')
        self._write(self.pred_file, self.preds)
        with self.assertRaisesRegex(bakeoff.EvidenceError, "model identity mismatch"):
            bakeoff.evaluate(bakeoff.load_plan(self._plan_file()), self.dataset_file, self.pred_file)

    def test_bad_probability_denied(self):
        self.preds[0]["probabilities"]["yes"] = float("nan")
        self._write(self.pred_file, self.preds)
        with self.assertRaisesRegex(bakeoff.EvidenceError, "invalid probability"):
            bakeoff.evaluate(bakeoff.load_plan(self._plan_file()), self.dataset_file, self.pred_file)

    def test_temperature_only_calibration(self):
        data = bakeoff.validate_data(self.data)
        ps = bakeoff.validate_predictions(self.preds, data, self.plan)["laya-english"]
        ids = [x["id"] for x in self.data if x["split"] == "calibration"]
        t = bakeoff.temperature(ids, data, ps)
        for sample in self.data:
            if sample["split"] == "future_2":
                ps[sample["id"]]["probabilities"] = {"yes": 0.99, "no": 0.01}
        self.assertEqual(t, bakeoff.temperature(ids, data, ps))

    def test_resource_all_scales_rejects_missing(self):
        rows = [{"model": "laya-english", "logical_cells": 64, "active_cells": 1,
                 "cpu_rss_peak_bytes": 123, "gpu_peak_bytes": 0, "throughput_per_sec": 1,
                 "p95_latency_ms": 1, "p99_latency_ms": 2, "load_latency_ms": 3,
                 "host_id": "test", "driver_receipt": "test", "origin": "observed-target-host"}]
        _, blockers = bakeoff.check_resources(rows, self.models)
        self.assertIn("resource-missing-scales:laya-english", blockers)
        self.assertIn("resource-missing-scales:harrier-270m", blockers)

    def test_retrieval_heldout_quality_is_scored_independently(self):
        decision = bakeoff.validate_data(self.data)
        gold = [{"query_id": "q1", "source_group": "ret-1", "split": "future_1",
                 "timestamp": 700, "candidate_ids": ["a", "b"], "relevant": {"a": 3}},
                {"query_id": "q2", "source_group": "ret-2", "split": "future_2",
                 "timestamp": 800, "candidate_ids": ["a", "b"], "relevant": {"b": 1}}]
        rows = [{"model": model, "query_id": gold_row["query_id"], "revision": h40('a'),
                 "weights_sha256": h64('b'), "ranked_ids": [key for key in gold_row["candidate_ids"]
                                                          if key in gold_row["relevant"]] +
                                                          [key for key in gold_row["candidate_ids"]
                                                           if key not in gold_row["relevant"]],
                 "origin": "live-model-observation"}
                for model in retrieval.ENCODERS for gold_row in gold]
        scores, blockers = retrieval.evaluate(gold, rows, self.plan, decision)
        self.assertEqual(scores["arctic-305m"]["future_1"]["ndcg_at_10"], 1.0)
        self.assertEqual(scores["harrier-270m"]["future_2"]["mrr_at_10"], 1.0)
        self.assertIn("retrieval-independent-groups-insufficient:future_1", blockers)
        rows[0]["ranked_ids"] = ["a", "a"]
        with self.assertRaisesRegex(bakeoff.EvidenceError, "invalid retrieval ranking"):
            retrieval.evaluate(gold, rows, self.plan, decision)

    def test_encoder_fit_rejects_future_label_visibility(self):
        gold = self.folder / "training.jsonl"
        self._write(gold, self.data)
        self.models[-1]["train_data_sha256"] = bakeoff.digest(gold)
        with self.assertRaisesRegex(bakeoff.EvidenceError, "fit only permits train rows"):
            run_live.fit_encoder_head(self.models[-1], self.folder, gold, self.folder / "head.json", False)

    def test_unsigned_lifecycle_event_claims_are_blocked(self):
        owners = {"artifact-cas": "learning.artifacts", "generation-fence": "runtime.agentd",
                  "signed-final-use": "kernel.authority", "rollback": "learning.artifacts",
                  "restart-recovery": "runtime.agentd", "old-generation-rejected": "runtime.agentd"}
        events = [{"payload": {"model": model, "event": event, "issuer": issuer,
                               "source_head": self.plan["source_head"], "weights_sha256": h64('b'),
                               "receipt_id": f"{model}-{event}", "generation": 3}}
                  for model in bakeoff.MODEL_NAMES for event, issuer in owners.items()]
        lifecycle = self.folder / "events.jsonl"
        self._write(lifecycle, events)
        report = bakeoff.evaluate(bakeoff.load_plan(self._plan_file()), self.dataset_file,
                                  self.pred_file, lifecycle_path=lifecycle)
        self.assertFalse(report["owner_signature_integrity_verified"])
        self.assertIn("lifecycle-ed25519-key-or-independent-trust-anchor-missing", report["blockers"])
        self.assertFalse(report["production_qualified"])

    @unittest.skipUnless(shutil.which("openssl"), "OpenSSL CLI unavailable")
    def test_ed25519_signature_integrity_and_tampering(self):
        key, public = self.folder / "private.pem", self.folder / "issuer.pub.pem"
        subprocess.run(["openssl", "genpkey", "-algorithm", "ED25519", "-out", str(key)],
                       check=True, capture_output=True)
        subprocess.run(["openssl", "pkey", "-in", str(key), "-pubout", "-out", str(public)],
                       check=True, capture_output=True)
        payload = {"model": "laya-english", "event": "artifact-cas", "issuer": "learning.artifacts",
                   "source_head": self.plan["source_head"], "weights_sha256": h64('b'),
                   "receipt_id": "real-test-signature", "generation": 1}
        message = self.folder / "message.json"
        message.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")), encoding="utf-8")
        signature = self.folder / "signature.bin"
        subprocess.run(["openssl", "pkeyutl", "-sign", "-inkey", str(key), "-rawin",
                        "-in", str(message), "-out", str(signature)], check=True, capture_output=True)
        row = {"payload": payload, "signature_b64": base64.b64encode(signature.read_bytes()).decode("ascii")}
        receipt = self.folder / "signed.jsonl"
        self._write(receipt, [row])
        blockers, verified = bakeoff.check_lifecycle(receipt, self.plan, public, bakeoff.digest(public))
        self.assertTrue(verified)
        self.assertIn("owner-receipt-replay-and-real-world-effect-not-independently-verified", blockers)
        row["payload"]["receipt_id"] = "payload-was-tampered"
        self._write(receipt, [row])
        with self.assertRaisesRegex(bakeoff.EvidenceError, "invalid owner Ed25519 signature"):
            bakeoff.check_lifecycle(receipt, self.plan, public, bakeoff.digest(public))




    def test_paired_interval_ties_match_score_option_order(self):
        row = {**self.data[-1], "id": "tie", "label": "yes", "options": ["yes", "no"]}
        data = {"tie": row}
        base = {"tie": {"probabilities": {"no": 0.5, "yes": 0.5},
                        "abstain": False, "latency_ms": 1}}
        challenger = {"tie": {**base["tie"], "probabilities": {"yes": 0.5, "no": 0.5}}}
        self.assertEqual(bakeoff.score(["tie"], data, base, 1, 0.6)["accuracy"], 1.0)
        self.assertEqual(bakeoff.score(["tie"], data, challenger, 1, 0.6)["accuracy"], 1.0)
        self.assertEqual(bakeoff.paired_interval(["tie"], data, base, challenger, 1, 1),
                         (0.0, 0.0))

    def test_retrieval_future_one_follows_decision_train_and_calibration(self):
        decision = bakeoff.validate_data(self.data)
        gold = [{"query_id": "q1", "source_group": "ret-1", "split": "future_1",
                 "timestamp": 208, "candidate_ids": ["a", "b"], "relevant": {"a": 3}},
                {"query_id": "q2", "source_group": "ret-2", "split": "future_2",
                 "timestamp": 800, "candidate_ids": ["a", "b"], "relevant": {"b": 1}}]
        rows = [{"model": model, "query_id": row["query_id"], "revision": h40('a'),
                 "weights_sha256": h64('b'), "ranked_ids": ["a", "b"],
                 "origin": "live-model-observation"}
                for model in retrieval.ENCODERS for row in gold]
        for timestamp, split in [(107, "train"), (206, "calibration"), (207, "calibration")]:
            with self.subTest(timestamp=timestamp, split=split):
                gold[0]["timestamp"] = timestamp
                with self.assertRaisesRegex(bakeoff.EvidenceError,
                                            f"retrieval future_1 not held out after decision {split}"):
                    retrieval.evaluate(gold, rows, self.plan, decision)
        gold[0]["timestamp"] = 208
        scores, blockers = retrieval.evaluate(gold, rows, self.plan, decision)
        self.assertEqual(scores["arctic-305m"]["future_1"]["ndcg_at_10"], 1.0)
        self.assertIn("retrieval-independent-groups-insufficient:future_1", blockers)

    def _head_declarations(self):
        entry = dict(self.models[-1])
        # Metadata only: these fixtures contain no model or head weight array.
        learned = {"schema": "hepta.cell.bakeoff.head.v1", "model": entry["name"],
                   "revision": entry["revision"], "weights_sha256": entry["weights_sha256"],
                   "train_dataset_sha256": entry["train_data_sha256"],
                   "steps": entry["head_steps"], "seed": entry["head_seed"],
                   "learning_rate": entry["head_lr"], "optimizer": entry["head_optimizer"]}
        return entry, learned

    def test_encoder_head_training_declarations_reject_before_runtime_load(self):
        entry, learned = self._head_declarations()
        head, out = self.folder / "head.json", self.folder / "prediction.jsonl"
        changes = {"train_dataset_sha256": h64('1'), "steps": 101, "seed": 43,
                   "learning_rate": 0.2, "optimizer": "adam"}
        for field, value in changes.items():
            for missing in (False, True):
                with self.subTest(field=field, missing=missing):
                    submitted = dict(learned)
                    if missing:
                        del submitted[field]
                    else:
                        submitted[field] = value
                    head.write_text(json.dumps(submitted), encoding="utf-8")
                    entry["head_sha256"] = bakeoff.digest(head)
                    with mock.patch.dict("sys.modules", {"numpy": None}), \
                         mock.patch.object(run_live, "load_encoder") as load, \
                         self.assertRaisesRegex(bakeoff.EvidenceError,
                                                "encoder head training declaration mismatch"):
                        run_live.run_predictions(entry, self.folder, [], out, head, False)
                    load.assert_not_called()
                    self.assertFalse(out.exists())

    def test_evaluation_rows_and_hashes_use_the_consumed_snapshot(self):
        dataset_sha = bakeoff.digest(self.dataset_file)
        predictions_sha = bakeoff.digest(self.pred_file)
        changed_data = [{**r, "label": "no" if r["label"] == "yes" else "yes"}
                        for r in self.data]
        changed_predictions = [{**r, "probabilities": {"yes": 0.5, "no": 0.5}}
                               for r in self.preds]

        def encode(rows):
            return "".join(json.dumps(row) + "\n" for row in rows).encode("utf-8")

        replacements = {self.dataset_file: encode(changed_data),
                        self.pred_file: encode(changed_predictions)}
        with replace_after_first_read(replacements) as replaced:
            report = bakeoff.evaluate(self.plan, self.dataset_file, self.pred_file)
        self.assertEqual(replaced, set(replacements))
        self.assertEqual(report["dataset_sha256"], dataset_sha)
        self.assertEqual(report["predictions_sha256"], predictions_sha)
        self.assertGreater(report["scores"]["laya-english"]["future_1"]["accuracy"], 0.9)
        self.assertFalse(report["production_qualified"])
        self.assertNotEqual(bakeoff.digest(self.dataset_file), dataset_sha)
        self.assertNotEqual(bakeoff.digest(self.pred_file), predictions_sha)

    def test_head_hash_and_declarations_use_one_read(self):
        entry, learned = self._head_declarations()
        original = {**learned, "steps": entry["head_steps"] + 1}
        head, out = self.folder / "head.json", self.folder / "prediction.jsonl"
        head.write_text(json.dumps(original), encoding="utf-8")
        entry["head_sha256"] = bakeoff.digest(head)
        replacement = json.dumps(learned).encode("utf-8")
        with replace_after_first_read({head: replacement}) as replaced, \
             mock.patch.dict("sys.modules", {"numpy": None}), \
             mock.patch.object(run_live, "load_encoder") as load, \
             self.assertRaisesRegex(bakeoff.EvidenceError,
                                    "encoder head training declaration mismatch"):
            run_live.run_predictions(entry, self.folder, [], out, head, False)
        self.assertEqual(replaced, {head})
        load.assert_not_called()
        self.assertFalse(out.exists())

    def test_fit_train_hash_and_split_validation_use_one_read(self):
        gold = self.folder / "training.jsonl"
        self._write(gold, self.data)
        entry = {**self.models[-1], "train_data_sha256": bakeoff.digest(gold)}
        train_only = [r for r in self.data if r["split"] == "train"]
        replacement = "".join(json.dumps(r) + "\n" for r in train_only).encode("utf-8")
        with replace_after_first_read({gold: replacement}) as replaced, \
             mock.patch.object(run_live, "load_encoder") as load, \
             self.assertRaisesRegex(bakeoff.EvidenceError, "fit only permits train rows"):
            run_live.fit_encoder_head(entry, self.folder, gold, self.folder / "head.json", False)
        self.assertEqual(replaced, {gold})
        load.assert_not_called()
        self.assertFalse((self.folder / "head.json").exists())

    @unittest.skipUnless(shutil.which("openssl"), "OpenSSL CLI unavailable")
    def test_lifecycle_verification_uses_the_fingerprinted_key_bytes(self):
        key, public = self.folder / "private.pem", self.folder / "issuer.pub.pem"
        subprocess.run(["openssl", "genpkey", "-algorithm", "ED25519", "-out", str(key)],
                       check=True, capture_output=True)
        subprocess.run(["openssl", "pkey", "-in", str(key), "-pubout", "-out", str(public)],
                       check=True, capture_output=True)
        fingerprint = bakeoff.digest(public)
        payload = {"model": "laya-english", "event": "artifact-cas", "issuer": "learning.artifacts",
                   "source_head": self.plan["source_head"], "weights_sha256": h64('b'),
                   "receipt_id": "snapshot-fixture", "generation": 1}
        message, signature = self.folder / "message.json", self.folder / "signature.bin"
        message.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")),
                           encoding="utf-8")
        subprocess.run(["openssl", "pkeyutl", "-sign", "-inkey", str(key), "-rawin",
                        "-in", str(message), "-out", str(signature)], check=True, capture_output=True)
        receipt = self.folder / "signed.jsonl"
        self._write(receipt, [{"payload": payload,
                              "signature_b64": base64.b64encode(signature.read_bytes()).decode("ascii")}])
        with replace_after_first_read({public: b"replaced public-key fixture\n"}) as replaced:
            blockers, verified = bakeoff.check_lifecycle(receipt, self.plan, public, fingerprint)
        self.assertEqual(replaced, {public})
        self.assertTrue(verified)
        self.assertIn("owner-receipt-replay-and-real-world-effect-not-independently-verified", blockers)
        self.assertNotEqual(bakeoff.digest(public), fingerprint)

    def test_oversized_public_key_snapshot_is_rejected_before_verifier(self):
        public = self.folder / "oversized.pub.pem"
        public.write_bytes(b"X" * (64 * 1024 + 1))
        receipt = self.folder / "oversized-key-receipt.jsonl"
        self._write(receipt, [{"payload": {
            "model": "laya-english", "event": "artifact-cas", "issuer": "learning.artifacts",
            "source_head": self.plan["source_head"], "weights_sha256": h64("b"),
            "receipt_id": "oversized-key-fixture", "generation": 1,
        }}])
        with mock.patch.object(bakeoff.subprocess, "run") as verify, \
             self.assertRaisesRegex(bakeoff.EvidenceError, "owner public key exceeds 64 KiB"):
            bakeoff.check_lifecycle(receipt, self.plan, public, bakeoff.digest(public))
        verify.assert_not_called()

    def test_prediction_plan_entry_is_validated_from_the_same_read(self):
        invalid = json.loads(json.dumps(self.plan))
        invalid["models"][0]["weights_sha256"] = None
        path = self.folder / "plan.json"
        path.write_text(json.dumps(invalid), encoding="utf-8")
        replacement = json.dumps(self.plan).encode("utf-8")
        argv = ["run_live.py", "predict", "--plan", str(path), "--model", "laya-english",
                "--checkpoint", str(self.folder), "--blind", str(self.folder / "blind.jsonl"),
                "--output", str(self.folder / "out.jsonl")]
        stderr = io.StringIO()
        with replace_after_first_read({path: replacement}) as replaced, \
             mock.patch("sys.argv", argv), \
             mock.patch.object(run_live, "verified_local_model") as verify, \
             mock.patch.object(run_live, "run_predictions") as predict, \
             redirect_stderr(stderr), self.assertRaises(SystemExit) as exited:
            run_live.main()
        self.assertEqual(replaced, {path})
        self.assertEqual(exited.exception.code, 2)
        self.assertIn("missing weights_sha256", stderr.getvalue())
        verify.assert_not_called()
        predict.assert_not_called()


if __name__ == "__main__":
    unittest.main()
