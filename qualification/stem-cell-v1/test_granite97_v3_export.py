"""Zero-model, source/adversarial tests for the V5 physical Granite97 export ABI.

These tests verify the byte-format and negative gates, not pretrained learning.
"""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from granite97_v3_export import (
    FILES, MODEL_ID, REVISION, Q24, build_record, canonical_json,
    complete_input_digest, load_material, profile_digests, quantize_rows, sha,
)


def fixture_identity():
    return dict(
        encoder_digest=sha(b"base-model"),
        tokenizer_digest=sha(b"tokenizer"),
        normalizer_digest=sha(b"normalizer"),
        quantization_digest=sha(b"Q24"),
        preprocessing_digest=sha(b"preprocess"),
        adapter_digest=sha(b"adapter"),
    )


def record(source=b"hello Granite v3", ids=None, mask=None, rows=None):
    ids = [101, 305, 102] if ids is None else ids
    mask = [1, 1, 1] if mask is None else mask
    rows = [[0.5] * 384 for _ in ids] if rows is None else rows
    return build_record(
        source, ids, mask, rows, fixture_identity(), sha(b"material"),
        150, 100, 200, principal_id="principal:a", purpose_id="reasoning",
        generation=4, authority_epoch=2,
    )


class GraniteExportV5Tests(unittest.TestCase):
    def test_python_rust_exact_original_token_hash_golden(self):
        self.assertEqual(
            complete_input_digest(b"hello Granite v3", [101, 305, 102], [1, 1, 1]),
            "aa6a4645ede9405489a07e20faa9395eaa42545e6d6cdb49b7388576315a10ae",
        )

    def test_snapshot_carries_byte_bound_scope_and_numeric_token_rows(self):
        item = record()
        self.assertEqual(item["model_id"], MODEL_ID)
        self.assertEqual(item["revision"], REVISION)
        self.assertEqual(item["schema"], "hepta.stem.granite97-token-export.v5")
        self.assertEqual(item["values_q24"], [Q24 // 2] * (3 * 384))
        self.assertEqual(
            (item["principal_id"], item["purpose_id"], item["generation"],
             item["authority_epoch"]),
            ("principal:a", "reasoning", 4, 2),
        )
        self.assertEqual(json.loads(canonical_json(item)), item)

    def test_ties_even_negative_ties_and_real_numeric_bounds(self):
        one_over_q = 1 / Q24
        rows = [[0.0] * 384 for _ in range(3)]
        rows[0][0] = 0.5 * one_over_q
        rows[1][0] = 1.5 * one_over_q
        rows[2][0] = -1.5 * one_over_q
        values = quantize_rows(rows, [1, 1, 1])
        self.assertEqual([values[0], values[384], values[768]], [0, 2, -2])
        for wrong in (float("nan"), float("inf"), 8.01, -8.01):
            with self.subTest(wrong=wrong):
                rows[0][0] = wrong
                with self.assertRaises(ValueError):
                    quantize_rows(rows, [1, 1, 1])

    def test_no_truncation_or_mask_surgery(self):
        with self.assertRaises(ValueError):
            complete_input_digest(b"source", list(range(257)), [1] * 257)
        with self.assertRaises(ValueError):
            complete_input_digest(b"source", [101, 102], [1, 0])
        with self.assertRaises(ValueError):
            complete_input_digest(b"source", [101, 102], [1])
        with self.assertRaises(ValueError):
            complete_input_digest(b"", [101, 102], [1, 1])
        self.assertEqual(
            quantize_rows([[0.0] * 384, [0.0] * 384], [1, 0]),
            [0] * 768,
        )
        with self.assertRaises(ValueError):
            quantize_rows([[0.0] * 384, [1.0] * 384], [1, 0])
        with self.assertRaises(ValueError):
            quantize_rows([[0.0] * 383], [1])

    def test_complete_original_bytes_change_identity_with_same_tokens(self):
        first = complete_input_digest(b"alpha", [101, 305, 102], [1, 1, 1])
        second = complete_input_digest(b"alpha!", [101, 305, 102], [1, 1, 1])
        self.assertNotEqual(first, second)
        self.assertNotEqual(first, complete_input_digest(b"alpha", [101, 306, 102], [1, 1, 1]))

    def test_bad_scope_and_fake_work_fail_without_pretrained_model(self):
        valid = dict(principal_id="principal:a", purpose_id="reasoning",
                     generation=4, authority_epoch=2)
        for override in (
            {"principal_id": "../escape"}, {"purpose_id": ""},
            {"generation": 0}, {"authority_epoch": True},
            {"generation": 2**64},
        ):
            with self.subTest(override=override):
                fields = {**valid, **override}
                with self.assertRaises(ValueError):
                    build_record(
                        b"hello", [101], [1], [[0.] * 384], fixture_identity(),
                        sha(b"material"), 100, 10, 20, **fields,
                    )
        with self.assertRaises(ValueError):
            build_record(
                b"hello", [101], [1], [[0.] * 384], fixture_identity(),
                sha(b"material"), 100, 0, 20, **valid,
            )

    def test_tokenizer_runtime_or_material_changes_identity(self):
        material = {"sha256": {k: sha(k.encode()) for k in FILES}}
        a = profile_digests(sha(b"m"), material, max_tokens=192,
                            torch_version="2.6.0+cpu", transformers_version="4.57.1")
        b = profile_digests(sha(b"m"), material, max_tokens=128,
                            torch_version="2.6.0+cpu", transformers_version="4.57.1")
        c = profile_digests(sha(b"other"), material, max_tokens=192,
                            torch_version="2.6.0+cpu", transformers_version="4.57.1")
        self.assertNotEqual(a["preprocessing_digest"], b["preprocessing_digest"])
        self.assertNotEqual(a["encoder_digest"], c["encoder_digest"])
        self.assertEqual(a["adapter_digest"], b["adapter_digest"])

    def test_physical_model_inventory_byte_changes_and_symlink_fail(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            contents = {}
            for name in FILES:
                raw = f"synthetic; NOT pretrained {name}".encode()
                contents[name] = raw
                (root / name).write_bytes(raw)
            manifest = dict(
                model_id=MODEL_ID, revision=REVISION,
                files={k: len(v) for k, v in contents.items()},
                sha256={k: sha(v) for k, v in contents.items()},
            )
            (root / "material.json").write_bytes(canonical_json(manifest))
            admitted, exact_sha = load_material(root)
            self.assertEqual(admitted["revision"], REVISION)
            self.assertEqual(len(exact_sha), 64)
            (root / "model.safetensors").write_bytes(b"malicious new bytes")
            with self.assertRaises(ValueError):
                load_material(root)
            (root / "model.safetensors").unlink()
            (root / "model.safetensors").symlink_to(root / "config.json")
            with self.assertRaises(ValueError):
                load_material(root)


if __name__ == "__main__":
    unittest.main()
