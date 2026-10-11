"""Model-free Python/Rust exact-byte Stem Worker payload compatibility tests."""
import hashlib
import unittest

from stem_worker_binding import (
    feature_vector_digest_v1,
    qualification_only_receipt,
    scoped_worker_input_digest_v1,
    stem_feature_ref_digest_v1,
)


def _digest(value):
    return hashlib.sha256(value).hexdigest()


def fixture():
    features = [1 << 22, -(1 << 21)]
    return {
        "scope_id": "scope.1",
        "principal_id": "principal.1",
        "stem_model_id": "jina-v5-text-nano",
        "stem_generation": 3,
        "authority_epoch": 2,
        "lease_expires_at_ms": 8000,
        "stem_weights_digest": _digest(b"verified-stem-by-owner"),
        "tokenizer_digest": _digest(b"stem-tokenizer"),
        "preprocessor_digest": _digest(b"stem-preprocessor"),
        "projection_digest": _digest(b"matryoshka-256-q24"),
        "input_digest": _digest(b"scope.1/input"),
        "feature_digest": feature_vector_digest_v1(features),
        "feature_width": 2,
        "feature_vector_q24": features,
    }


class StemWorkerBindingTests(unittest.TestCase):
    def test_cross_language_rust_fixture_exact_golden(self):
        source = fixture()
        self.assertEqual(source["feature_digest"],
                         "b9b1bbf5ad007adaed29f199b62dee14de4473d79e5e13315aa8ddb06e133d23")
        self.assertEqual(
            stem_feature_ref_digest_v1(source),
            "6a705b03b523b5a7e8cb884b0d0994d9ae76cb4dbc078102f66392b26b6f852e",
        )
        self.assertEqual(
            scoped_worker_input_digest_v1(source),
            "6d6c6541396eb0f5ece9ec2ced55569133aa8f48852d7c1748509d53f3189e43",
        )
        proof = qualification_only_receipt(source)
        self.assertFalse(proof["production_promotion_permitted"])
        self.assertFalse(proof["loaded_stem_artifact_attested"])
        self.assertFalse(proof["independent_final_use_verified"])

    def test_scope_principal_epoch_or_lease_change_invalidates_worker_payload(self):
        first = fixture()
        observed = scoped_worker_input_digest_v1(first)
        for field, new in (
            ("scope_id", "scope.other"),
            ("principal_id", "principal.other"),
            ("stem_generation", 4),
            ("authority_epoch", 3),
            ("lease_expires_at_ms", 8001),
            ("input_digest", _digest(b"another-input")),
            ("projection_digest", _digest(b"other-matryoshka")),
            ("tokenizer_digest", _digest(b"other-tokenizer")),
        ):
            changed = dict(first)
            changed[field] = new
            self.assertNotEqual(observed, scoped_worker_input_digest_v1(changed), field)

    def test_noncanonical_or_tampered_fields_fail_closed(self):
        source = fixture()
        for field, bad in (
            ("stem_model_id", "hello world"),
            ("principal_id", "用户"),
            ("scope_id", "x" * 129),
            ("stem_generation", 0),
            ("stem_generation", 1 << 64),
            ("authority_epoch", True),
            ("input_digest", "0" * 64),
            ("feature_width", 1),
            ("feature_digest", "0" * 64),
        ):
            broken = dict(source)
            broken[field] = bad
            with self.subTest(field=field, value=str(bad)[:24]):
                with self.assertRaises(ValueError):
                    scoped_worker_input_digest_v1(broken)
        broken = fixture()
        broken["feature_vector_q24"] = [1 << 22, -(1 << 21) + 1]
        with self.assertRaisesRegex(ValueError, "feature digest"):
            scoped_worker_input_digest_v1(broken)


if __name__ == "__main__":
    unittest.main()
