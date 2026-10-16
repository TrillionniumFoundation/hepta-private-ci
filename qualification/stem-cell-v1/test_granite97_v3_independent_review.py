#!/usr/bin/env python3
"""Source-only negative controls for source-separated real Granite97 replay.

No pretrained download, torch, model execution or simulated positive review.
The positive fixture tests the *preflight ABI*, not actual Encoder correctness.
"""
from pathlib import Path
import json
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import granite97_v3_independent_review as review


def fixture():
    original = b"check original evidence and question"
    ids, mask = [101, 205, 102], [1, 1, 1]
    material = review.sha(b"original material bytes")
    record = dict(
        schema=review.SCHEMA, model_id=review.MODEL_ID, revision=review.REVISION,
        material_digest=material,
        encoder_digest=review.sha(review.DOMAIN_MODEL + bytes.fromhex(material)),
        tokenizer_digest=review.sha(b"tokenizer"),
        normalizer_digest=review.sha(b"normalizer"),
        quantization_digest=review.sha(b"quantizer"),
        preprocessing_digest=review.sha(b"preprocessor"),
        adapter_digest=review.sha(b"adapter"),
        source_sha256=review.sha(original),
        input_digest=review.complete_digest(original, ids, mask),
        principal_id="principal:a", purpose_id="stem-research",
        generation=7, authority_epoch=11,
        input_ids=ids, attention_mask=mask,
        values_q24=[review.Q24 // 2] * (3 * 384), width=384,
        expires_at_ms=1000,
        encoder_forwards=1, encoder_cpu_ns=12345, encoder_wall_ns=67890,
    )
    kwargs=dict(source_sha256=review.sha(original), material_sha256=material,
                principal="principal:a", purpose="stem-research",
                generation=7, authority_epoch=11,
                now_ms=100, maximum_expiry_ms=1000)
    return original, record, kwargs


class GraniteIndependentReviewSourceTests(unittest.TestCase):
    def preflight(self, original, record, params):
        return review.preflight_export(record, original, **params)

    def test_external_source_and_v3_abi_positive_without_model(self):
        original, record, params = fixture()
        summary = self.preflight(original, record, params)
        self.assertEqual(summary["rows"], 3)
        self.assertEqual(summary["width"], 384)
        self.assertEqual(summary["source_digest"], record["source_sha256"])
        self.assertEqual(summary["input_digest"], record["input_digest"])

    def test_python_rust_independent_sha_golden(self):
        self.assertEqual(
            review.complete_digest(b"hello Granite v3", [101, 305, 102], [1, 1, 1]),
            "aa6a4645ede9405489a07e20faa9395eaa42545e6d6cdb49b7388576315a10ae",
        )

    def test_source_or_token_changes_and_recomputed_untrusted_digest_fail(self):
        original, record, params = fixture()
        with self.assertRaises(ValueError):
            self.preflight(original + b"!", record, params)
        mutated = dict(record, input_ids=[101, 206, 102])
        with self.assertRaises(ValueError):
            self.preflight(original, mutated, params)
        mutated["input_digest"] = review.complete_digest(
            original, mutated["input_ids"], mutated["attention_mask"])
        # The unsigned source/proposal can supply internally consistent new
        # tokenization. The independent original-token owner must bind it
        # separately before accepting the read; this preflight alone cannot.
        self.preflight(original, mutated, params)
        self.assertNotEqual(mutated["input_digest"], record["input_digest"])

    def test_model_revision_manifest_and_scope_are_owner_fenced(self):
        original, record, params = fixture()
        for key, value in (
            ("model_id", "fake"),
            ("revision", "main"),
            ("material_digest", review.sha(b"attacker-model")),
            ("encoder_digest", review.sha(b"attacker-encoder")),
            ("principal_id", "principal:b"),
            ("purpose_id", "other-task"),
            ("generation", 8),
            ("authority_epoch", 12),
        ):
            with self.subTest(key=key):
                with self.assertRaises(ValueError):
                    self.preflight(original, {**record, key: value}, params)

    def test_undeclared_extension_missing_counters_expired_and_wrong_types(self):
        original, record, params = fixture()
        for key, value in (
            ("encoder_forwards", 0),
            ("encoder_forwards", 2),
            ("encoder_cpu_ns", True),
            ("encoder_wall_ns", 0),
            ("expires_at_ms", 1001),
            ("expires_at_ms", 100),
            ("width", 256),
            ("input_ids", [101, 102]),
            ("attention_mask", [1, 0, 1]),
            ("values_q24", [0] * 1151),
            ("generation", False),
            ("source_sha256", "A" * 64),
        ):
            with self.subTest(key=key):
                with self.assertRaises(ValueError):
                    self.preflight(original, {**record, key: value}, params)
        with self.assertRaises(ValueError):
            self.preflight(original, {**record, "unreviewed": True}, params)

    def test_payload_saturation_nonfinite_and_illegal_json(self):
        original, record, params = fixture()
        oversized = dict(record, values_q24=[review.Q24 * 9] + record["values_q24"][1:])
        with self.assertRaises(ValueError):
            self.preflight(original, oversized, params)
        nonint = dict(record, values_q24=[0.5] + record["values_q24"][1:])
        with self.assertRaises(ValueError):
            self.preflight(original, nonint, params)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            a = root / "duplicate.json"
            a.write_text('{"foo":1,"foo":2}')
            with self.assertRaises(ValueError):
                review.load_json_file(a, 1000)
            b = root / "nonfinite.json"
            b.write_text('{"answer":NaN}')
            with self.assertRaises(ValueError):
                review.load_json_file(b, 1000)


    def test_independent_profile_replay_detects_runtime_or_tokenizer_drift(self):
        original, record, _ = fixture()
        manifest = {"sha256": {name: review.sha(name.encode())
                               for name in review.FILES}}
        # This is a source-only profile construction, not a verified model.
        fp = {}
        tokenizer = {name: manifest["sha256"][name] for name in review.FILES
                     if "token" in name or name == "special_tokens_map.json"}
        canonical = lambda value: json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
            allow_nan=False).encode()
        fp["tokenizer_digest"] = review.sha(
            b"hepta.granite97.tokenizer.v5\0" + canonical(tokenizer))
        fp["normalizer_digest"] = review.sha(b"hepta.granite97.identity-normalizer.v5")
        fp["quantization_digest"] = review.sha(b"hepta.granite97.fp32-q24-ties-even.v5")
        fp["preprocessing_digest"] = review.sha(
            b"hepta.granite97.preprocessing.v5\0" + canonical(
                dict(max_tokens=192, truncation=False, add_special_tokens=True,
                     padding=False, precision="fp32", attention="eager",
                     output="last_hidden_state", tokenizer=tokenizer,
                     torch_version="2.6.0+cpu", transformers_version="4.57.1",
                     model_config_sha256=manifest["sha256"]["config.json"])))
        fp["adapter_digest"] = review.sha(b"hepta.granite97.identity-adapter.v5")
        admitted = {**record, **fp}
        self.assertEqual(
            review.verify_preprocessing_profile(
                admitted, manifest, maximum_tokens=192,
                torch_version="2.6.0+cpu", transformers_version="4.57.1"),
            fp)
        with self.assertRaises(ValueError):
            review.verify_preprocessing_profile(
                admitted, manifest, maximum_tokens=128,
                torch_version="2.6.0+cpu", transformers_version="4.57.1")
        with self.assertRaises(ValueError):
            review.verify_preprocessing_profile(
                admitted, manifest, maximum_tokens=192,
                torch_version="2.10.0+cpu", transformers_version="4.57.1")
        bad_material = json.loads(json.dumps(manifest))
        bad_material["sha256"]["tokenizer.json"] = review.sha(b"mutated")
        with self.assertRaises(ValueError):
            review.verify_preprocessing_profile(
                admitted, bad_material, maximum_tokens=192,
                torch_version="2.6.0+cpu", transformers_version="4.57.1")

    def test_independent_material_inventory_is_byte_bound(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            manifest = dict(model_id=review.MODEL_ID, revision=review.REVISION,
                            files={}, sha256={})
            payloads = {}
            for name in review.FILES:
                payloads[name] = ("NOT MODEL WEIGHTS: " + name).encode()
                (root / name).write_bytes(payloads[name])
                manifest["files"][name] = len(payloads[name])
                manifest["sha256"][name] = review.sha(payloads[name])
            (root / "material.json").write_text(json.dumps(manifest))
            body = [review.DOMAIN_MATERIAL]
            for name in sorted(review.FILES):
                raw = name.encode()
                body.extend((len(raw).to_bytes(4, "big"), raw,
                             len(payloads[name]).to_bytes(8, "big"),
                             bytes.fromhex(review.sha(payloads[name]))))
            external = review.sha(b"".join(body))
            self.assertEqual(review.inspect_original_material(root, external), external)
            with self.assertRaises(ValueError):
                review.inspect_original_material(root, review.sha(b"other snapshot"))
            (root / "model.safetensors").write_bytes(b"changed")
            with self.assertRaises(ValueError):
                review.inspect_original_material(root, external)
            (root / "model.safetensors").unlink()
            (root / "model.safetensors").symlink_to(root / "config.json")
            with self.assertRaises(ValueError):
                review.inspect_original_material(root, external)

    def test_rational8_independent_numeric_and_profile_requires_opt_in(self):
        # Independently implemented bounded transform, not proof of real
        # model execution or exact invertibility after Q24 quantization.
        for original in (-64.0, -16.0, -8.0, 0.0, 8.0, 16.0, 64.0):
            expected = round((8.0 * original) / (8.0 + abs(original)) * review.Q24)
            self.assertEqual(
                review.independently_project_feature(original, "rational8-v1"), expected)
        with self.assertRaises(ValueError):
            review.independently_project_feature(16.0, "identity")
        with self.assertRaises(ValueError):
            review.independently_project_feature(float("nan"), "rational8-v1")
        with self.assertRaises(ValueError):
            review.independently_project_feature(1.0, "unrecognized")

        _, record, _ = fixture()
        material = {"sha256": {n: review.sha(n.encode()) for n in review.FILES}}
        tokenizer = {n: material["sha256"][n] for n in review.FILES
                     if "token" in n or n == "special_tokens_map.json"}
        profile = dict(max_tokens=192, truncation=False, add_special_tokens=True,
                       padding=False, precision="fp32", attention="eager",
                       output="last_hidden_state", tokenizer=tokenizer,
                       torch_version="2.10.0+cpu", transformers_version="4.57.1",
                       model_config_sha256=material["sha256"]["config.json"],
                       feature_adapter="rational8-v1")
        canonical = lambda x: json.dumps(x, sort_keys=True,
                                         separators=(",", ":"), ensure_ascii=False,
                                         allow_nan=False).encode()
        # Recompute profile independently from the producer implementation.
        bounded = dict(record)
        bounded.update(
            tokenizer_digest=review.sha(
                b"hepta.granite97.tokenizer.v5\0" + canonical(tokenizer)),
            normalizer_digest=review.sha(b"hepta.granite97.identity-normalizer.v5"),
            quantization_digest=review.sha(b"hepta.granite97.fp32-q24-ties-even.v5"),
            preprocessing_digest=review.sha(
                b"hepta.granite97.preprocessing.v5\0" + canonical(profile)),
            adapter_digest=review.sha(review.RATIONAL8_DOMAIN))
        self.assertEqual(
            review.verify_preprocessing_profile(
                bounded, material, maximum_tokens=192,
                torch_version="2.10.0+cpu", transformers_version="4.57.1",
                feature_adapter="rational8-v1")["adapter_digest"],
            bounded["adapter_digest"])
        with self.assertRaises(ValueError):
            review.verify_preprocessing_profile(
                bounded, material, maximum_tokens=192,
                torch_version="2.10.0+cpu", transformers_version="4.57.1")
        with self.assertRaises(ValueError):
            review.verify_preprocessing_profile(
                bounded, material, maximum_tokens=192,
                torch_version="2.10.0+cpu", transformers_version="4.57.1",
                feature_adapter="unknown")

    def test_expiry_scope_and_material_precede_any_tensor_import(self):
        original, record, params = fixture()
        with self.assertRaises(ValueError):
            self.preflight(original, record, {**params, "now_ms": 1001})
        with self.assertRaises(ValueError):
            self.preflight(original, record, {**params, "maximum_expiry_ms": 999})
        with self.assertRaises(ValueError):
            self.preflight(original, record, {**params, "material_sha256": review.sha(b"other")})


if __name__ == "__main__":
    unittest.main()
