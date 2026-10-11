"""Synthetic byte-identity, blinding and no-gold human review handoff tests."""

import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from native import digest
from stem_blind_review_packet import make_blind_review_packet
from stem_blind_review_export import export_worklist, SOURCE, TREE, ZIP_SHA

ARMS = (
    "frozen_rerank",
    "prototype",
    "linear",
    "gated",
    "lineage_lora_gated",
    "independent_lora_gated",
)
PHASES = ("select", "retention", "test", "transfer")
STAGES = (16, 32, 48)
PIN = "c" * 40
ID = "fixed-reader"
PROFILE = "same-prompt"


def query(qid):
    return dict(
        identity=qid,
        family="family-" + qid,
        scope="scope-" + qid,
        content="What did the source say?",
        observed_at="2024-01-01",
    )


def receipt(qid, evidence):
    q = query(qid)
    return dict(
        generator_identity=ID,
        generator_profile=PROFILE,
        observable_query=q,
        delivered_evidence=evidence,
        canonical_request_digest=digest((ID, PROFILE, q, evidence)),
    )


def sample():
    question_ids = {"train": [f"train-{i}" for i in range(48)]}
    question_ids.update({phase: [f"{phase}-{i}" for i in range(8)] for phase in PHASES})
    plan = dict(
        schema="hepta.stem-cell.native-development.v1",
        source_commit=PIN,
        questions=question_ids,
        arms=list(ARMS),
        curriculum_attempted_examples=list(STAGES),
        question_families={
            qid: "original-" + qid for values in question_ids.values() for qid in values
        },
    )
    rows, empty = [], []
    for phase in PHASES:
        for qid in question_ids[phase]:
            source = [
                dict(
                    label="E1",
                    root="root",
                    scope="scope-" + qid,
                    observed_at="2023-12-31",
                    excerpt="Original source evidence.",
                    id="source-original-id",
                )
            ]
            for stage in STAGES:
                for arm in ARMS:
                    row = dict(
                        stage=stage,
                        phase=phase,
                        question_id=qid,
                        arm=arm,
                        status="succeeded",
                        family="original-" + qid,
                    )
                    if stage == 48 and arm == "frozen_rerank":
                        row.update(
                            answer="Source-backed answer [E1]",
                            receipt=receipt(qid, source),
                        )
                    rows.append(row)
            empty.append(
                dict(
                    phase=phase,
                    question_id=qid,
                    evidence_count=0,
                    family="original-" + qid,
                    status="succeeded",
                    answer="Hallucinated citation [E1]",
                    receipt=receipt(qid, []),
                )
            )
    return plan, rows, empty


class BlindReviewPacketTests(unittest.TestCase):
    def test_complete_no_gold_32_by_two(self):
        packet, mapping = make_blind_review_packet(*sample())
        self.assertEqual(packet["original_cases"], 32)
        self.assertEqual(packet["reader_conditions"], 64)
        self.assertEqual(len(packet["reviewer_packets"]), 32)
        self.assertEqual(len(mapping["blinded_case_mapping"]), 32)
        self.assertFalse(packet["independent_review_certified"])
        self.assertFalse(packet["production_accepted"])
        self.assertTrue(packet["no_gold_answers_read"])
        for case in packet["reviewer_packets"]:
            self.assertEqual(len(case["conditions"]), 2)
            self.assertEqual({v["slot"] for v in case["conditions"]}, {"A", "B"})
            self.assertNotIn("answer_key", case)
            self.assertNotIn("native_source_correct", case)
            self.assertNotIn("source_family", case)
            self.assertNotIn("arm", case)
            self.assertTrue(case["source_sufficiency_review_pending"])
            self.assertTrue(
                all(x["reviewer_verdict"] is None for x in case["conditions"])
            )

    def test_empty_context_citation_is_structurally_unbound(self):
        packet, mapping = make_blind_review_packet(*sample())
        for case, meta in zip(
            packet["reviewer_packets"], mapping["blinded_case_mapping"], strict=True
        ):
            no_source_slot = next(
                k for k, v in meta["opaque_slots"].items() if v["role"] == "empty"
            )
            slot = next(x for x in case["conditions"] if x["slot"] == no_source_slot)
            self.assertEqual(slot["delivered_evidence"], [])
            self.assertEqual(slot["structurally_unbound_markers"], 1)
        self.assertIsNone(packet["semantic_citation_precision"])

    def test_original_utf8_answer_bytes_are_cryptographically_bound(self):
        import hashlib

        packet, meta = make_blind_review_packet(*sample())
        entry = meta["blinded_case_mapping"][0]
        original = next(
            v for v in entry["opaque_slots"].values() if v["role"] == "fixed"
        )
        expected = hashlib.sha256(
            "Source-backed answer [E1]".encode("utf-8")
        ).hexdigest()
        self.assertEqual(original["answer_digest"], expected)
        self.assertEqual(len(packet["reviewer_packets"]), 32)

    def test_emitted_e0_marker_is_invalid_not_ignored(self):
        plan, rows, empty = sample()
        empty[0]["answer"] = "Unsupported marker [E0] and [E1]"
        packet, mapping = make_blind_review_packet(plan, rows, empty)
        blank_slot = next(
            slot
            for slot, info in mapping["blinded_case_mapping"][0]["opaque_slots"].items()
            if info["role"] == "empty"
        )
        condition = next(
            x
            for x in packet["reviewer_packets"][0]["conditions"]
            if x["slot"] == blank_slot
        )
        self.assertEqual(condition["structurally_unbound_markers"], 2)
        self.assertFalse(condition["independent_semantic_review_completed"])

    def test_raw_answer_and_evidence_digest_tampering_rejects(self):
        for mode in ("request", "evidence", "reader-question"):
            plan, rows, empty = sample()
            target = next(
                x for x in rows if x["stage"] == 48 and x["arm"] == "frozen_rerank"
            )
            if mode == "request":
                target["receipt"]["canonical_request_digest"] = "f" * 64
            elif mode == "evidence":
                target["receipt"]["delivered_evidence"][0]["excerpt"] = "Changed!"
            else:
                target["receipt"]["observable_query"]["content"] = "Altered"
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                make_blind_review_packet(plan, rows, empty)

    def test_reader_model_or_prompt_drift_rejected(self):
        for field in ("generator_identity", "generator_profile"):
            plan, rows, empty = sample()
            empty[0]["receipt"][field] = "unmatched-reader"
            with self.subTest(field=field), self.assertRaises(ValueError):
                make_blind_review_packet(plan, rows, empty)

    def test_future_or_cross_scope_evidence_rejected(self):
        for field, forged in (("observed_at", "2025-01-01"), ("scope", "other-scope")):
            plan, rows, empty = sample()
            item = next(
                x for x in rows if x["stage"] == 48 and x["arm"] == "frozen_rerank"
            )
            evidence = item["receipt"]["delivered_evidence"]
            evidence[0][field] = forged
            item["receipt"]["canonical_request_digest"] = digest(
                (
                    ID,
                    PROFILE,
                    item["receipt"]["observable_query"],
                    evidence,
                )
            )
            with self.subTest(field=field), self.assertRaises(ValueError):
                make_blind_review_packet(plan, rows, empty)

    def test_missing_extra_duplicate_and_cross_phase_fail_closed(self):
        for kind in ("missing", "duplicate", "unknown", "extra-zero"):
            plan, rows, empty = sample()
            if kind == "missing":
                rows.pop()
            elif kind == "duplicate":
                rows[-1] = copy.deepcopy(rows[0])
            elif kind == "unknown":
                rows[0]["question_id"] = "heldout-not-registered"
            else:
                empty.append(dict(empty[0]))
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                make_blind_review_packet(plan, rows, empty)

    def test_failed_frozen_answer_kept_in_review_denominator(self):
        plan, rows, empty = sample()
        target = next(
            x for x in rows if x["stage"] == 48 and x["arm"] == "frozen_rerank"
        )
        target["status"] = "failed"
        target.pop("answer")
        target.pop("receipt")
        packet, mapping = make_blind_review_packet(plan, rows, empty)
        self.assertEqual(packet["reader_conditions"], 64)
        self.assertEqual(packet["status_counts"]["unreviewable-reader-failure"], 1)
        self.assertEqual(packet["status_counts"]["unreviewed"], 63)
        self.assertEqual(len(mapping["blinded_case_mapping"]), 32)

    def test_identical_empty_requests_are_detected_not_double_counted(self):
        plan, rows, empty = sample()
        target = next(
            x for x in rows if x["stage"] == 48 and x["arm"] == "frozen_rerank"
        )
        target["receipt"] = receipt(target["question_id"], [])
        target["answer"] = "Different raw answer"
        _, mapping = make_blind_review_packet(plan, rows, empty)
        self.assertEqual(
            mapping["blinded_case_mapping"][0]["identical_request_if_both_succeeded"],
            True,
        )
        self.assertEqual(
            mapping["blinded_case_mapping"][0]["distinct_original_requests"], 1
        )

    def test_source_family_and_frozen_selected_window_drift_reject(self):
        for mode in ("family", "selection"):
            plan, rows, empty = sample()
            target = next(
                x for x in rows if x["stage"] == 48 and x["arm"] == "frozen_rerank"
            )
            if mode == "family":
                target["family"] = "independent-incorrect-family"
            else:
                target["selected"] = None
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                make_blind_review_packet(plan, rows, empty)

    def test_failed_zero_reader_is_retained_without_forged_evidence(self):
        plan, rows, empty = sample()
        zero = empty[0]
        zero["status"] = "failed"
        zero.pop("answer")
        zero.pop("receipt")
        work, provenance = make_blind_review_packet(plan, rows, empty)
        self.assertEqual(work["reader_conditions"], 64)
        self.assertEqual(work["status_counts"]["unreviewable-reader-failure"], 1)
        self.assertEqual(len(provenance["blinded_case_mapping"]), 32)

    def test_export_reads_no_gold_or_privileged_oracle_bytes(self):
        plan, predictions, zero = sample()
        plan["source_commit"] = SOURCE
        accesses = []

        class FakePinnedArchive:
            sha256 = ZIP_SHA
            manifest_entries = 146

            def __init__(self, path, sha):
                self.closed = False
                assert sha == ZIP_SHA

            def read(self, member):
                accesses.append(member)
                return (SOURCE if member == "tested-commit.txt" else TREE).encode()

            def json(self, member):
                accesses.append(member)
                if member != "comparison/preregistered.json":
                    raise AssertionError("target/gold source read by worklist")
                return plan

            def jsonl(self, member):
                accesses.append(member)
                if member == "comparison/policy-predictions.jsonl":
                    return predictions
                if member == "comparison/reader-no-evidence.jsonl":
                    return zero
                raise AssertionError("model output replaced by gold/oracle")

            def close(self):
                self.closed = True

        with tempfile.TemporaryDirectory() as d:
            with patch("stem_blind_review_export.PinnedArchive", FakePinnedArchive):
                dst = Path(d) / "owner-packet"
                summary = export_worklist(Path("fake-pinned.zip"), dst)
                self.assertEqual(summary["unsigned_review_slots"], 64)
                self.assertEqual(summary["actual_reviewer_verdicts"], 0)
                self.assertFalse(summary["independently_adjudicated_entailment"])
                reviewer = [
                    json.loads(x)
                    for x in (dst / "blind-question-answer-worklist.jsonl")
                    .read_text()
                    .splitlines()
                ]
                template = [
                    json.loads(x)
                    for x in (dst / "unsigned-reviewer-return-template.jsonl")
                    .read_text()
                    .splitlines()
                ]
                self.assertEqual(len(reviewer), 32)
                self.assertEqual(len(template), 64)
                self.assertTrue(
                    all(x["reviewer_attestation"] is None for x in template)
                )
                with self.assertRaises(FileExistsError):
                    export_worklist(Path("fake-pinned.zip"), dst)
        self.assertEqual(
            set(accesses),
            {
                "tested-commit.txt",
                "tested-tree.txt",
                "comparison/preregistered.json",
                "comparison/policy-predictions.jsonl",
                "comparison/reader-no-evidence.jsonl",
            },
        )

    def test_generated_packet_drops_injected_gold_labels_and_oracle(self):
        plan, rows, empty = sample()
        plan["gold_answers"] = {"select-0": "secret-target"}
        rows[0]["oracle_answer"] = "secret"
        packet, _ = make_blind_review_packet(plan, rows, empty)
        serialized = repr(packet)
        self.assertNotIn("secret", serialized)
        self.assertNotIn("frozen_rerank", serialized)
        self.assertNotIn("oracle_answer", serialized)


if __name__ == "__main__":
    unittest.main()
