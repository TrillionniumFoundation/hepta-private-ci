"""Offline material ingress regression: never asserts actual pretrained model quality."""
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import torch

from multimodal_bridge import ContractError, ModalityFeature
from multimodal_alignment_contract import canonical, load_pinned_jsonl, parse_source, sha
from multimodal_real_encoder import (
    PROFILE_SCHEMA, RECEIPT_SCHEMA, feature_rows, run_offline, validated_profile,
    write_jsonl_new,
)


def pin(name):
    return hashlib.sha256(name.encode()).hexdigest()


def profile(width=2, normalize="none", batch_size=3):
    snapshot = {"revision": "a" * 40, "kind": "encoder",
                "files": {"config.json": pin("config"), "model.safetensors": pin("weights"),
                          "tokenizer.json": pin("tokenizer")}}
    raw = {"schema": PROFILE_SCHEMA, "candidate": "mmbert-small-reference-not-weights",
           "snapshot": snapshot, "expected_width": width, "maximum_tokens": 512,
           "batch_size": batch_size, "pooling": "attention-mask-mean",
           "normalization": normalize}
    return validated_profile(raw, sha(canonical(raw))), raw


def train_rows():
    rows = []
    for i in range(8):
        source = ModalityFeature.from_vector("image", pin(f"image-{i}"), pin("frozen-image"),
                                            (float(i) / 10, 0.2))
        rows.append({"case_id": f"t{i}", "group_id": f"g{i//4}", "scope": "scopeA",
                     "observed_at": i, "split": "train",
                     "target_text": f"training phrase {i}",
                     "source": {"modality": source.modality,
                                "input_sha256": source.input_sha256,
                                "encoder_sha256": source.encoder_sha256,
                                "values": list(source.values)}})
    return rows


def future_rows():
    return [{"case_id": f"f{i}", "group_id": f"future-{i}", "scope": "scopeA",
             "observed_at": i + 100, "split": "future",
             "target_text": f"future phrase {i}",
             "source_input_sha256": pin(f"future-source-{i}")} for i in range(3)]


class FakeBackend:
    def __init__(self, identity):
        self.identity = identity
        self.forward_calls = 0
        self.texts = []
        self.variant = "normal"

    def encode(self, texts):
        self.texts.extend(texts)
        self.forward_calls += 1
        if self.variant == "double":
            self.forward_calls += 1
        if self.variant == "none":
            return None
        if self.variant == "wrong-dtype":
            return torch.ones((len(texts), 2), dtype=torch.float64)
        if self.variant == "wrong-width":
            return torch.ones((len(texts), 3), dtype=torch.float32)
        if self.variant == "nan":
            return torch.full((len(texts), 2), float("nan"))
        if self.variant == "zero":
            return torch.zeros((len(texts), 2))
        return torch.tensor([[len(t)/100, sum(ord(c) for c in t) % 23 / 100]
                             for t in texts], dtype=torch.float32)


class EncoderIngressTests(unittest.TestCase):
    def setUp(self):
        self.config, self.raw = profile()
        self.backend = FakeBackend(self.config.snapshot_digest)

    def test_train_rows_were_physically_forwarded_and_match_v1(self):
        inp = train_rows()
        out, receipt = feature_rows(inp, "train", self.backend, self.config)
        self.assertEqual(len(out), 8)
        self.assertEqual((receipt["batches"], self.backend.forward_calls), (3, 3))
        self.assertEqual(receipt["schema"], RECEIPT_SCHEMA)
        self.assertFalse(receipt["model_checkpoint_locally_verified"])
        self.assertFalse(receipt["production_accepted"])
        self.assertIsNone(receipt["physical_forwards"])
        self.assertTrue(all("target_text" not in row for row in out))
        for row in out:
            source, target = parse_source(row, paired=True)
            self.assertEqual((source.scope, source.source.modality, target.modality),
                             ("scopeA", "image", "text"))
            self.assertEqual(target.encoder_sha256, receipt["feature_encoder_identity"])
        self.assertEqual(inp, train_rows())  # never mutates supplied records

    def test_evaluator_target_rows_only_and_no_source_values(self):
        out, receipt = feature_rows(future_rows(), "future_targets", self.backend, self.config)
        self.assertEqual(len(out), 3)
        self.assertEqual(receipt["batches"], 1)
        for row in out:
            self.assertEqual(set(row), {"case_id", "group_id", "scope", "observed_at",
                                        "split", "source_input_sha256", "target"})
            self.assertEqual(row["target"]["modality"], "text")
        self.assertTrue(all("target_text" not in r for r in out))

    def test_stem_identity_changes_with_model_or_pooling_or_norm(self):
        rows = train_rows()
        other, _ = profile(normalize="unit_l2")
        orig, receipt = feature_rows(rows, "train", self.backend, self.config)
        alternate = FakeBackend(other.snapshot_digest)
        changed, changed_receipt = feature_rows(rows, "train", alternate, other)
        self.assertNotEqual(receipt["feature_encoder_identity"], changed_receipt["feature_encoder_identity"])
        self.assertNotEqual(orig[0]["target"]["encoder_sha256"], changed[0]["target"]["encoder_sha256"])
        self.assertAlmostEqual(sum(v*v for v in changed[0]["target"]["values"]), 1, places=6)
        alt = FakeBackend(pin("different-weights-snapshot"))
        _, different = feature_rows(rows, "train", alt, self.config)
        self.assertNotEqual(receipt["feature_encoder_identity"], different["feature_encoder_identity"])

    def test_zero_norm_must_reject_not_silently_patch(self):
        config, _ = profile(normalize="unit_l2")
        backend = FakeBackend(config.snapshot_digest)
        backend.variant = "zero"
        with self.assertRaises(ContractError):
            feature_rows(train_rows(), "train", backend, config)

    def test_no_fallback_on_model_failure_or_wrong_shapes(self):
        for problem in ("none", "wrong-dtype", "wrong-width", "nan", "double"):
            with self.subTest(problem=problem):
                backend = FakeBackend(self.config.snapshot_digest)
                backend.variant = problem
                with self.assertRaises(ContractError):
                    feature_rows(train_rows(), "train", backend, self.config)

    def test_nonfinite_or_out_of_range_features_fail_not_clip(self):
        class Over(FakeBackend):
            def encode(self, texts):
                self.forward_calls += 1
                return torch.full((len(texts), 2), 9., dtype=torch.float32)
        with self.assertRaises(ContractError):
            feature_rows(train_rows(), "train", Over(self.config.snapshot_digest), self.config)

    def test_model_ingress_declines_fake_counter_and_empty_digest(self):
        fake = FakeBackend("0" * 64)
        with self.assertRaises(ContractError):
            feature_rows(train_rows(), "train", fake, self.config)
        fake.identity = self.config.snapshot_digest
        fake.forward_calls = None
        with self.assertRaises(ContractError):
            feature_rows(train_rows(), "train", fake, self.config)

    def test_train_source_must_be_nontext_and_one_encoder(self):
        for mutate in (lambda rows: rows[0].update(source={**rows[0]["source"], "modality": "text"}),
                       lambda rows: rows[0].update(source={**rows[0]["source"], "encoder_sha256": pin("other")}),
                       lambda rows: rows[0].update(scope="scopeOther")):
            rows = train_rows()
            mutate(rows)
            with self.subTest(rows=rows[0]), self.assertRaises(ContractError):
                feature_rows(rows, "train", self.backend, self.config)
        self.assertEqual(self.backend.forward_calls, 0)

    def test_phase_cannot_read_future_targets_as_train(self):
        with self.assertRaises(ContractError):
            feature_rows(future_rows(), "train", self.backend, self.config)
        with self.assertRaises(ContractError):
            feature_rows(train_rows(), "future_targets", self.backend, self.config)

    def test_duplicate_cases_wrong_time_and_invalid_text_fail(self):
        for field, value in (("case_id", "t1"), ("observed_at", -1), ("target_text", ""),
                             ("target_text", "too-long-" * 1100)):
            rows = train_rows()
            rows[0][field] = value
            with self.subTest(field=field), self.assertRaises(ContractError):
                feature_rows(rows, "train", self.backend, self.config)
        self.assertEqual(self.backend.forward_calls, 0)

    def test_training_minimum_and_group_independence(self):
        with self.assertRaises(ContractError):
            feature_rows(train_rows()[:7], "train", self.backend, self.config)
        rows = train_rows()
        for row in rows:
            row["group_id"] = "same-group"
        with self.assertRaises(ContractError):
            feature_rows(rows, "train", self.backend, self.config)

    def test_profile_rejects_wrong_pooling_snapshot_kind_and_width(self):
        variants = (
            ("pooling", "cls"), ("expected_width", 768),
            ("maximum_tokens", 65536), ("candidate", "invalid label"),
            ("normalization", "unverified-standardization"),
        )
        for name, value in variants:
            with self.subTest(name=name):
                raw = {**self.raw, name: value}
                with self.assertRaises(ContractError):
                    validated_profile(raw, sha(canonical(raw)))
        raw = {**self.raw, "snapshot": {**self.raw["snapshot"], "kind": "causal_lm"}}
        with self.assertRaises(ContractError):
            validated_profile(raw, sha(canonical(raw)))

    def test_wrong_profile_digest_rejects_before_any_model_use(self):
        with self.assertRaises(ContractError):
            validated_profile(self.raw, pin("wrong-profile"))
        self.assertEqual(self.backend.forward_calls, 0)

    def test_profile_in_memory_tamper_is_rejected(self):
        config, _ = profile()
        config.snapshot["files"]["model.safetensors"] = pin("tamper")
        with self.assertRaises(ContractError):
            feature_rows(train_rows(), "train", self.backend, config)

    def test_identity_depends_on_exact_target_text(self):
        rows = train_rows()
        out, _ = feature_rows(rows, "train", FakeBackend(self.config.snapshot_digest), self.config)
        rows[0]["target_text"] = rows[0]["target_text"].upper()
        changed, _ = feature_rows(rows, "train", FakeBackend(self.config.snapshot_digest), self.config)
        self.assertNotEqual(out[0]["target"]["input_sha256"], changed[0]["target"]["input_sha256"])

    def test_new_ingress_is_byte_compatible_with_sealed_v1_stages(self):
        from multimodal_alignment import train, predict
        from multimodal_alignment_evaluator import evaluate
        train_material, receipt = feature_rows(
            train_rows(), "train", FakeBackend(self.config.snapshot_digest), self.config)
        fit = train(train_material, sha(b"".join(canonical(row) for row in train_material)))
        future_raw = future_rows()
        future_targets, independent_receipt = feature_rows(
            future_raw, "future_targets", FakeBackend(self.config.snapshot_digest), self.config)
        self.assertEqual(receipt["feature_encoder_identity"],
                         independent_receipt["feature_encoder_identity"])
        future_sources = []
        for i, row in enumerate(future_raw):
            source = ModalityFeature.from_vector(
                "image", row["source_input_sha256"], pin("frozen-image"),
                (float(i) / 10, 0.2))
            future_sources.append({"case_id": row["case_id"], "group_id": row["group_id"],
                                   "scope": row["scope"], "observed_at": row["observed_at"],
                                   "split": "future", "source": {
                                       "modality": source.modality,
                                       "input_sha256": source.input_sha256,
                                       "encoder_sha256": source.encoder_sha256,
                                       "values": list(source.values)}})
        # Producer sees only source features, never held-out target text/labels.
        self.assertTrue(all("target_text" not in row and "target" not in row
                            for row in future_sources))
        predictions = predict(fit, future_sources,
                              sha(canonical(fit)), sha(b"".join(canonical(row) for row in future_sources)))
        result = evaluate(predictions, future_targets,
                          sha(canonical(predictions)),
                          sha(b"".join(canonical(row) for row in future_targets)))
        self.assertEqual(result["arms"]["fitted"]["cases"], 3)
        self.assertFalse(result["measured_real_model_capability"])
        self.assertFalse(result["production_accepted"])

    def test_jsonl_writer_is_create_only_and_reloads_pinned(self):
        out, _ = feature_rows(future_rows(), "future_targets", self.backend, self.config)
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)/"future-targets.jsonl"
            digest = write_jsonl_new(path, out)
            loaded, returned = load_pinned_jsonl(path, digest)
            self.assertEqual(returned, digest)
            self.assertEqual(loaded, out)
            with self.assertRaises(FileExistsError):
                write_jsonl_new(path, out)
            with self.assertRaises(ContractError):
                load_pinned_jsonl(path, pin("wrong"))

    def test_evaluator_and_train_cli_entrypoints_are_independent(self):
        from multimodal_real_encoder import main as train_main
        from multimodal_real_encoder_evaluator import main as eval_main
        self.assertNotEqual(train_main, eval_main)

    def test_cli_missing_model_material_does_not_make_output(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            p = root / "profile.json"
            p.write_bytes(canonical(self.raw))
            data = root / "data.jsonl"
            data.write_bytes(b"".join(canonical(row) for row in train_rows()))
            target = root / "encoded"
            with self.assertRaises((FileNotFoundError, OSError, ValueError, ImportError)):
                run_offline(p, sha(p.read_bytes()), root / "missing-model",
                            data, sha(data.read_bytes()), target, "train")
            self.assertFalse(target.exists())


if __name__ == "__main__":
    unittest.main()
