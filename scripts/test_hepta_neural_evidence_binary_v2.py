"""Finite adversarial evidence controls; fixtures grant no model qualification."""

import copy
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import hepta_neural_evidence_binary_v2 as target
import hepta_neural_evidence_v1 as original
import test_hepta_neural_evidence_v1 as fixtures


class BinaryTraceTests(unittest.TestCase):
    def setUp(self):
        self.rows = [
            dict(prompt=f"finite fixture {i}", expected_output=("yes", "no")[i % 2])
            for i in range(10)
        ]
        self.tokens = [[1, 100 + i, 2] for i in range(10)]
        self.context = dict(recipe="11" * 32, plan_sha256="22" * 32)
        hashes = [
            hashlib.sha256(original.canonical(row)).hexdigest() for row in self.rows
        ]
        self.raw = dict(
            input="33" * 32,
            source=dict(binary_answer_observed="44" * 32),
            training=dict(loss=[], tokens=300, supervised_tokens=100),
        )
        self.events = [
            dict(
                event="start",
                input=self.raw["input"],
                profile=target.PROFILE,
                recipe=self.context["recipe"],
                plan_sha256=self.context["plan_sha256"],
                source=self.raw["source"]["binary_answer_observed"],
                source_rows=hashes,
                pid=123,
                start_monotonic_ns=1,
            )
        ]
        self.consumed = dict(steps=[])
        loss = format(math.log(2), ".17g")
        clock = 1
        for update in range(10):
            for ordinal in range(10):
                clock += 1
                self.events.append(
                    dict(
                        event="microstep",
                        optimizer_step=update,
                        row_ordinal=ordinal,
                        source_row_sha256=hashes[ordinal],
                        input_ids=self.tokens[ordinal],
                        answer_token_ids=[10407, 4607],
                        target_index=ordinal % 2,
                        backward_completed=True,
                        answer_logits=["0", "0"],
                        loss=loss,
                        completed_monotonic_ns=clock,
                        completed_process_cpu_ns=clock,
                    )
                )
                self.consumed["steps"].append(
                    dict(
                        optimizer_step=update,
                        row_ordinal=ordinal,
                        source_row_sha256=hashes[ordinal],
                        input_ids=self.tokens[ordinal],
                        supervised_tokens=1,
                    )
                )
            clock += 1
            self.events.append(
                dict(
                    event="optimizer-step",
                    optimizer_step=update,
                    microsteps=10,
                    optimizer_completed=True,
                    gradient_l2_squared="1",
                    completed_monotonic_ns=clock,
                    completed_process_cpu_ns=clock,
                )
            )
            self.raw["training"]["loss"].append(
                format(math.fsum([float(loss)] * 10) / 10, ".17g")
            )
        self.events.append(
            dict(
                event="complete",
                optimizer_steps=10,
                microsteps=100,
                tokens=300,
                supervised_tokens=100,
                completed_monotonic_ns=clock + 1,
            )
        )

    def verify(self, events=None, consumed=None):
        return target.validate_trace(
            self.events if events is None else events,
            self.raw,
            self.consumed if consumed is None else consumed,
            self.rows,
            self.tokens,
            self.context,
        )

    def test_complete_trace_recounts_actual_exposures_without_claiming_more_examples(
        self,
    ):
        self.assertEqual(
            self.verify(),
            dict(
                optimizer_updates=10,
                gradient_microsteps=100,
                independent_source_rows=10,
                input_tokens=300,
                answer_supervised_tokens=100,
                eos_supervised_tokens=0,
            ),
        )

    def test_replayed_or_missing_microsteps_cannot_replace_complete_order(self):
        for mutation in (
            self.events[:-1],
            self.events[:1] + [self.events[2]] + self.events[2:],
            self.events[:1] + self.events[2:3] + self.events[1:2] + self.events[3:],
        ):
            with (
                self.subTest(length=len(mutation)),
                self.assertRaises((ValueError, IndexError, KeyError)),
            ):
                self.verify(mutation)

    def test_logits_targets_tokens_clocks_gradient_and_cost_relabelling_refuse(self):
        mutations = [
            (1, "answer_logits", ["nan", "0"]),
            (1, "answer_logits", ["-1e308", "1e308"]),
            (1, "loss", "0"),
            (1, "target_index", 1),
            (1, "input_ids", [1, 999, 2]),
            (1, "input_ids", [True, 100, 2]),
            (1, "answer_token_ids", [10407.0, 4607]),
            (1, "backward_completed", False),
            (1, "completed_monotonic_ns", 0),
            (1, "optimizer_step", False),
            (11, "gradient_l2_squared", "0"),
            (11, "optimizer_completed", False),
            (111, "microsteps", 10),
            (111, "supervised_tokens", 40),
        ]
        for index, key, value in mutations:
            events = copy.deepcopy(self.events)
            events[index][key] = value
            with self.subTest(index=index, key=key), self.assertRaises(ValueError):
                self.verify(events)
        consumed = copy.deepcopy(self.consumed)
        consumed["steps"][10]["source_row_sha256"] = "00" * 32
        with self.assertRaises(ValueError):
            self.verify(consumed=consumed)


class BinaryCommandTests(unittest.TestCase):
    setUp = fixtures.EvidenceReaderTests.setUp
    command_record = fixtures.EvidenceReaderTests.command_record

    def test_full_observer_policy_actual_budgets_and_optional_cleanup_timestamps(self):
        policy = dict(
            profile="linux-owned-exit-worker-pidfd-v4",
            maximum_drain_ns=100000000,
            observer_source_sha256="aa" * 32,
        )
        value = dict(
            exit_observation_profile=policy,
            terminal_reconciliation_profile="explicit-linux-owned-exit-worker-pidfd-v4",
            budget=dict(wall_seconds=600, rss_bytes=8 * 1024**3),
            child_spawned=True,
            owned_child_exit_observed=True,
            cleanup_method="wait4",
            sample_interval_ms=50,
            observed_wall_ns=1000,
            child_cpu_ns=1000,
            observer_cpu_ns=100,
            sampled_peak_rss_bytes=1024,
            waited_child_peak_rss_bytes=2048,
        )
        self.assertIsNone(
            target.observed_cost(value, policy, 600, 8 * 1024**3)[
                "exit_cleanup_elapsed_ns"
            ]
        )
        value["exit_cleanup_observation"] = dict(
            outcome="terminal-wait4",
            missing_sample_ns=10,
            completed_ns=20,
            retirement_closed_by="exact-owned-child-terminal-wait4",
        )
        self.assertEqual(
            target.observed_cost(value, policy, 600, 8 * 1024**3)[
                "exit_cleanup_elapsed_ns"
            ],
            10,
        )
        for key, replacement in (
            ("observed_wall_ns", 600000000001),
            ("waited_child_peak_rss_bytes", 8 * 1024**3 + 1),
            ("child_cpu_ns", True),
            (
                "exit_observation_profile",
                dict(policy, observer_source_sha256="bb" * 32),
            ),
            (
                "exit_cleanup_observation",
                dict(value["exit_cleanup_observation"], completed_ns=100000011),
            ),
        ):
            changed = copy.deepcopy(value)
            changed[key] = replacement
            with self.subTest(key=key), self.assertRaises(ValueError):
                target.observed_cost(changed, policy, 600, 8 * 1024**3)

    def test_isolated_actual_entrypoint_loads_only_explicit_sibling_path(self):
        completed = subprocess.run(
            [sys.executable, "-I", "-B", target.__file__, "--help"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn(b"source,assess,archive", completed.stdout)

    def test_source_collects_all_five_before_one_exclusive_write(self):
        def checkout(directory, expected):
            return dict(
                identity=dict(
                    commit=expected,
                    dirty=False,
                    tree=target.TRAINING_TREE
                    if directory.name == "chain-binary"
                    else "b" * 40,
                )
            )

        output = self.root / "snapshot.json"
        with (
            patch.object(original.ci, "git", return_value=str(self.root / "hepta")),
            patch.object(original, "collect_source", side_effect=checkout),
        ):
            self.assertEqual(target.source(output), 0)
            before = output.read_bytes()
            self.assertEqual(
                set(original.read(output)["repositories"]), target.REPOSITORIES
            )
            self.assertEqual(
                original.read(output)["schema"],
                "hepta-neural-complete-source-binary-v2",
            )
            with self.assertRaises(FileExistsError):
                target.source(output)
            self.assertEqual(output.read_bytes(), before)

    def test_original_and_binary_model_selectors_are_not_interchangeable(self):
        record = self.command_record()
        record["command"][9] = target.BinaryEvidence.positive_selector
        path = self.root / "positive-native.json"
        path.write_text(json.dumps(record))
        self.assertEqual(
            target.BinaryEvidence(self.root).command("positive-native", 1)["passed"], 2
        )
        with self.assertRaises(ValueError):
            original.Evidence(self.root).command("positive-native", 1)
        record["command"][9] = original.Evidence.positive_selector
        path.write_text(json.dumps(record))
        with self.assertRaises(ValueError):
            target.BinaryEvidence(self.root).command("positive-native", 1)

    def test_four_checkout_snapshots_cannot_qualify_new_training_source(self):
        snapshot = dict(
            schema="hepta-neural-complete-source-v1",
            valid=True,
            run=original.run_identity(),
            repositories={
                name: dict(identity={})
                for name in ("hepta", "chain", "chain-answer-eos", "chain-observed")
            },
        )
        for name in ("source-before.json", "source-after.json"):
            (self.root / name).write_text(json.dumps(snapshot))
        (self.root / "final-source-diff.patch").write_bytes(b"")
        with (
            patch.dict(os.environ, dict.fromkeys(original.REQUIRED, "success")),
            patch.object(target.BinaryEvidence, "command", return_value={}),
            patch.object(target.BinaryEvidence, "loop", return_value={}),
        ):
            self.assertEqual(target.assess(self.root), 1)
        report = original.read(self.root / "qualification-summary.json")
        self.assertFalse(report["passed"])
        self.assertFalse(report["checks"]["complete_source"]["passed"])


if __name__ == "__main__":
    unittest.main()
