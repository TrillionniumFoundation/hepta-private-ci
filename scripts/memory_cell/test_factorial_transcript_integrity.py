"""Synthetic protocol regressions only; these do not run any reader."""

import copy
import unittest

from factorial_evidence_gate import ARMS, CONDITIONS, READERS, sha
from factorial_transcript_integrity import audit, text_sha
from test_factorial_evidence_gate import fixture


def example():
    plan, rows = fixture()
    transcripts = []
    for case in plan["cases"]:
        cid = case["id"]
        critical = {
            "id": "premise",
            "text": f"unique prerequisite for {cid}",
        }
        other = {
            "id": "other",
            "text": f"unrelated old context for {cid}",
        }
        case["question_sha256"] = text_sha(f"question for {cid}")
        case["admitted_evidence"] = [
            {"id": source["id"], "sha256": text_sha(source["text"])}
            for source in (critical, other)
        ]
        case["premise_sha256"] = text_sha(critical["text"])
        case["oracle_source_sha256"] = sha([critical, other])
        for arm in ARMS:
            for condition in CONDITIONS:
                for reader in READERS:
                    evidence = {
                        "none": [],
                        "hybrid": [other],
                        "oracle": [critical, other],
                        "ablated": [other],
                    }[condition]
                    if arm == "knowledge_only":
                        evidence = []
                    row = next(
                        r
                        for r in rows
                        if (
                            r["id"],
                            r["arm"],
                            r["condition"],
                            r["reader"],
                        )
                        == (cid, arm, condition, reader)
                    )
                    row.update(
                        source_digest=sha(evidence),
                        answer_digest=text_sha("original unedited answer"),
                        prompt_digest=text_sha("identical frozen template"),
                        reader_revision=f"model-{reader}-sha",
                    )
                    transcripts.append(
                        {
                            "id": cid,
                            "arm": arm,
                            "condition": condition,
                            "reader": reader,
                            "question": f"question for {cid}",
                            "delivered_evidence": copy.deepcopy(evidence),
                            "raw_answer": "original unedited answer",
                            "prompt_template": "identical frozen template",
                            "reader_revision": f"model-{reader}-sha",
                        }
                    )
    for row in rows:
        row["plan_sha256"] = sha(plan)
    return plan, rows, transcripts


class OriginalTranscriptGateTests(unittest.TestCase):
    def test_complete_unmodified_transcript_binds_bytes(self):
        plan, rows, transcripts = example()
        report = audit(plan, rows, transcripts)
        self.assertEqual(report["transcript_count"], 160)
        self.assertEqual(report["oracle_and_exact_lesion_case_count"], 4)
        self.assertTrue(report["all_original_answers_and_sources_byte_bound"])
        self.assertFalse(report["independent_task_success_adjudicated"])
        self.assertFalse(report["production_accepted"])

    def test_detect_scored_answer_rewrite(self):
        plan, rows, transcripts = example()
        transcripts[0]["raw_answer"] = "rewritten after reading truth"
        with self.assertRaisesRegex(ValueError, "raw answer"):
            audit(plan, rows, transcripts)

    def test_detect_delivered_evidence_rewrite(self):
        plan, rows, transcripts = example()
        target = next(t for t in transcripts if t["condition"] == "oracle")
        target["delivered_evidence"][0]["text"] = "forged premise"
        with self.assertRaisesRegex(ValueError, "unregistered source bytes"):
            audit(plan, rows, transcripts)

    def test_detect_a_wrong_ablation_even_when_rehashed(self):
        plan, rows, transcripts = example()
        for transcript in transcripts:
            if (
                transcript["condition"] == "ablated"
                and transcript["arm"] != "knowledge_only"
            ):
                transcript["delivered_evidence"] = [
                    {
                        "id": "premise",
                        "text": f"unique prerequisite for {transcript['id']}",
                    }
                ]
                row = next(
                    r
                    for r in rows
                    if all(
                        r[k] == transcript[k]
                        for k in ("id", "arm", "reader", "condition")
                    )
                )
                row["source_digest"] = sha(transcript["delivered_evidence"])
        with self.assertRaisesRegex(ValueError, "ablation must remove exactly"):
            audit(plan, rows, transcripts)

    def test_detect_missing_transcript_and_duplicate(self):
        plan, rows, transcripts = example()
        with self.assertRaisesRegex(ValueError, "incomplete original transcript"):
            audit(plan, rows, transcripts[:-1])
        with self.assertRaisesRegex(ValueError, "duplicate raw transcript"):
            audit(plan, rows, transcripts + [transcripts[0]])

    def test_detect_empty_arm_evidence_leak(self):
        plan, rows, transcripts = example()
        # Keep frozen/reference source equality intact, so the test exercises
        # the no-original-body contract rather than an earlier reader-parity gate.
        for target in transcripts:
            if target["arm"] != "knowledge_only" or target["condition"] != "hybrid":
                continue
            target["delivered_evidence"] = [
                {
                    "id": "other",
                    "text": f"unrelated old context for {target['id']}",
                }
            ]
            row = next(
                r
                for r in rows
                if all(r[k] == target[k] for k in ("id", "arm", "reader", "condition"))
            )
            row["source_digest"] = sha(target["delivered_evidence"])
        with self.assertRaisesRegex(ValueError, "no-evidence / parametric-only"):
            audit(plan, rows, transcripts)

    def test_detect_changed_question_and_template(self):
        plan, rows, transcripts = example()
        transcripts[0]["question"] = "different task"
        with self.assertRaisesRegex(ValueError, "question bytes"):
            audit(plan, rows, transcripts)
        plan, rows, transcripts = example()
        transcripts[0]["prompt_template"] = "different template"
        with self.assertRaisesRegex(ValueError, "prompt-template bytes"):
            audit(plan, rows, transcripts)


if __name__ == "__main__":
    unittest.main()
