"""Synthetic fixtures test handoff integrity; never substitute for actual Qwen evidence."""

from copy import deepcopy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import qwen_citation_review_packet as review

ALL = (
    "selected_k",
    "hybrid_k4",
    "hybrid_k6",
    "hybrid_k4_reversed",
    "single_hop",
    "entity_time",
    "organized",
    "program_support",
    "empty",
)


def sample():
    cases, docs, rows = [], [], []
    for k in range(8):
        qid = f"scope{k}"
        cases.append(
            dict(
                query=dict(
                    identity=qid,
                    scope=qid,
                    content=f"Which site {k}?",
                    observed_at="2026-10-11T00:00:00Z",
                )
            )
        )
        source = f"event{k}"
        content = json.dumps(dict(id=source, value="site_1"))
        docs.append(dict(identity=source, scope=qid, root=f"root{k}", content=content))
        for arm in ALL:
            empty = arm == "empty"
            rows.append(
                dict(
                    question_id=qid,
                    arm=arm,
                    status="succeeded",
                    answer="unknown" if empty else "site_1 [E1]",
                    selected=[] if empty else [source],
                    receipt=dict(
                        delivered_evidence=[]
                        if empty
                        else [
                            dict(
                                original_id=source,
                                label="E1",
                                excerpt=content,
                                source_digest=review.digest(content),
                                root=f"root{k}",
                                scope=qid,
                                source_start=0,
                                source_end=len(content.encode()),
                            )
                        ]
                    ),
                )
            )
    for k in range(100):
        docs.append(
            dict(identity=f"extra{k}", scope="extra", root="extra", content="x")
        )
    original = {
        "plan/plan.json": json.dumps(dict(cases=cases)).encode(),
        "plan/source-view.json": json.dumps(docs).encode(),
    }
    full = {"tested-commit.txt": review.SOURCE_PINS["A"]["commit"].encode()}
    original_receipt = dict(
        generating_commit=review.SOURCE_PINS["A"]["commit"],
        model_identity="f9aa334d3a02cabececea367c283caf66ef9875132907ebc34dac1c8d3a7f225",
        calibration=dict(attempts=40, all_model_calls_succeeded=True),
        evaluation=dict(attempts=72, all_model_calls_succeeded=True),
        production_accepted=False,
    )
    replay = {"shard-replay.json": json.dumps(original_receipt).encode()}
    full["evaluation/raw-answers.jsonl"] = (
        "\n".join(json.dumps(r) for r in rows) + "\n"
    ).encode()
    return original, full, replay, rows


class ReviewerPacketTests(unittest.TestCase):
    def generate(self, fixture):
        source, full, replay, _ = fixture
        with (
            patch.object(review, "open_sealed", side_effect=(source, full, replay)),
            patch.object(
                review, "PLAN", review.sha256(source["plan/plan.json"]).hexdigest()
            ),
        ):
            return review.packet(
                Path("source.zip"), Path("full.zip"), Path("replay.zip")
            )

    def test_complete_output_has_40_blinded_original_answers(self):
        result = self.generate(sample())
        self.assertEqual(result["review_items"], 40)
        self.assertEqual(len({r["review_id"] for r in result["items"]}), 40)
        self.assertFalse(result["independent_human_review_performed"])
        self.assertFalse(result["candidate_accepted"])
        self.assertFalse(result["production_accepted"])
        for row in result["items"]:
            self.assertTrue(row["original_answer"])
            self.assertEqual(row["claim_judgement"], "unreviewed")
            self.assertFalse(
                {"arm", "kind", "expected", "support", "strict_task_success"}
                & row.keys()
            )

    def test_byte_reproducible_review_order(self):
        first = self.generate(sample())
        self.assertEqual(first, self.generate(sample()))
        self.assertEqual(
            [r["review_id"] for r in first["items"]],
            sorted(r["review_id"] for r in first["items"]),
        )

    def test_tampered_original_excerpt_rejected(self):
        files = list(sample())
        files[3][0]["receipt"]["delivered_evidence"][0]["excerpt"] = "altered"
        files[1]["evaluation/raw-answers.jsonl"] = (
            "\n".join(json.dumps(r) for r in files[3]) + "\n"
        ).encode()
        with self.assertRaisesRegex(ValueError, "source detached"):
            self.generate(files)

    def test_missing_attempt_rejected(self):
        files = list(sample())
        files[3].pop()
        files[1]["evaluation/raw-answers.jsonl"] = (
            "\n".join(json.dumps(r) for r in files[3]) + "\n"
        ).encode()
        with self.assertRaisesRegex(ValueError, "nine-arm reader census"):
            self.generate(files)

    def test_incomplete_auditor_rejected(self):
        files = list(sample())
        receipt = json.loads(files[2]["shard-replay.json"])
        receipt["evaluation"]["attempts"] = 71
        files[2]["shard-replay.json"] = json.dumps(receipt).encode()
        with self.assertRaisesRegex(ValueError, "mechanical independent replay"):
            self.generate(files)

    def test_hallucinated_label_is_not_erased(self):
        files = list(sample())
        files[3][0]["answer"] = "site_1 [E9]"
        files[1]["evaluation/raw-answers.jsonl"] = (
            "\n".join(json.dumps(r) for r in files[3]) + "\n"
        ).encode()
        result = self.generate(files)
        self.assertEqual(
            sum("E9" in r["unknown_citation_labels"] for r in result["items"]), 1
        )


if __name__ == "__main__":
    unittest.main()
