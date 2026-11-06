"""Read-only audit regressions; fixtures are not task-benefit evidence."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from native import digest
from stem_audit import ARMS, CURVE, PHASES, record_key, validate_records
from stem_audit_archive import AuditError, PinnedArchive, parse_json


def fixture():
    plan = dict(
        arms=list(ARMS),
        curriculum_attempted_examples=list(CURVE),
        questions={p: [p] for p in PHASES},
        question_families={p: "family" for p in PHASES},
    )
    raw, first = [], {}
    for stage in CURVE:
        for phase in PHASES:
            for arm in ARMS:
                query = dict(
                    identity=phase,
                    scope=phase,
                    family="family",
                    content="Question",
                    observed_at="2024",
                )
                receipt = dict(
                    generator_identity="reader",
                    generator_profile="profile",
                    observable_query=query,
                    delivered_evidence=[],
                    generation_seconds=0.1,
                    canonical_request_digest=digest(("reader", "profile", query, [])),
                )
                row = dict(
                    stage=stage,
                    phase=phase,
                    question_id=phase,
                    family="family",
                    arm=arm,
                    status="succeeded",
                    selected=0,
                    answer="original",
                )
                actual = phase not in first
                receipt.update(
                    actual_reader_execution=actual,
                    reused_from=None if actual else first[phase],
                    incremental_generation_seconds=0.1 if actual else 0.0,
                )
                row["receipt"] = receipt
                first.setdefault(phase, record_key(row))
                raw.append(row)
    scored = [
        dict(
            deepcopy(r),
            source_choice_correct=1,
            diagnostic_answer_f1=0.5,
            citation_structure=dict(semantic_precision=None),
        )
        for r in raw
    ]
    oracles = [
        dict(
            phase=p,
            question_id=p,
            status="unavailable",
            policy_comparator=False,
            semantic_entailment_independently_verified=False,
        )
        for p in PHASES
    ]
    report = dict(
        plan=deepcopy(plan),
        production_accepted=False,
        superiority_claim=False,
        logical_policy_attempts=72,
        reader=dict(
            actual_attempts=4,
            actual_successes=4,
            actual_failed_attempts=0,
            cache_hits=68,
        ),
        metrics={
            f"{s}/{p}/{a}": dict(
                attempted=1, succeeded=1, failed=0, source_accuracy=1, diagnostic_f1=0.5
            )
            for s in CURVE
            for p in PHASES
            for a in ARMS
        },
    )
    return dict(plan=plan, raw=raw, scored=scored, oracles=oracles, report=report)


class RecordAuditTests(unittest.TestCase):
    def test_complete_census_and_direct_reuse_reconcile_without_model(self):
        result = validate_records(**fixture())
        self.assertEqual(result["policy_counts"], {"succeeded": 72})
        self.assertEqual(result["reader_actual_successes"], 4)
        self.assertEqual(result["reader_cache_hits"], 68)
        self.assertTrue(result["policy_matrix_succeeded"])
        self.assertFalse(result["production_accepted"])
        self.assertEqual(result["new_model_calls"], 0)

    def test_missing_duplicate_and_score_rewrites_reject(self):
        for change in ("missing", "duplicate", "answer", "family"):
            data = fixture()
            if change == "missing":
                data["raw"].pop()
            elif change == "duplicate":
                data["raw"][-1] = data["raw"][0]
            else:
                data["scored"][0][change] = "changed"
            with self.assertRaises(AuditError):
                validate_records(**data)

    def test_resealed_reused_query_cannot_change_original_request(self):
        data = fixture()
        receipt = data["raw"][1]["receipt"]
        receipt["observable_query"]["content"] = "different question"
        receipt["canonical_request_digest"] = digest(
            ("reader", "profile", receipt["observable_query"], [])
        )
        data["scored"][1]["receipt"] = deepcopy(receipt)
        with self.assertRaisesRegex(AuditError, "reuse changed"):
            validate_records(**data)

    def test_reuse_must_point_back_to_actual_execution(self):
        for parent in ("missing", "16/select/select/prototype", "48/test/test/gated"):
            data = fixture()
            data["raw"][1]["receipt"]["reused_from"] = parent
            data["scored"][1]["receipt"]["reused_from"] = parent
            with self.assertRaisesRegex(AuditError, "reuse reference"):
                validate_records(**data)

    def test_failed_native_matrix_can_have_successful_accounting_audit(self):
        data = fixture()
        row = data["raw"][-1]
        row.pop("receipt")
        row.pop("answer")
        row.update(status="failed", error_type="ValueError", error="before Reader")
        data["scored"][-1] = dict(
            deepcopy(row),
            source_choice_correct=0,
            diagnostic_answer_f1=0.0,
            citation_structure=dict(semantic_precision=None),
        )
        data["report"]["reader"]["cache_hits"] -= 1
        data["report"]["metrics"]["48/transfer/independent_lora_gated"] = dict(
            attempted=1, succeeded=0, failed=1, source_accuracy=0, diagnostic_f1=0.0
        )
        result = validate_records(**data)
        self.assertTrue(result["accounting_verified"])
        self.assertFalse(result["policy_matrix_succeeded"])
        self.assertEqual(result["policy_counts"], {"succeeded": 71, "failed": 1})
        self.assertEqual(result["reader_cache_hits"], 67)

    def test_oracle_promotion_and_counter_fabrication_reject(self):
        for change in ("oracle", "counter", "boolean", "score"):
            data = fixture()
            if change == "oracle":
                data["oracles"][0]["policy_comparator"] = True
            elif change == "counter":
                data["report"]["reader"]["cache_hits"] += 1
            elif change == "boolean":
                data["report"]["reader"]["actual_attempts"] = True
            else:
                data["scored"][0]["diagnostic_answer_f1"] = float("nan")
            with self.assertRaises(AuditError):
                validate_records(**data)

    def test_unjournalled_failed_reader_calls_remain_unverified(self):
        data = fixture()
        data["report"]["reader"].update(actual_attempts=5, actual_failed_attempts=1)
        result = validate_records(**data)
        self.assertFalse(result["reader_failed_calls_individually_verified"])


class ArchiveAuditTests(unittest.TestCase):
    def test_external_pin_and_exact_manifest_both_required(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "artifact.zip"
            payload = b"original"
            member_pin = hashlib.sha256(payload).hexdigest()
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("record.txt", payload)
                archive.writestr("SHA256SUMS", f"{member_pin}  ./record.txt\n")
            pin = hashlib.sha256(path.read_bytes()).hexdigest()
            opened = PinnedArchive(path, pin)
            self.assertEqual(opened.manifest_entries, 1)
            self.assertEqual(opened.read("record.txt"), payload)
            opened.close()
            with self.assertRaisesRegex(AuditError, "external ZIP digest"):
                PinnedArchive(path, "0" * 64)
            with zipfile.ZipFile(path, "a") as archive:
                archive.writestr("unlisted.txt", "extra")
            new_pin = hashlib.sha256(path.read_bytes()).hexdigest()
            with self.assertRaisesRegex(AuditError, "manifest file census"):
                PinnedArchive(path, new_pin)

    def test_path_traversal_is_not_extracted_or_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "artifact.zip"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("../outside", "bad")
            pin = hashlib.sha256(path.read_bytes()).hexdigest()
            with self.assertRaisesRegex(AuditError, "unsafe"):
                PinnedArchive(path, pin)
            self.assertFalse((Path(tmp).parent / "outside").exists())

    def test_duplicate_json_and_nonfinite_constants_reject(self):
        for payload in ('{"a":1,"a":2}', '{"a":NaN}', '{"a":Infinity}'):
            with self.assertRaises(AuditError):
                parse_json(payload)
        self.assertEqual(parse_json(json.dumps({"text": "原文"})), {"text": "原文"})


if __name__ == "__main__":
    unittest.main()
