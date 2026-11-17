"""Engineering integration tests with scripted outputs, never model evidence."""

import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from . import data, repo_execution as execution, repo_interaction_v3 as interaction
from .chat_protocol import native_examples, training_messages
from .protocol_v3 import LEGACY_ILLUSTRATION, prepare_record, verify_reference
from .test_data import record
from .test_repo_execution import answer


class ScriptedPredictor:
    """A deterministic test fixture; no model is loaded or credited with success."""

    model_digest = "a" * 64

    def __init__(self, answers):
        self.answers, self.requests, self.closed = iter(answers), [], False

    def predict(self, request):
        self.requests.append(copy.deepcopy(request))
        return {
            "answer": next(self.answers),
            "loaded_model_digest": self.model_digest,
            "input_sha256": hashlib.sha256(
                request["task"]["input"].encode()
            ).hexdigest(),
            "messages_sha256": data.digest(request["task"].get("messages", [])),
            "input_tokens": 3,
            "output_tokens": 2,
            "hit_output_limit": False,
        }

    def close(self):
        self.closed = True


class InteractionV3Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        execution.load_catalog()
        original = record()
        original["task"]["input"] = (
            "Test subject(state, name), which increments that named counter. "
            "Cover a zero and nonzero count. " + LEGACY_ILLUSTRATION
        )
        original["task"]["verifier"] = {
            "name": "repo_patch",
            "version": "1",
            "parameters": {
                "fixture_id": "A-counter",
                "fixture_sha256": data.digest(execution._CATALOG["A-counter"]),
            },
        }
        initial = {
            "phase": "before_edit",
            "assertion_count": 0,
            "business_contract_covered": False,
            "test_source": execution.TEMPLATE,
        }
        original["task"]["messages"] = [
            {"role": "user", "content": original["task"]["input"]},
            {"role": "tool", "content": data.canonical(initial).decode()},
        ]
        original["trajectory"] = []
        original["final_answer"] = answer(
            '    assert subject({"calls": 0}, "calls") == {"calls": 1}\n'
            '    assert subject({"calls": 7}, "calls") == {"calls": 8}'
        )
        reference = data.verify_answer(original, original["final_answer"])
        if not reference["success"]:
            raise AssertionError("the engineering fixture reference did not execute")
        original["verified_outcome"] = {
            "success": True,
            "receipt_sha256": reference["receipt_sha256"],
            "verifier_name": "repo_patch",
            "verifier_version": "1",
        }
        cls.original, cls.prepared = original, prepare_record(original)
        # A different successful answer ensures no authored-reference substitution.
        cls.correct = answer(
            '    assert subject({"calls": 0}, "calls") == {"calls": 1}\n'
            '    assert subject({"calls": 5}, "calls") == {"calls": 6}'
        )

    def test_json_and_ast_rejections_feed_a_real_successful_retry(self):
        for bad in ('{"edits":[', answer("    import math\n    assert subject(0)")):
            with self.subTest(bad=bad), tempfile.TemporaryDirectory() as tmp:
                predictor = ScriptedPredictor([bad, self.correct])
                before = copy.deepcopy(self.prepared)
                with patch.object(
                    execution.subprocess, "run", wraps=execution.subprocess.run
                ) as run:
                    result = interaction.attempts(
                        predictor, self.prepared, Path(tmp) / "run"
                    )
                self.assertEqual(run.call_count, 1)
                first, second = result["steps"]
                observed = json.loads(first["feedback"])
                self.assertTrue(observed["format_error"])
                self.assertLessEqual(len(observed["format_error"].encode()), 256)
                self.assertEqual(
                    [
                        first["executed"],
                        first["verification"]["success"],
                        second["executed"],
                        second["verification"]["success"],
                        result["first_attempt_success"],
                        result["success"],
                    ],
                    [False, False, True, True, False, True],
                )
                self.assertEqual(
                    predictor.requests[1]["task"]["messages"],
                    [
                        *predictor.requests[0]["task"]["messages"],
                        {"role": "assistant", "content": bad},
                        {"role": "tool", "content": first["feedback"]},
                    ],
                )
                raw = [
                    json.loads((Path(tmp) / "run" / f"output-{n}.json").read_text())[
                        "answer"
                    ]
                    for n in (0, 1)
                ]
                self.assertEqual(raw, [bad, self.correct])
                self.assertNotEqual(raw[1], self.original["final_answer"])
                self.assertEqual(self.prepared, before)
                for request in predictor.requests:
                    for message in request["task"]["messages"]:
                        self.assertNotIn(
                            self.original["final_answer"], message["content"]
                        )
                receipt = second["verification"]
                self.assertEqual(
                    receipt["receipt_sha256"],
                    data.digest(
                        {
                            k: v
                            for k, v in receipt.items()
                            if k not in ("receipt_sha256", "success")
                        }
                    ),
                )
                self.assertEqual(second["execution_summary"]["subject_call_count"], 2)
                self.assertEqual(
                    [r["passed"] for r in receipt["result"]["result"]["observations"]],
                    [True, False, False],
                )

    def test_type_error_does_not_become_a_control_kill_score(self):
        bad = answer('    assert subject({"calls": 0}) == {"calls": 1}')
        with tempfile.TemporaryDirectory() as tmp:
            result = interaction.attempts(
                ScriptedPredictor([bad, self.correct]), self.prepared, Path(tmp) / "run"
            )
        first, second = result["steps"]
        measured = first["verification"]["result"]["result"]
        self.assertEqual(measured["controls_rejected"], measured["control_count"])
        observed = json.loads(first["feedback"])
        self.assertEqual(
            {
                key: observed[key]
                for key in (
                    "success",
                    "execution_performed",
                    "original_passed",
                    "original_error_type",
                    "completed_original_calls",
                    "control_comparison_informative",
                    "controls_rejected",
                    "control_count",
                )
            },
            {
                "success": False,
                "execution_performed": True,
                "original_passed": False,
                "original_error_type": "TypeError",
                "completed_original_calls": 0,
                "control_comparison_informative": False,
                "controls_rejected": None,
                "control_count": None,
            },
        )
        self.assertIsNone(first["execution_summary"]["subject_call_attempt_count"])
        self.assertEqual(
            first["execution_summary"]["verification_receipt_sha256"],
            first["verification"]["receipt_sha256"],
        )
        self.assertTrue(second["verification"]["success"])

    def test_syntax_admission_and_weak_assertions_are_not_success(self):
        variants = (
            answer('    assert subject({"calls": 0}, "calls") is not None'),
            answer('    assert subject({"calls": 0}, "calls") == {"calls": 9}'),
        )
        for candidate in variants:
            with (
                self.subTest(candidate=candidate),
                tempfile.TemporaryDirectory() as tmp,
            ):
                result = interaction.attempts(
                    ScriptedPredictor([candidate]),
                    self.prepared,
                    Path(tmp) / "run",
                    maximum=1,
                )
                self.assertFalse(result["success"])
                self.assertTrue(result["steps"][0]["executed"])
                self.assertEqual(
                    result["steps"][0]["execution_summary"]["subject_call_count"], 1
                )

    def test_preparation_is_pre_freeze_and_preserves_actual_observations(self):
        original = copy.deepcopy(self.original)
        real_tool = {"role": "tool", "content": '{"actual_status":"ready"}'}
        original["task"]["messages"].append(real_tool)
        before = copy.deepcopy(original)
        prepared = prepare_record(original)
        self.assertEqual(original, before)
        self.assertEqual(prepared["task"]["messages"][1:], [real_tool])
        self.assertNotIn("assert ...", prepared["task"]["input"])
        self.assertNotIn("verified_outcome", prepared)
        self.assertEqual(prepare_record(prepared), prepared)
        for name in ("source_id", "lineage_id", "split", "exposure", "final_answer"):
            self.assertEqual(prepared[name], original[name])
        similar = json.loads(original["task"]["messages"][1]["content"])
        similar["business_contract_covered"] = 0
        original["task"]["messages"][1]["content"] = data.canonical(similar).decode()
        self.assertEqual(
            prepare_record(original)["task"]["messages"][1:],
            original["task"]["messages"][1:],
        )
        original["task"]["messages"][1]["content"] = (
            '{"phase":"before_edit","real":true}'
        )
        self.assertEqual(
            prepare_record(original)["task"]["messages"][1:],
            original["task"]["messages"][1:],
        )
        original["task"]["messages"].insert(
            1, {"role": "assistant", "content": "earlier action"}
        )
        with self.assertRaisesRegex(ValueError, "precede"):
            prepare_record(original)

    def test_shadow_and_stale_bindings_do_not_start_verifier_children(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(
                execution.subprocess, "run", wraps=execution.subprocess.run
            ) as run:
                shadow = interaction.attempts(
                    ScriptedPredictor([self.correct]),
                    self.prepared,
                    Path(tmp) / "shadow",
                    execute=False,
                )
                stale = copy.deepcopy(self.prepared)
                stale["task"]["input"] += " changed"
                with self.assertRaises(ValueError):
                    interaction.attempts(
                        ScriptedPredictor([self.correct]), stale, Path(tmp) / "stale"
                    )
                run.assert_not_called()
        self.assertEqual(
            (
                shadow["success"],
                shadow["steps"][0]["verification"],
                shadow["steps"][0]["executed"],
            ),
            (None, None, False),
        )

    def test_reference_rebinding_and_collected_corrections_remain_separate(self):
        prepared = verify_reference(self.prepared)
        self.assertNotEqual(
            prepared["verified_outcome"], self.original["verified_outcome"]
        )
        bad = answer('    assert subject({"calls": 0}) == {"calls": 1}')
        predictor = ScriptedPredictor([self.correct, bad, self.correct])
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(
                interaction.coding_sft, "load_predictor", return_value=predictor
            ):
                cohorts, report = interaction.collect(
                    [prepared], {}, tmp, Path(tmp) / "collected"
                )
        self.assertTrue(predictor.closed)
        controlled = cohorts["controlled"][0]
        training, _ = training_messages(native_examples([controlled], "trajectory")[0])
        supervised = [m["content"] for m in training if m["train"]]
        self.assertEqual(supervised, [self.original["final_answer"]])
        self.assertEqual(
            [e["content"] for e in controlled["trajectory"] if e["actor"] == "student"],
            [bad, self.correct],
        )
        self.assertEqual(controlled["lineage_id"], self.original["lineage_id"])
        self.assertEqual(report["cohorts"]["controlled"]["completed_original_calls"], 2)
        self.assertIsNone(report["cohorts"]["shadow"]["successful_tasks"])
        self.assertEqual(
            report["cohorts"]["shadow"]["semantic_measurement"], "unmeasured"
        )

    def test_wrong_input_or_history_is_retained_but_never_executed(self):
        for field in ("input_sha256", "messages_sha256"):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as tmp:
                predictor = ScriptedPredictor([self.correct])
                generated = predictor.predict({"task": self.prepared["task"]})
                generated[field] = "0" * 64
                with (
                    patch.object(predictor, "predict", return_value=generated),
                    patch.object(
                        execution.subprocess, "run", wraps=execution.subprocess.run
                    ) as run,
                ):
                    with self.assertRaisesRegex(ValueError, "recorded request"):
                        interaction.attempts(
                            predictor, self.prepared, Path(tmp) / "run"
                        )
                    run.assert_not_called()
                self.assertEqual(
                    json.loads((Path(tmp) / "run" / "output-0.json").read_text()),
                    generated,
                )
                self.assertFalse((Path(tmp) / "run" / "RESULT.json").exists())

    def test_missing_call_counts_remain_unknown_with_a_measured_subtotal(self):
        prepared = verify_reference(self.prepared)
        predictor = ScriptedPredictor([self.correct, '{"edits":[', self.correct])
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(
                interaction.coding_sft, "load_predictor", return_value=predictor
            ):
                _, report = interaction.collect(
                    [prepared], {}, tmp, Path(tmp) / "collection"
                )
        fields = (
            "completed_original_calls",
            "completed_original_calls_measured_subtotal",
            "completed_original_calls_measured_attempts",
            "completed_original_calls_missing_attempts",
            "completed_original_call_count_complete",
            "successful_tasks",
            "semantic_measurement",
        )
        self.assertEqual(
            {
                name: [row[field] for field in fields]
                for name, row in report["cohorts"].items()
            },
            {
                "shadow": [None, None, 0, 1, False, None, "unmeasured"],
                "controlled": [None, 2, 1, 1, False, 1, "measured"],
            },
        )

    def test_prompt_panels_preserve_identity_and_retain_both_bindings(self):
        original = copy.deepcopy(self.original)
        original.pop("verified_outcome")
        original["task"]["input"] += "\nRetrieved context for this same task."
        original["task"]["messages"][0]["content"] = original["task"]["input"]
        shown = prepare_record(original)
        variants = []
        for field, value in (
            ("project_id", "different-project"),
            ("family_id", "different-family"),
            ("split", "selection"),
            ("available_at", shown["available_at"] + 1),
        ):
            changed = copy.deepcopy(shown)
            changed[field] = value
            variants.append(changed)
        for section, key, value in (
            ("source", "sha256", "0" * 64),
            ("authorization", "training_allowed", False),
        ):
            changed = copy.deepcopy(shown)
            changed[section][key] = value
            variants.append(changed)
        changed = copy.deepcopy(shown)
        changed["task"]["verifier"]["parameters"]["fixture_sha256"] = "0" * 64
        variants.append(changed)
        changed = copy.deepcopy(shown)
        changed.update(
            origin_kind="authorized_agent_run", exposure="previously_exposed"
        )
        variants.append(changed)
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(interaction.coding_sft, "load_predictor") as load:
                for changed in variants:
                    with self.assertRaisesRegex(ValueError, "identity"):
                        interaction.evaluate(
                            {},
                            tmp,
                            [self.prepared],
                            Path(tmp) / "rejected",
                            prompt_records=[changed],
                        )
                load.assert_not_called()
            manifest = {"engineering_prompt_test": True}
            predictor = ScriptedPredictor([self.correct])
            predictor.model_digest = data.digest(manifest)
            output = Path(tmp) / "evaluated"
            with patch.object(
                interaction.coding_sft, "load_predictor", return_value=predictor
            ):
                evaluation = interaction.evaluate(
                    manifest, tmp, [self.prepared], output, prompt_records=[shown]
                )
            self.assertEqual(
                json.loads((output / "ORIGINAL_PANEL.json").read_text()),
                [self.prepared],
            )
            self.assertEqual(
                json.loads((output / "SHOWN_PANEL.json").read_text()), [shown]
            )
        self.assertTrue(evaluation["rows"][0]["success"])
        self.assertEqual(
            evaluation["original_panel_digest"], data.digest([self.prepared])
        )
        self.assertEqual(evaluation["shown_panel_digest"], data.digest([shown]))
        self.assertNotEqual(
            evaluation["original_panel_digest"], evaluation["shown_panel_digest"]
        )
        self.assertEqual(
            predictor.requests[0]["task"],
            {
                "input": shown["task"]["input"],
                "messages": shown["task"]["messages"],
            },
        )

    def test_evaluation_keeps_actual_verifier_and_raw_policy_mismatch_output(self):
        manifest = {"engineering_fixture": True}
        predictor = ScriptedPredictor([self.correct])
        predictor.model_digest = data.digest(manifest)
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(
                interaction.coding_sft, "load_predictor", return_value=predictor
            ):
                evaluated = interaction.evaluate(
                    manifest, tmp, [self.prepared], Path(tmp) / "eval"
                )
            self.assertTrue(evaluated["rows"][0]["steps"][0]["verification"]["success"])
            self.assertEqual(
                evaluated["rows"][0]["task_digest"], data.digest(self.prepared)
            )
            wrong = ScriptedPredictor([self.correct])
            generated = wrong.predict({"task": {"input": "fixture"}})
            generated["loaded_model_digest"] = "b" * 64
            with patch.object(wrong, "predict", return_value=generated):
                with self.assertRaisesRegex(ValueError, "policy"):
                    interaction.attempts(wrong, self.prepared, Path(tmp) / "mismatch")
            self.assertEqual(
                json.loads((Path(tmp) / "mismatch" / "output-0.json").read_text()),
                generated,
            )


if __name__ == "__main__":
    unittest.main()
