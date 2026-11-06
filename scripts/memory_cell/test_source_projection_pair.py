"""Regression guards for exact original run pairing, not model-quality evidence."""

import json
import unittest
from unittest import mock

from source_projection_pair import ARMS, SOURCE, compare

FULL = "a" * 40
SPARSE = "b" * 40


def encode(value):
    return json.dumps(value, allow_nan=False).encode()


def fixture(backend):
    items = {name: b"same" for name in SOURCE}
    items["snapshot/READY.json"] = encode(
        dict(
            source_sha="s",
            source_documents_digest="s",
            base_identity="m",
            reader_profile="m",
            scopes=["scope"],
            roots=["root"],
            retained_original_source_bytes=3,
            write_seconds=3.0,
            training=dict(
                loss_backend=backend,
                revision=2,
                examples=2,
                steps=2,
                source_supervision=["source"],
                training_digest="training",
                write_schedule=dict(visits_per_example=[1, 1]),
                input_tokens=20,
                supervised_tokens=4,
                trainable_parameters=4,
                base_unchanged=True,
                full_projection_positions=20,
                actual_projection_positions=20 if backend == "full" else 4,
                losses=[3.0, 2.0],
            ),
        )
    )
    rows = []
    for arm in ARMS:
        empty = arm in ("parameter_only", "empty")
        rows.append(
            dict(
                question_id="q",
                arm=arm,
                kind="new_fact",
                status="succeeded",
                candidate_digest="pool",
                selected=[] if empty else ["id"],
                answer="id",
                receipt=dict(
                    input_ids_digest="empty" if empty else "same",
                    delivered_evidence=[] if empty else ["source"],
                    derived_evidence=[],
                    reader_identity="same",
                    reader_profile="same",
                    knowledge_module_enabled=arm in ("parameter_only", "knowledge"),
                ),
            )
        )
    items["tasks/raw-answers.jsonl"] = b"\n".join(encode(row) for row in rows) + b"\n"
    return items


def diagnostic():
    return dict(
        original_task_count=1,
        original_generation_calls=7,
        actual_optimizer_updates=2,
        strict_task_successes={arm: 0 for arm in ARMS},
        paired_effects={},
        unsupported_empty_context_citation_answers={arm: 0 for arm in ARMS},
        reason_codes=["no_parameter_only_task_gain"],
        research_parameter_candidate_rejected=True,
    )


class PairTests(unittest.TestCase):
    def check(self, full, sparse):
        with mock.patch(
            "source_projection_pair.diagnose",
            side_effect=[diagnostic(), diagnostic()],
        ):
            return compare(full, sparse, full_commit=FULL, sparse_commit=SPARSE)

    def test_same_inputs_and_outputs_are_not_new_task_gain(self):
        result = self.check(fixture("full"), fixture("supervised_positions"))
        self.assertEqual(result["changed_answers"], 0)
        self.assertEqual(result["selected_training_projection_positions"], 4)
        self.assertTrue(result["rejected_parameter_candidate"])
        self.assertFalse(result["production_accepted"])

    def test_answer_change_is_recorded_not_repaired(self):
        full, sparse = fixture("full"), fixture("supervised_positions")
        rows = [
            json.loads(line) for line in sparse["tasks/raw-answers.jsonl"].splitlines()
        ]
        rows[1]["answer"] = "different"
        sparse["tasks/raw-answers.jsonl"] = (
            b"\n".join(encode(row) for row in rows) + b"\n"
        )
        self.assertEqual(self.check(full, sparse)["changed_answers"], 1)

    def test_training_source_prompt_and_pool_drift_fail_closed(self):
        for mode in ("source", "reader", "training", "prompt", "pool", "missing"):
            full, sparse = fixture("full"), fixture("supervised_positions")
            if mode == "source":
                sparse[SOURCE[0]] = b"different"
            elif mode in ("reader", "training"):
                ready = json.loads(sparse["snapshot/READY.json"])
                if mode == "reader":
                    ready["base_identity"] = "changed"
                else:
                    ready["training"]["source_supervision"] = ["changed"]
                sparse["snapshot/READY.json"] = encode(ready)
            else:
                rows = [
                    json.loads(line)
                    for line in sparse["tasks/raw-answers.jsonl"].splitlines()
                ]
                if mode == "prompt":
                    rows[1]["receipt"]["input_ids_digest"] = "different"
                elif mode == "pool":
                    rows[1]["candidate_digest"] = "different"
                else:
                    rows.pop()
                sparse["tasks/raw-answers.jsonl"] = (
                    b"\n".join(encode(row) for row in rows) + b"\n"
                )
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                self.check(full, sparse)

    def test_missing_or_invalid_write_cost_reject(self):
        for value in (0, -1, True, float("nan")):
            full, sparse = fixture("full"), fixture("supervised_positions")
            ready = json.loads(full["snapshot/READY.json"])
            ready["write_seconds"] = value
            full["snapshot/READY.json"] = json.dumps(ready, allow_nan=True).encode()
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.check(full, sparse)


if __name__ == "__main__":
    unittest.main()
