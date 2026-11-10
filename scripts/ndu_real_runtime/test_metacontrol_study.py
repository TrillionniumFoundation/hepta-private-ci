"""Fixture-only study protocol checks; no real-task gain is established here."""

from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from . import metacontrol_study as study
from .critic_context import context_digest
from .metacontrol import ObservedContinuation, PublicControlState, _digest
from .test_metacontrol import CRITIC


def fixture_rows(prefix, groups=10):
    rows = []
    for group in range(groups):
        source = f"{prefix}/{group}"
        for feature in (-1.0, 1.0):
            context = f"context/{feature}"
            state = PublicControlState(
                (feature,),
                (0.5, 0.5),
                True,
                0.0,
                ("READ_ROI", "WRITE_TEXT", "STOP"),
                10.0,
            )
            stop_digest = _digest([source, context, "stop"])
            for action in ("READ_ROI", "WRITE_TEXT"):
                row = ObservedContinuation(
                    source,
                    f"{source}/{context}/{action}",
                    state,
                    action,
                    0.4,
                    0.4 if action == "READ_ROI" else 0.6 if feature > 0 else 0.2,
                    0.02,
                    False,
                    context=CRITIC,
                    evidence_context_sha256=context_digest(CRITIC),
                )
                rows.append(
                    {
                        "schema": "ndu.real.metacontrol-observation.v2",
                        "context_id": context,
                        "observation": {**asdict(row), "context": CRITIC.to_wire()},
                        "evidence": {
                            "kind": "fixture",
                            "critic_context_sha256": context_digest(CRITIC),
                            "utility_profile_sha256": CRITIC.utility_sha256,
                            "tariff_sha256": CRITIC.tariff_sha256,
                            "source_sha256": _digest(source),
                            "state_sha256": _digest(asdict(state)),
                            "stop_delivery_sha256": stop_digest,
                            "continuation_delivery_sha256": stop_digest
                            if action == "READ_ROI"
                            else _digest(row.decision_id),
                            "evaluator_sha256": "a" * 64,
                            "rubric_sha256": "b" * 64,
                            "cost_scope": "wall_time_only",
                            "continuation_steps": [action, "STOP"],
                            "incremental_cost_includes_policy_planning": False,
                            "action_budget_cost_bound": 1.0,
                            "finalization_reserve": 0.5,
                        },
                    }
                )
    return rows


class MetacontrolStudyTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def put(self, name, rows):
        raw = b"".join(
            (json.dumps(row, separators=(",", ":")) + "\n").encode() for row in rows
        )
        path = self.root / f"{name}.jsonl"
        path.write_bytes(raw)
        return path, hashlib.sha256(raw).hexdigest()

    def setup_inputs(self, *, future_rows=None):
        options = {
            "expected_source_sha256": _digest(study.source_manifest()),
            "context": CRITIC,
            "latency_weight": 0.01,
            "allow_fixtures": True,
            "output": self.root / "result",
        }
        for phase in ("train", "calibration", "future"):
            path, pin = self.put(
                phase,
                future_rows
                if phase == "future" and future_rows is not None
                else fixture_rows(phase),
            )
            options[phase], options[phase + "_sha256"] = path, pin
        return options

    def test_freeze_precedes_first_future_read_and_report_is_explicit_replay(self):
        options, original = self.setup_inputs(), study.read_input

        def observe(path, pin, **kwargs):
            if path == options["future"]:
                self.assertTrue((options["output"] / "freeze.json").is_file())
                self.assertTrue((options["output"] / "controller.json").is_file())
            return original(path, pin, **kwargs)

        with patch.object(study, "read_input", side_effect=observe):
            report = study.run_study(**options)
        self.assertFalse(report["policy_evaluation_performed"])
        self.assertFalse(report["native_prospective_execution"])
        self.assertTrue(report["counterfactual_replay_performed"])
        self.assertEqual(report["evidence_kind"], "fixture")
        self.assertEqual(report["future_source_groups"], 10)
        self.assertEqual(report["decision"], "HOLD_NO_GO")
        self.assertFalse(report["full_cost_observed"])
        self.assertEqual(report["summaries"]["conditional"]["observed_contexts"], 20)
        freeze = json.loads((options["output"] / "freeze.json").read_text())
        self.assertEqual(len(freeze["fixed_trials"]), 5)
        for row in report["outcomes"]:
            for result in row["policies"].values():
                self.assertAlmostEqual(
                    result["planning_cost"], result["planning_seconds"] * 0.01
                )

    def test_missing_action_keeps_denominator_and_never_imputes_return(self):
        future = [
            row
            for row in fixture_rows("future")
            if row["observation"]["action"] != "WRITE_TEXT"
        ]
        report = study.run_study(**self.setup_inputs(future_rows=future))
        self.assertEqual(report["incomplete_table_count"], 20)
        self.assertFalse(report["counterfactual_replay_performed"])
        for summary in report["summaries"].values():
            self.assertEqual(summary["contexts"], 20)
            self.assertEqual(summary["unknown_contexts"], 20)
            self.assertIsNone(summary["source_balanced_net_gain"])

    def test_fixture_opt_in_and_sha_source_pins_are_required(self):
        options = self.setup_inputs()
        with self.assertRaisesRegex(ValueError, "explicit fixture"):
            study.run_study(**{**options, "allow_fixtures": False})
        self.assertTrue((options["output"] / "failure.json").is_file())
        path, pin = options["train"], options["train_sha256"]
        path.write_bytes(path.read_bytes() + b" ")
        with self.assertRaisesRegex(ValueError, "SHA256"):
            study.read_input(path, pin, allow_fixtures=True, context=CRITIC)
        with self.assertRaisesRegex(ValueError, "source"):
            study.run_study(**{**options, "expected_source_sha256": "0" * 64})
        duplicate_planning = fixture_rows("double-cost", 2)
        duplicate_planning[0]["evidence"][
            "incremental_cost_includes_policy_planning"
        ] = True
        path, pin = self.put("double-cost", duplicate_planning)
        with self.assertRaisesRegex(ValueError, "cost scope"):
            study.read_input(path, pin, allow_fixtures=True, context=CRITIC)

    def test_source_alias_and_inconsistent_same_state_scores_reject(self):
        aliases = fixture_rows("train")
        for row in aliases:
            row["observation"]["source_group"] = (
                "alias/" + row["observation"]["source_group"]
            )
        options = self.setup_inputs(future_rows=aliases)
        with self.assertRaisesRegex(ValueError, "identities overlap"):
            study.run_study(**options)
        rows = fixture_rows("bad", groups=2)
        rows[1]["observation"]["stop_quality"] = 0.3
        path, pin = self.put("bad", rows)
        supplied, _ = study.read_input(path, pin, allow_fixtures=True, context=CRITIC)
        with self.assertRaisesRegex(ValueError, "conflicting identities"):
            study._table_groups(supplied)

    def test_read_useful_repeated_and_noise_are_information_only_before_stop(self):
        # All three are explicit fixture packets. No committed output changes
        # until a separately charged delivery suffix executes.
        for kind, packet in (
            ("useful", {"answer": "correct", "trusted": True}),
            ("repeated", {"answer": "old", "trusted": True}),
            ("noise", {"answer": "random", "trusted": False}),
        ):
            packet_path, delivered = (
                self.root / f"{kind}.packet",
                self.root / f"{kind}.delivery",
            )
            packet_path.write_bytes(json.dumps(packet).encode())
            delivered.write_bytes(b"old")
            expected_packet = hashlib.sha256(packet_path.read_bytes()).hexdigest()
            observed_raw = packet_path.read_bytes()  # Actual fixture READ.
            self.assertEqual(hashlib.sha256(observed_raw).hexdigest(), expected_packet)
            self.assertEqual(delivered.read_bytes(), b"old")
            # The same public fixed resolver executes only in the explicit
            # second primitive. Its offline fixture reference is never an input.
            observed = json.loads(observed_raw)
            if observed["trusted"]:
                delivered.write_bytes(observed["answer"].encode())
            self.assertEqual(delivered.read_bytes() == b"correct", kind == "useful")
            rows = [
                row
                for row in fixture_rows(kind, 2)
                if row["observation"]["action"] == "READ_ROI"
            ]
            rows[0]["evidence"]["continuation_steps"] = [
                "READ_ROI",
                "WRITE_TEXT",
                "STOP",
            ]
            path, pin = self.put(kind, rows)
            with self.assertRaisesRegex(ValueError, "suffix macro"):
                study.read_input(path, pin, allow_fixtures=True, context=CRITIC)
        rows = [
            row
            for row in fixture_rows("mislabelled", 2)
            if row["observation"]["action"] == "READ_ROI"
        ]
        rows[0]["observation"]["continuation_quality"] = 1.0
        path, pin = self.put("mislabelled", rows)
        with self.assertRaisesRegex(ValueError, "cannot change delivery"):
            study.read_input(path, pin, allow_fixtures=True, context=CRITIC)

    def test_supported_outcomes_do_not_fill_unsupported_policy_predictions(self):
        rows = fixture_rows("future")
        for row in rows:
            row["observation"]["state"]["features"] = (2.0,)
            row["evidence"]["state_sha256"] = _digest(row["observation"]["state"])
        report = study.run_study(**self.setup_inputs(future_rows=rows))
        self.assertEqual(report["incomplete_table_count"], 0)
        for method in ("point", "unconditional", "conditional"):
            self.assertEqual(report["summaries"][method]["unknown_contexts"], 20)
            self.assertIsNone(report["summaries"][method]["source_balanced_net_gain"])

    def test_study_cannot_mix_execution_cost_scopes_across_splits(self):
        rows = fixture_rows("future")
        for row in rows:
            row["observation"]["full_cost_observed"] = True
            row["evidence"]["cost_scope"] = "complete_declared"
        with self.assertRaisesRegex(ValueError, "cost-scope profiles"):
            study.run_study(**self.setup_inputs(future_rows=rows))


if __name__ == "__main__":
    unittest.main()
