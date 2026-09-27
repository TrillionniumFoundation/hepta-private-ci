"""Protocol tests use explicit doubles; none represents a real Laya forward."""
from contextlib import nullcontext
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from scripts.hepta_laya_retrieval import (
    PinnedLaya, Rejected, Request, Source, canonical, digest, encode, file_digests,
    lock_bundle, probability_ppm, score, strict_json,
)


def source(name="record-1", text="Approved retrieval evidence"):
    return Source(name, 1, hashlib.sha256(text.encode()).hexdigest(), text)


def request():
    return Request("op-1", "workspace-1", 1, digest("objective"), digest("snapshot"),
                   digest("bundle"), 2000, "What evidence supports this?", (source(),))


class Port:
    def __init__(self, raw=None):
        self.calls = []
        self.bundle_digest = digest("bundle")
        self.raw = raw if raw is not None else {
            "answers": {"source": {"type": "choice", "choice": "c1",
                "probabilities": {"c0": 0.1, "c1": 0.9}, "action": {"act_probability": 1.0}}},
            "usage": {"input_tokens": 30, "output_tokens": 0},
        }

    def predict(self, state, questions):
        self.calls.append((state, questions))
        return self.raw


class RetrievalTests(unittest.TestCase):
    def test_real_scores_are_not_behavior_propensities(self):
        port = Port()
        result = score(request(), port, now_ms=lambda: 1000, current=lambda _: True)
        self.assertEqual(result["prediction_ppm"], (100000, 900000))
        self.assertEqual(result["selected_source"], "record-1")
        self.assertEqual(result["selected_behavior_propensity_ppm"], 1000000)
        self.assertFalse(result["production_authority"])
        self.assertEqual(len(port.calls), 1)
        self.assertNotIn("objective", port.calls[0][0])
        claimed = result.pop("result_digest")
        self.assertEqual(claimed, digest(result))

    def test_no_model_authority_from_act_probability(self):
        port = Port()
        port.raw["answers"]["source"]["probabilities"] = {"c0": 0.9, "c1": 0.1}
        port.raw["answers"]["source"]["choice"] = "c0"
        self.assertIsNone(score(request(), port, now_ms=lambda: 1000, current=lambda _: True)["selected_source"])

    def test_bundle_substitution_never_calls_model(self):
        port = Port()
        port.bundle_digest = digest("different-model")
        with self.assertRaises(Rejected):
            score(request(), port, now_ms=lambda: 1000, current=lambda _: True)
        self.assertEqual(port.calls, [])

    def test_expired_input_never_calls_model(self):
        port = Port()
        with self.assertRaises(Rejected):
            score(request(), port, now_ms=lambda: 2000, current=lambda _: True)
        self.assertEqual(port.calls, [])

    def test_withdrawal_before_dispatch_never_calls_model(self):
        port = Port()
        with self.assertRaises(Rejected):
            score(request(), port, now_ms=lambda: 1000, current=lambda _: False)
        self.assertEqual(port.calls, [])

    def test_withdrawal_during_inference_does_not_publish_or_retry(self):
        port, views = Port(), iter((True, False))
        with self.assertRaises(Rejected):
            score(request(), port, now_ms=lambda: 1000, current=lambda _: next(views))
        self.assertEqual(len(port.calls), 1)

    def test_expiry_during_inference_does_not_publish_or_retry(self):
        port, clock = Port(), iter((1000, 2000))
        with self.assertRaises(Rejected):
            score(request(), port, now_ms=lambda: next(clock), current=lambda _: True)
        self.assertEqual(len(port.calls), 1)

    def test_exception_is_not_a_terminal_negative_observation(self):
        port = Port()
        with patch.object(port, "predict", side_effect=RuntimeError("lost response")) as call:
            with self.assertRaises(RuntimeError):
                score(request(), port, now_ms=lambda: 1000, current=lambda _: True)
            self.assertEqual(call.call_count, 1)

    def test_changed_source_bytes_reject_before_model(self):
        port = Port()
        req = replace(request(), sources=(replace(source(), text="Changed without revision"),))
        with self.assertRaises(Rejected):
            score(req, port, now_ms=lambda: 1000, current=lambda _: True)
        self.assertEqual(port.calls, [])

    def test_source_revision_and_input_order_bind_request(self):
        a, b = source("a", "Alpha"), source("b", "Beta")
        first = replace(request(), sources=(b, a))
        second = replace(first, sources=(a, b))
        self.assertEqual(encode(first), encode(second))
        self.assertNotEqual(digest(asdict(first)), digest(asdict(second)))
        revised = replace(first, sources=(b, replace(a, revision=2)))
        self.assertNotEqual(digest(asdict(first)), digest(asdict(revised)))

    def test_duplicates_and_limits_reject(self):
        for req in (replace(request(), sources=(source(), source())),
                    replace(request(), sources=()), replace(request(), query="x" * 2049),
                    replace(request(), generation=True), replace(request(), deadline_ms=True)):
            with self.subTest(req=req), self.assertRaises(Rejected):
                req.validate(1000)

    def test_invalid_probabilities_are_not_clipped_or_filled(self):
        cases = ({"c0": 0.1}, {"c0": 0.2, "c1": 0.7}, {"c0": float("nan"), "c1": 0.8},
                 {"c0": True, "c1": 0.0}, {"c0": -0.1, "c1": 1.1},
                 {"c0": 0.2, "c1": 0.8, "extra": 0.0})
        for raw in cases:
            with self.subTest(raw=raw), self.assertRaises(Rejected):
                probability_ppm(raw, (None, "a"))

    def test_rounded_mass_is_conserved_with_deterministic_tie(self):
        self.assertEqual(probability_ppm({"c0": .3333, "c1": .3333, "c2": .3333},
                                       (None, "a", "b")), (333334, 333333, 333333))

    def test_missing_usage_and_wrong_answer_type_reject(self):
        for raw in ({}, {"answers": {"source": {"type": "noul"}}},
                    {"answers": {"source": {"type": "choice", "choice": "c1",
                                              "probabilities": {"c0": .1, "c1": .9}}}}):
            with self.subTest(raw=raw), self.assertRaises(Rejected):
                score(request(), Port(raw), now_ms=lambda: 1000, current=lambda _: True)

    def test_duplicate_json_and_nonfinite_rejected(self):
        for data in ('{"a":1,"a":2}', '{"x":NaN}', '{"x":Infinity}'):
            with self.assertRaises(Rejected):
                strict_json(data)


class BundleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        from scripts.hepta_laya_retrieval import REQUIRED_FILES
        for name in REQUIRED_FILES:
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"not real weights" if name.endswith("safetensors") else b"{}")
        (self.root / "tokenizer/tokenizer_config.json").write_text('{"tokenizer_class":"PreTrainedTokenizerFast"}')
        self.versions = patch("scripts.hepta_laya_retrieval.metadata.version",
                              side_effect=lambda name: "0.3.20" if name == "laya" else "test-version")
        self.versions.start()
        self.addCleanup(self.versions.stop)
        self.pin = lock_bundle(self.root, "a" * 40, 512, 192)
        self.env = patch.dict("os.environ", {"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"})
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_unpinned_runtime_or_model_ref_is_rejected(self):
        for revision in ("main", "latest", "0" * 40):
            with self.assertRaises(Rejected):
                lock_bundle(self.root, revision, 512, 192)
        with patch("scripts.hepta_laya_retrieval.metadata.version", return_value="0.4.0"):
            with self.assertRaises(Rejected):
                lock_bundle(self.root, "a" * 40, 512, 192)

    def test_bundle_digest_change_is_rejected_before_sdk_import(self):
        with self.assertRaises(Rejected):
            PinnedLaya(self.root, self.pin, digest("forged-manifest"))

    def test_artifact_change_is_rejected_before_sdk_import(self):
        (self.root / "model.safetensors").write_bytes(b"changed")
        with self.assertRaises(Rejected):
            PinnedLaya(self.root, self.pin, digest(self.pin))

    def test_missing_file_is_not_downloaded(self):
        (self.root / "encoder/config.json").unlink()
        with self.assertRaises(FileNotFoundError):
            PinnedLaya(self.root, self.pin, digest(self.pin))

    def test_symlink_bundle_is_rejected(self):
        p = self.root / "encoder/config.json"
        p.unlink()
        p.symlink_to(self.root / "rl_agent_config.json")
        with self.assertRaises(Rejected):
            file_digests(self.root)

    def test_sdk_tokenizer_rewrite_requires_a_new_normalized_bundle(self):
        (self.root / "tokenizer/tokenizer_config.json").write_text('{"tokenizer_class":"TokenizersBackend"}')
        pin = lock_bundle(self.root, "a" * 40, 512, 192)
        with self.assertRaises(Rejected):
            PinnedLaya(self.root, pin, digest(pin))

    def test_optional_tokenizer_inputs_are_also_bound(self):
        optional = self.root / "tokenizer/added_tokens.json"
        optional.write_text('{"extra":123}')
        with self.assertRaises(Rejected):
            PinnedLaya(self.root, self.pin, digest(self.pin))
        newer = lock_bundle(self.root, "a" * 40, 512, 192)
        self.assertIn("tokenizer/added_tokens.json", newer["files"])
        self.assertNotEqual(digest(newer), digest(self.pin))

    def test_optional_symlink_cannot_escape_model_bundle(self):
        (self.root / "tokenizer/added_tokens.json").symlink_to(self.root / "rl_agent_config.json")
        with self.assertRaises(Rejected):
            file_digests(self.root)

    def test_directory_cannot_replace_required_artifact(self):
        path = self.root / "model.safetensors"
        path.unlink()
        path.mkdir()
        with self.assertRaises(Rejected):
            file_digests(self.root)

    def test_offline_environment_is_required(self):
        with patch.dict("os.environ", {"HF_HUB_OFFLINE": "0"}), self.assertRaises(Rejected):
            PinnedLaya(self.root, self.pin, digest(self.pin))

    def test_unknown_manifest_fields_cannot_grant_authority(self):
        pin = dict(self.pin, production_authority=True)
        with self.assertRaises(Rejected):
            PinnedLaya(self.root, pin, digest(pin))

    def test_token_preflight_rejects_truncation_before_forward(self):
        calls = []
        agent = SimpleNamespace(
            _check_question=lambda *_: None, _to_internal=lambda q: q,
            _encode_state=lambda state, ids, q, ml, hl: [{"ids": [ml], "markers": [1]}],
            system_one=lambda *a, **k: calls.append(a),
        )
        driver = PinnedLaya.__new__(PinnedLaya)
        driver._agent, driver._max_len, driver._head_max_len = agent, 512, 192
        with patch.dict("sys.modules", {"torch": SimpleNamespace(inference_mode=nullcontext)}):
            with self.assertRaises(Rejected):
                driver.predict(*encode(request())[:2])
        self.assertEqual(calls, [])

    def test_preflight_allows_identical_complete_encodings(self):
        calls = []
        agent = SimpleNamespace(
            _check_question=lambda *_: None, _to_internal=lambda q: q,
            _encode_state=lambda *args: [{"ids": [1, 2, 3], "markers": [2]}],
            system_one=lambda *a, **k: calls.append(k) or {"answers": {}},
        )
        driver = PinnedLaya.__new__(PinnedLaya)
        driver._agent, driver._max_len, driver._head_max_len = agent, 512, 192
        with patch.dict("sys.modules", {"torch": SimpleNamespace(inference_mode=nullcontext)}):
            self.assertEqual(driver.predict(*encode(request())[:2]), {"answers": {}})
        self.assertEqual(calls, [{"max_len": 512, "head_max_len": 192}])


if __name__ == "__main__":
    unittest.main()
