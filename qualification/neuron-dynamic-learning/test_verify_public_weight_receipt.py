"""Adversarial archive fixtures; synthetic bytes are not real-model evidence."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from verify_public_weight_receipt import ReceiptError, digest, verify_zip


class PublicArchiveChecks(unittest.TestCase):
    def fixture(self, file, mutate=None):
        source = {"source": "google/embeddinggemma-2",
                  "revision": "914f7f89142e33e77833254d9c9b90c3cef7303b",
                  "production_promotion": "DENY_ALL", "pipeline_digest": "f" * 64,
                  "remote_metadata_is_not_independent_signature": True,
                  "actual_encoder_forward_executed": False,
                  "bytes_verified": 1525787092, "model_files": 13}
        rows = []
        for cid, phrase, vector in (
                ("cell.a", "Classify a checked file-content digest.", [1 << 24] + [0] * 255),
                ("cell.b", "Classify a checked file-content digest.", [1 << 24] + [0] * 255),
                ("cell.c", "Classify an observed syntax error.", [0, 1 << 24] + [0] * 254)):
            rows.append({"cell_id": cid, "features_q24": vector,
                         "feature_digest": digest(vector),
                         "embedding_f32_digest": hashlib.sha256(str(vector).encode()).hexdigest(),
                         "input_digest": hashlib.sha256(phrase.encode()).hexdigest(),
                         "pipeline_digest": "f" * 64, "authority": "DENY_ALL",
                         "scope_id": "public.shadow", "principal_id": "physical.cpu",
                         "purpose_id": "nonproduction.smoke", "generation": 1,
                         "authority_epoch": 1, "modality": "text", "role": "classification",
                         "requires_new_neuron_profile": False})
        prediction = {"model_id": source["source"], "model_revision": source["revision"],
                      "evidence_type": "local_weight_execution_unverified_origin",
                      "physical_local_model_execution": True,
                      "physical_transformer_forward_calls": None,
                      "independently_authenticated_receipt": False,
                      "model_origin_independently_authenticated": False,
                      "production_promotion": "DENY_ALL", "profile": "text",
                      "feature_dimension": 256, "cell_requests": 3,
                      "distinct_input_rows": 2, "sentence_transformer_encode_calls": 1,
                      "text_token_budget_verified": True,
                      "multimodal_internal_token_budget_verified": False,
                      "measured_wall_micros": 100, "rows": rows}
        if mutate:
            mutate(source, prediction)
        with zipfile.ZipFile(file, "w") as z:
            z.writestr("gemma2-snapshot-receipt.json", json.dumps(source))
            z.writestr("gemma2-real-forward.json", json.dumps(prediction))
            z.writestr("gemma2-environment.freeze",
                       "torch==1.0\nsentence-transformers==1.0\n"
                       "transformers==1.0\nsafetensors==1.0\n")

    def test_valid_numeric_fixture_is_not_independent_model_evidence(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "fixture.zip"
            self.fixture(path)
            reviewed = verify_zip(path)
            self.assertEqual(reviewed["matched_rust_q24_content_digests"], 3)
            self.assertFalse(reviewed["independent_model_execution_attestation"])
            self.assertEqual(reviewed["production_promotion"], "DENY_ALL")

    def test_tamper_or_overclaim_is_rejected(self):
        for kind in ("feature", "physical", "authority"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / "bad.zip"
                def corrupt(source, prediction):
                    if kind == "feature":
                        prediction["rows"][0]["features_q24"][0] += 1
                    elif kind == "physical":
                        prediction["physical_transformer_forward_calls"] = 1
                    else:
                        source["production_promotion"] = "ALLOW"
                self.fixture(path, mutate=corrupt)
                with self.assertRaises(ReceiptError):
                    verify_zip(path)

    def test_zip_extra_member_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "bad.zip"
            self.fixture(path)
            with zipfile.ZipFile(path, "a") as z:
                z.writestr("../outside.txt", "bad")
            with self.assertRaises(ReceiptError):
                verify_zip(path)
