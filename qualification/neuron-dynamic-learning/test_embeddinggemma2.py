"""Contract tests only; no mock output may count as physical model evidence."""
import contextlib
from collections import UserDict
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from embeddinggemma2_shadow import (
    FrozenGemmaShadow, QualificationError, load_manifest, normalize_truncation,
    sha256, validate_sample,
)
from embeddinggemma2_pairs import execute_pairs, paired_cosine_metrics, validate_pairs
from differentiation_gate import DifferentiationError, advisory_gate
from embeddinggemma2_cell_study import run_study, validate_study


def sample(cell="cell.a", text="complete question plus options and state", **kw):
    base = {
        "scope_id": "scope.a", "principal_id": "principal.a",
        "purpose_id": "purpose.decision", "cell_id": cell,
        "generation": 2, "authority_epoch": 5,
        "input": {"modality": "text", "role": "classification", "value": text,
                  "sha256": sha256(text.encode("utf-8"))},
    }
    base.update(kw)
    return base


def pair(case_id, split, group, time, text, media):
    t = sample("text." + case_id, text)
    t["input"]["role"] = "search_query"
    m = sample("media." + case_id)
    m["input"] = {"modality": "image", "role": "document", "value": media,
                  "sha256": sha256(media.encode("utf-8"))}
    return {"case_id": case_id, "group_id": group, "split": split,
            "observed_utc": time, "text": t, "media": m}


def pairs():
    return [pair("a", "test", "g1", "2026-08-01T00:00:00Z", "text a", "a.png"),
            pair("b", "test", "g2", "2026-08-02T00:00:00Z", "text b", "b.png"),
            pair("c", "future", "g3", "2026-09-01T00:00:00Z", "text c", "c.png"),
            pair("d", "future", "g4", "2026-09-02T00:00:00Z", "text d", "d.png")]


class SnapshotAndModality(unittest.TestCase):
    def test_complete_snapshot_identity_and_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            directory = root / "frozen"
            directory.mkdir()
            (directory / "config.json").write_bytes(b"{}")
            (directory / "model.safetensors").write_bytes(b"unit digest only not weights")
            files = {p.name: sha256(p.read_bytes()) for p in directory.iterdir()}
            manifest = {"model_id": "google/embeddinggemma-2", "revision": "a" * 40,
                        "snapshot": "frozen", "files": files, "profile": "text",
                        "dimension": 256, "precision": "float32", "license": "Apache-2.0",
                        "runtime": {k: "1.0.0" for k in
                            ("torch", "transformers", "tokenizers", "safetensors", "sentence-transformers")}}
            path = root / "manifest.json"
            path.write_text(json.dumps(manifest), encoding="utf-8")
            model, snapshot, digest = load_manifest(path)
            self.assertEqual(snapshot, directory)
            self.assertEqual(model["model_id"], "google/embeddinggemma-2")
            self.assertEqual(len(digest), 64)
            for field, bad in (("revision", "main"), ("precision", "float16"),
                               ("dimension", 257), ("license", "unknown")):
                changed = dict(manifest, **{field: bad})
                path.write_text(json.dumps(changed), encoding="utf-8")
                with self.assertRaises(QualificationError):
                    load_manifest(path)
            path.write_text(json.dumps(manifest), encoding="utf-8")
            (directory / "config.json").write_text("tampered", encoding="utf-8")
            with self.assertRaises(QualificationError):
                load_manifest(path)
            (directory / "config.json").write_bytes(b"{}")
            (directory / "unknown").write_bytes(b"extra")
            with self.assertRaises(QualificationError):
                load_manifest(path)
            (directory / "unknown").unlink()
            (directory / "link").symlink_to("config.json")
            with self.assertRaises(QualificationError):
                load_manifest(path)
            (directory / "link").unlink()
            # Model file inventory alone is not sufficient to authorize
            # potentially executable or unsafe Python/pickle weight formats.
            (directory / "unsafe.pt").write_bytes(b"opaque unsafe pickle")
            manifest["files"]["unsafe.pt"] = sha256((directory / "unsafe.pt").read_bytes())
            path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaises(QualificationError):
                load_manifest(path)

    def test_matryoshka_prefix_must_be_renormalized(self):
        raw = [3.0, 4.0] + [0.0] * 766
        vector = normalize_truncation(raw, 256)
        self.assertAlmostEqual(np.linalg.norm(vector), 1.0)
        self.assertEqual(vector[:2], [0.6, 0.8])
        for bad in ([0.0] * 768, [float("nan")] + [0.0] * 767, [1.0] * 512):
            with self.assertRaises(QualificationError):
                normalize_truncation(bad, 256)

    def test_scope_generation_modality_and_media_hash(self):
        a = sample()
        k, p = validate_sample(a, "text", None)
        self.assertEqual(p, a["input"]["value"])
        changed = sample(principal_id="different")
        self.assertNotEqual(k, validate_sample(changed, "text", None)[0])
        changed = sample(authority_epoch=7)
        self.assertNotEqual(k, validate_sample(changed, "text", None)[0])
        with self.assertRaises(QualificationError):
            validate_sample(sample(input={**a["input"], "sha256": "0" * 64}), "text", None)
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            (folder / "media.png").write_bytes(b"image fixture bytes not a decoded image")
            media = sample(input={"modality": "image", "role": "document", "value": "media.png",
                                  "sha256": sha256((folder / "media.png").read_bytes())})
            self.assertIsInstance(validate_sample(media, "vision", folder)[1], dict)
            with self.assertRaises(QualificationError):
                validate_sample(media, "text", folder)
            (folder / "media.png").write_bytes(b"tampered")
            with self.assertRaises(QualificationError):
                validate_sample(media, "vision", folder)
            (folder / "media.png").unlink()
            (folder / "media.png").symlink_to("/etc/hosts")
            with self.assertRaises(QualificationError):
                validate_sample(media, "vision", folder)
            media["input"]["value"] = "https://example.com/media.png"
            with self.assertRaises(QualificationError):
                validate_sample(media, "vision", folder)

    def test_full_text_token_inventory_no_hidden_truncation(self):
        class Tokenizer:
            def __call__(self, content, **kwargs):
                self.calls.append((content, kwargs))
                return UserDict({"input_ids": list(range(self.count))})
            def __init__(self):
                self.count = 11
                self.calls = []
        class Model:
            tokenizer = Tokenizer()
            prompts = {"Classification": "task: classification | query: "}
        shadow = FrozenGemmaShadow.__new__(FrozenGemmaShadow)
        shadow.model = Model()
        shadow._check_full_text_budget("question/options/state", "Classification")
        self.assertFalse(shadow.model.tokenizer.calls[-1][1]["truncation"])
        self.assertTrue(shadow.model.tokenizer.calls[-1][0].startswith("task: classification"))
        shadow.model.tokenizer.count = 8193
        with self.assertRaises(QualificationError):
            shadow._check_full_text_budget("very long", "Classification")
        with self.assertRaises(QualificationError):
            shadow._check_full_text_budget("q", "FakePrompt")

    def test_stub_admission_is_never_physical_evidence(self):
        class Stub:
            def encode(self, payloads, **kwargs):
                output = np.zeros((len(payloads), kwargs["truncate_dim"]), dtype=np.float64)
                output[:, 0] = 1
                return output
        stem = FrozenGemmaShadow.__new__(FrozenGemmaShadow)
        stem.model = Stub()
        stem.manifest = {"profile": "text", "dimension": 256,
                         "revision": "a" * 40}
        stem.profile_digest = "f" * 64
        stem.model_encode_calls = 0
        stem._inference_context = contextlib.nullcontext
        result = stem.encode_cells([sample("cell.a"), sample("cell.b")])
        self.assertEqual(result["distinct_input_rows"], 1)
        self.assertEqual(result["sentence_transformer_encode_calls"], 1)
        self.assertIsNone(result["physical_transformer_forward_calls"])
        self.assertEqual(result["evidence_type"], "deterministic_stub_contract_only")
        self.assertFalse(result["physical_local_model_execution"])
        self.assertFalse(result["model_origin_independently_authenticated"])
        self.assertFalse(result["independently_authenticated_receipt"])
        self.assertEqual(result["production_promotion"], "DENY_ALL")
        self.assertEqual(result["rows"][0]["feature_digest"], result["rows"][1]["feature_digest"])
        second = stem.encode_cells([sample("cell.c")])
        self.assertEqual(second["sentence_transformer_encode_calls"], 1)
        self.assertEqual(stem.model_encode_calls, 2)
        with self.assertRaises(QualificationError):
            stem.encode_cells([sample("cell.a"), sample("cell.b", scope_id="different")])
        with self.assertRaises(QualificationError):
            stem.encode_cells([sample("cell.a"), sample("cell.a")])


class PairedEvidence(unittest.TestCase):
    def test_future_group_and_asset_leakage(self):
        rows = pairs()
        self.assertEqual(validate_pairs(rows)["cases"], 4)
        leak = pairs()
        leak[2]["group_id"] = "g1"
        with self.assertRaises(QualificationError):
            validate_pairs(leak)
        leak = pairs()
        leak[2]["text"]["input"]["sha256"] = leak[0]["text"]["input"]["sha256"]
        with self.assertRaises(QualificationError):
            validate_pairs(leak)
        leak = pairs()
        leak[1]["media"]["input"]["sha256"] = leak[0]["media"]["input"]["sha256"]
        with self.assertRaises(QualificationError):
            validate_pairs(leak)
        leak = pairs()
        leak[1]["text"]["input"]["sha256"] = leak[0]["text"]["input"]["sha256"]
        with self.assertRaises(QualificationError):
            validate_pairs(leak)
        leak = pairs()
        leak[2]["observed_utc"] = "2026-07-01T00:00:00Z"
        with self.assertRaises(QualificationError):
            validate_pairs(leak)
        leak = pairs()
        leak[2]["media"]["scope_id"] = "scope.other"
        with self.assertRaises(QualificationError):
            validate_pairs(leak)

    def test_paired_execution_refuses_unverified_stub(self):
        class StubRunner:
            manifest = {"dimension": 256, "profile": "vision"}
        with self.assertRaises(QualificationError):
            execute_pairs(StubRunner(), pairs(), Path("/unused"))

    def test_paired_oracle_reports_only_metrics_not_promotion(self):
        rows = pairs()
        a, b = [1 << 24] + [0] * 255, [0, 1 << 24] + [0] * 254
        vectors = {"a": (a, a, a), "b": (b, b, b), "c": (a, a, a), "d": (b, b, b)}
        result = paired_cosine_metrics(rows, vectors)
        self.assertEqual(len(result["results"]), 4)
        self.assertEqual(result["directional_text_views_per_case"], 2)
        self.assertTrue(all(r["recall_at_1"] == 1 for r in result["results"]))
        with self.assertRaises(QualificationError):
            paired_cosine_metrics(rows, {k: v[:2] for k, v in vectors.items()})
        self.assertEqual(result["production_promotion"], "DENY_ALL")


class StemHeadStudy(unittest.TestCase):
    def dataset(self):
        names = ("train", "calibration", "test", "future1", "future2", "future3")
        rows = []
        for index, split in enumerate(names):
            for j in range(8):
                raw = json.dumps({"question": f"task {index}/{j}",
                                  "options": ["yes", "no"], "state": "frozen"},
                                 sort_keys=True, ensure_ascii=False, separators=(",", ":"))
                rows.append({
                    "case_id": f"{split}.{j}",
                    "group_id": f"{split}.group.{j//4}",
                    "observed_utc": f"2026-{index+1:02d}-{j+1:02d}T00:00:00Z",
                    "split": split,
                    "label": j % 2,
                    "production_probability": 0.5,
                    "request": sample(cell=f"shadow.{index}.{j}",
                                      input={"modality": "text", "role": "classification",
                                             "value": raw, "sha256": sha256(raw.encode("utf-8"))}),
                })
        return {"schema": "hepta.gemma2.binary-cell-study.v1",
                "scope_id": "scope.a", "principal_id": "principal.a",
                "purpose_id": "purpose.decision", "source_manifest_digest": "a" * 64,
                "baseline_model_digest": "b" * 64, "cases": rows}

    def test_train_calibration_test_three_future_windows_strict_order(self):
        ds = self.dataset()
        v = validate_study(ds)
        self.assertEqual(v["rows"], 48)
        self.assertEqual(len(v["dataset_digest"]), 64)
        self.assertEqual(len(v["cohorts"]), 6)

    def test_leakage_missing_baseline_partial_prompt_rejected(self):
        ds = self.dataset()
        ds["cases"][32]["group_id"] = ds["cases"][0]["group_id"]
        with self.assertRaises(QualificationError):
            validate_study(ds)
        ds = self.dataset()
        ds["cases"][40]["observed_utc"] = "2026-01-01T00:00:00Z"
        with self.assertRaises(QualificationError):
            validate_study(ds)
        ds = self.dataset()
        ds["cases"][16]["production_probability"] = None
        with self.assertRaises(QualificationError):
            validate_study(ds)
        ds = self.dataset()
        ds["cases"][0]["request"]["input"]["value"] = '{"state":"only"}'
        with self.assertRaises(QualificationError):
            validate_study(ds)

    def test_stub_cannot_claim_real_stem_head_training(self):
        class StubRunner:
            _verified_local_weights = False
            manifest = {"dimension": 256, "profile": "text"}
        with self.assertRaises(QualificationError):
            run_study(StubRunner(), self.dataset())


class Screening(unittest.TestCase):
    def candidate(self):
        return {"action": "stem_consolidation", "candidate_digest": "a" * 64,
                "base_digest": "b" * 64, "source_snapshot_digest": "c" * 64,
                "evaluator_digest": "d" * 64, "predecessor_digest": "e" * 64,
                "revocation_frontier": "f" * 64,
                "real_pretrained_encoder": True, "independent_outcome": True,
                "training_groups": ["t"], "future_groups": ["f1", "f2", "f3"],
                "future_windows": 3, "current_model_unchanged": True,
                "deleted_sources_excluded": True, "cross_scope_training_authorized": True,
                "task_gain_lcb95": 0.001, "worst_retention_delta": -0.01,
                "max_ece": 0.02, "ood_false_accept_rate": 0.001,
                "matched_total_cost_ratio": 0.98}

    def test_no_production_promotion_even_if_self_reported_green(self):
        verdict = advisory_gate(self.candidate())
        self.assertEqual(verdict["screening"], "READY_FOR_INDEPENDENT_REVIEW")
        self.assertEqual(verdict["production_promotion"], "DENY_ALL")
        self.assertFalse(verdict["claims_independently_authenticated"])

    def test_negative_transfer_leakage_missing_authority_rejected(self):
        for value in (dict(task_gain_lcb95=-0.1), dict(worst_retention_delta=-0.03),
                      dict(cross_scope_training_authorized=False), dict(future_windows=2),
                      dict(future_groups=["t", "f1", "f2"]),
                      dict(real_pretrained_encoder=False)):
            c = self.candidate()
            c.update(value)
            self.assertEqual(advisory_gate(c)["screening"], "REJECTED")
        c = self.candidate()
        c["evaluator_digest"] = "invalid"
        with self.assertRaises(DifferentiationError):
            advisory_gate(c)


if __name__ == "__main__":
    unittest.main()
