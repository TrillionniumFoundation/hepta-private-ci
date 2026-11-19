"""Forward accounting and paired-diagnostic failure cases, with no model load."""

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from fitting_common import read_json, retain
from fitting_observation import ForwardLedger, classify
import fitting_runner
from model_process import ChildFailure
from source_store import SourceStore


EXAMPLES = [
    dict(prompt_ids=[10, 11], input_ids=[10, 11, 30, 2], labels=[-100, -100, 30, 2]),
    dict(
        prompt_ids=[10, 12],
        input_ids=[10, 12, 31, 32, 2],
        labels=[-100, -100, 31, 32, 2],
    ),
]


class ForwardLedgerTests(unittest.TestCase):
    def test_observed_mask_failure_retains_rejection_before_dispatch(self):
        with tempfile.TemporaryDirectory() as name:
            path = Path(name) / "train-forward-events.jsonl"
            with path.open("x") as stream:
                ledger = ForwardLedger(EXAMPLES, {"training": 1}, stream, [0])
                ledger.begin("training")
                with self.assertRaisesRegex(ValueError, "target mask"):
                    ledger.observe(
                        EXAMPLES[0]["input_ids"], [-100, 11, 30, 2], [1] * 4, False
                    )
                self.assertEqual(
                    ledger.summary(),
                    dict(
                        entered={},
                        completed={},
                        input_tokens={},
                        observed_example_indices=[],
                        rejected_before_forward=1,
                        incomplete_forward=None,
                    ),
                )
            events = [json.loads(line) for line in path.read_text().splitlines()]
            self.assertEqual([e["event"] for e in events], ["rejected_before_forward"])
            self.assertEqual(fitting_runner.event_totals(Path(name))["entered"], 0)

    def test_completed_budget_cannot_admit_an_extra_call_or_refund(self):
        with tempfile.TemporaryDirectory() as name:
            with (Path(name) / "train-forward-events.jsonl").open("x") as stream:
                ledger = ForwardLedger(EXAMPLES, {"training": 1}, stream, [1])
                ledger.begin("training")
                example = EXAMPLES[1]
                ledger.observe(example["input_ids"], example["labels"], [1] * 5, False)
                ledger.after(None, (), {}, None)
                with self.assertRaisesRegex(ValueError, "budget exhausted"):
                    ledger.observe(
                        example["input_ids"], example["labels"], [1] * 5, False
                    )
            self.assertEqual(
                fitting_runner.event_totals(Path(name)),
                dict(
                    entered=1,
                    completed=1,
                    rejected_before_forward=1,
                    entered_input_tokens=5,
                    incomplete_event_lines=0,
                    partial_forward_cost_unknown=False,
                ),
            )

    def test_interrupted_and_malformed_events_remain_unknown_cost(self):
        with tempfile.TemporaryDirectory() as name:
            path = Path(name) / "train-forward-events.jsonl"
            with path.open("x") as stream:
                ledger = ForwardLedger(EXAMPLES, {"training": 2}, stream, [0, 1])
                ledger.begin("training")
                ledger.observe(
                    EXAMPLES[0]["input_ids"], EXAMPLES[0]["labels"], [1] * 4, False
                )
                with self.assertRaisesRegex(ValueError, "pending forward"):
                    ledger.begin("training")
            with path.open("a") as stream:
                stream.write('{"event":\n')
                stream.write(
                    'null\n{"event":"invented"}\n{"event":"entered","input_ids":null}\n'
                )
            self.assertEqual(
                fitting_runner.event_totals(Path(name)),
                dict(
                    entered=1,
                    completed=0,
                    rejected_before_forward=0,
                    entered_input_tokens=4,
                    incomplete_event_lines=4,
                    partial_forward_cost_unknown=True,
                ),
            )

    def test_prefill_requires_prompt_only_no_labels_cache_and_registered_order(self):
        with tempfile.TemporaryDirectory() as name:
            with (Path(name) / "read-forward-events.jsonl").open("x") as stream:
                ledger = ForwardLedger(EXAMPLES, {"reload_prefill": 2}, stream)
                ledger.begin("reload_prefill")
                for ids, labels, cache in (
                    (EXAMPLES[0]["input_ids"], None, True),
                    (EXAMPLES[0]["prompt_ids"], [-100, -100], True),
                    (EXAMPLES[0]["prompt_ids"], None, False),
                    (EXAMPLES[1]["prompt_ids"], None, True),
                ):
                    with self.assertRaises(ValueError):
                        ledger.observe(ids, labels, [1] * len(ids), cache)
                ledger.observe(EXAMPLES[0]["prompt_ids"], None, [1, 1], True)
                ledger.after(None, (), {}, None)
            totals = fitting_runner.event_totals(Path(name))
            self.assertEqual(
                (
                    totals["entered"],
                    totals["completed"],
                    totals["rejected_before_forward"],
                ),
                (1, 1, 4),
            )


def paired_panels():
    teacher = [
        dict(
            example_index=i,
            prompt_sha256=f"prompt-{i}",
            adapter_state_sha256="same",
            target_ids=[i + 20, 2],
            supervised_logits_sha256=f"logits-{i}",
            first={"argmax_id": i + 20},
        )
        for i in range(40)
    ]
    prefill = deepcopy(teacher)
    for row in prefill:
        row["teacher_prefill_max_abs_difference"] = 0.0001
    return deepcopy(teacher), teacher, prefill


class PairedDiagnosisTests(unittest.TestCase):
    def test_same_wrong_first_token_is_fitting_failure_with_stable_save_and_prefill(
        self,
    ):
        panels = paired_panels()
        for panel in panels:
            panel[7]["first"]["argmax_id"] = 999
        result = classify(*panels)
        self.assertEqual(result["classification"], "first_token_fitting_incomplete")
        self.assertEqual(
            (
                result["memory_teacher_wrong_first_tokens"],
                result["save_reload_exact_logit_matches"],
                result["teacher_prefill_first_argmax_differences"],
            ),
            (1, 40, 0),
        )
        self.assertFalse(result["intrinsic_capacity_limit_established"])

    def test_changed_save_logits_are_visible_even_if_argmax_is_identical(self):
        memory, reloaded, prefill = paired_panels()
        reloaded[3]["supervised_logits_sha256"] = "different"
        result = classify(memory, reloaded, prefill)
        self.assertEqual(result["classification"], "save_reload_logits_differ")
        self.assertEqual(
            (
                result["save_reload_exact_logit_matches"],
                result["save_reload_first_argmax_differences"],
            ),
            (39, 0),
        )

    def test_prefill_argmax_difference_is_separate_from_small_numerical_difference(
        self,
    ):
        panels = paired_panels()
        self.assertEqual(
            classify(*panels)["classification"], "first_token_fitting_complete"
        )
        panels[2][8]["first"]["argmax_id"] = 999
        result = classify(*panels)
        self.assertEqual(
            (
                result["classification"],
                result["teacher_prefill_first_argmax_differences"],
            ),
            ("teacher_prefill_argmax_differs", 1),
        )

    def test_unpaired_state_target_prompt_or_truncated_panel_is_rejected(self):
        for key, value in (
            ("example_index", 999),
            ("prompt_sha256", "other"),
            ("adapter_state_sha256", "other"),
            ("target_ids", [777, 2]),
        ):
            panels = paired_panels()
            panels[1][5][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                classify(*panels)
        panels = paired_panels()
        panels[0].pop()
        with self.assertRaisesRegex(ValueError, "complete paired"):
            classify(*panels)


class AuthorityAndFailureTests(unittest.TestCase):
    def test_fresh_authority_has_disjoint_roots_without_undoing_old_withdrawal(self):
        with tempfile.TemporaryDirectory() as name:
            old = SourceStore(
                Path(name) / "old.sqlite", "same-prompt-scope", "old-cell"
            )
            previous = old.write("old-source", "long_00", "color", "orange")
            old.revoke("old-source", 0)
            withdrawn = old.snapshot()
            fresh = SourceStore(
                Path(name) / "fresh.sqlite", "same-prompt-scope", "new-cell"
            )
            current = fresh.write("fresh-source", "long_00", "color", "orange")
            self.assertNotEqual(previous.source_digest, current.source_digest)
            self.assertEqual(old.snapshot(), withdrawn)
            self.assertEqual(
                (
                    old.read("long_00", "color").status.value,
                    fresh.read("long_00", "color").status.value,
                ),
                ("revoked", "answered"),
            )
            self.assertFalse(set(fresh.snapshot()["roots"]) & set(withdrawn["revoked"]))

    def test_final_artifact_overhead_cannot_leave_a_success_receipt(self):
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name)
            (directory / "evidence.bin").write_bytes(b"x" * 100)
            result = {"status": "complete"}
            fitting_runner.seal_result(directory, result, 100)
            self.assertEqual(read_json(directory / "result.json")["status"], "failed")
            self.assertTrue((directory / "evidence.bin").exists())
            self.assertGreater(
                result["artifact_limit_failure"]["bytes_before_result"], 100
            )

    def test_child_failure_retains_process_and_entered_cost_without_reader_retry(self):
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name)
            retain(directory / "base-inventory.json", {})
            protocol = {"base": directory, "limits": {"artifact_bytes": 5_000_000}}
            receipt = dict(
                timed_out=True, returncode=-9, receipt_path="failure-receipt", stderr=""
            )

            def interrupted(*_args, **_kwargs):
                (directory / "train-forward-events.jsonl").write_text(
                    json.dumps(dict(event="entered", input_ids=[10, 11, 30, 2])) + "\n"
                )
                raise ChildFailure("fitting-train", receipt)

            child = Mock(side_effect=interrupted)
            with patch.multiple(
                fitting_runner,
                validate_protocol=lambda *_: protocol,
                base_inventory=lambda *_: {},
                two_cpus=lambda: [],
                bounded=lambda *_: None,
                run_child=child,
            ):
                result = fitting_runner.run(directory, "registered")
            self.assertEqual(child.call_count, 1)
            self.assertEqual(read_json(directory / "train-process.json"), receipt)
            self.assertEqual(
                (
                    result["status"],
                    result["budget_refund"],
                    result["actual_forward_events"]["entered"],
                    result["actual_forward_events"]["completed"],
                ),
                ("failed", 0, 1, 0),
            )
            self.assertTrue(
                result["actual_forward_events"]["partial_forward_cost_unknown"]
            )
            self.assertFalse((directory / "read-process.json").exists())


if __name__ == "__main__":
    unittest.main()
