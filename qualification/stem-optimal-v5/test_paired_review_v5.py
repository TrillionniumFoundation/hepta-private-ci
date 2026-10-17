"""Conformance for immutable ZIP, same-source pairing, and no-promotion gates."""
from __future__ import annotations

import copy
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from zipfile import ZipFile

import paired_review_v5 as pair


def zip_fixture(directory, *, member="receipt-granite47.json", content=None, extra=False):
    content = content or {"schema": "synthetic.fixture", "authority": "DENY_ALL"}
    raw = pair.canonical(content) + b"\n"
    path = Path(directory) / "artifact.zip"
    with ZipFile(path, "w") as z:
        z.writestr(member, raw)
        z.writestr(member.replace(".json", ".sha256"),
                   f"{hashlib.sha256(raw).hexdigest()}  {member}\n")
        if extra:
            z.writestr("../unsafe.json", "malicious")
    lock = {role: {"run_id": 7, "artifact_id": 8,
                   "archive_sha256": pair.sha(path.read_bytes()),
                   "json_member": member, "json_sha256": pair.sha(raw)}
            for role in pair.ROLES}
    return path, lock, content


class V5OriginalPairTests(unittest.TestCase):
    def test_zip_bytes_and_sha_sidecar_verification(self):
        with tempfile.TemporaryDirectory() as d:
            path, lock, expected = zip_fixture(d)
            self.assertEqual(pair.locked_json(path, lock, "granite47"), expected)
            with path.open("ab") as f:
                f.write(b"changed after ZIP was signed")
            with self.assertRaisesRegex(ValueError, "original ZIP SHA mismatch"):
                pair.locked_json(path, lock, "granite47")

    def test_pending_cheap_original_artifact_halts_review(self):
        with tempfile.TemporaryDirectory() as d:
            path, lock, _ = zip_fixture(d)
            lock["cheap_v4"]["archive_sha256"] = None
            with self.assertRaisesRegex(ValueError, "not SHA locked"):
                pair.locked_json(path, lock, "cheap_v4")

    def test_extra_member_is_not_allowed_even_when_zip_sha_matches(self):
        with tempfile.TemporaryDirectory() as d:
            path, lock, _ = zip_fixture(d, extra=True)
            with self.assertRaisesRegex(ValueError, "ZIP member"):
                pair.locked_json(path, lock, "granite47")

    def test_sidecar_tamper_rejected_with_valid_outer_digest(self):
        with tempfile.TemporaryDirectory() as d:
            path, lock, _ = zip_fixture(d)
            raw = pair.canonical({"schema": "synthetic.fixture"}) + b"\n"
            with ZipFile(path, "w") as z:
                z.writestr("receipt-granite47.json", raw)
                z.writestr("receipt-granite47.sha256", "0"*64 + "  receipt-granite47.json\n")
            lock["granite47"]["archive_sha256"] = pair.sha(path.read_bytes())
            lock["granite47"]["json_sha256"] = pair.sha(raw)
            with self.assertRaisesRegex(ValueError, "sidecar mismatch"):
                pair.locked_json(path, lock, "granite47")

    def test_nonfinite_probability_denied(self):
        source = {"schema": "hepta.stem.charge-stress.source.v3",
                  "source_plan_sha256": pair.SOURCE_PLAN_SHA,
                  "train": [{"label": i%4} for i in range(64)],
                  "heldout": [{"case_id": f"heldout:{i}"} for i in range(32)]}
        models = {}
        for name in pair.NEURAL:
            models[name] = {
                "schema": "hepta.stem.charge-stress.physical-unattested.v3",
                "cohort": "fee", "candidate": name,
                "source_plan_sha256": pair.SOURCE_PLAN_SHA,
                "authority": "DENY_ALL", "disposition": "HOLD_NO_GO",
                "production_authorized": False, "physical_claim_unattested": True,
                "publisher_future_windows": 0, "matched_421m_lifecycle": False,
                "head_parameters": 27656, "optimizer_steps": 100,
                "initial_head_sha256": "a"*64, "material_manifest_sha256": "b"*64,
                "cost": {"physical_encoder_sequences":96,"encoder_forward_batches":6,
                         "p99_latency_ms":None,"energy_joules":None},
                "rows": [{"case_id": f"heldout:{i}", "source_sha256": str(i),
                          "scores": {k:[0.25]*4 for k in pair.ARMS}} for i in range(32)]}
        source["cohort"] = "fee"
        for r in models.values():
            for i in range(32):
                r["rows"][i]["case_id"] = "heldout:" + str(i)
                r["rows"][i]["source_sha256"] = str(i)
        self.assertEqual(pair.original_nogold(source, models)["original_publisher_labels_opened"], False)
        mutated = copy.deepcopy(models)
        mutated["granite97"]["rows"][0]["scores"]["learned"][0] = float("nan")
        with self.assertRaisesRegex(ValueError, "invalid sealed score"):
            pair.original_nogold(source, mutated)

    def test_pair_same_ids_and_discordance_exact_p(self):
        gold = {f"id:{i}": i%4 for i in range(32)}
        a = dict(gold)
        b = dict(gold)
        for i in range(5):
            b[f"id:{i}"] = (i+1)%4
        result = pair.paired_counts(a, b, gold)
        self.assertEqual(result["candidate_only"], 5)
        self.assertEqual(result["baseline_only"], 0)
        self.assertEqual(result["nominal_exact_mcnemar_p"], 0.0625)
        self.assertEqual(result["delta_accuracy"], 5/32)
        with self.assertRaisesRegex(ValueError, "unmatched"):
            pair.paired_counts(a, {"different":0}, gold)

    def test_holm_three_fixed_neural_pairs(self):
        result = pair.holm({"granite47": .02, "granite97": .005, "mmbert140": .04})
        self.assertEqual(result, {"granite97": .015, "granite47": .04, "mmbert140": .04})
        with self.assertRaisesRegex(ValueError, "unregistered"):
            pair.holm({"granite47": .02})

    def test_no_model_utility_promotion_from_ties(self):
        gold = {f"id:{i}": i%4 for i in range(32)}
        result = pair.paired_counts(gold, gold, gold)
        self.assertEqual(result["delta_accuracy"], 0)
        self.assertEqual(result["nominal_exact_mcnemar_p"], 1)


if __name__ == "__main__":
    unittest.main()
