#!/usr/bin/env python3
"""Synthetic boundary records only; no model, owner or credential is simulated."""

import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import hepta_smollm_answer_eos_research_v3 as research


class ResearchBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = "1" * 40
        self.required = dict(
            schema="hepta-public-initial-required-outcomes-v2",
            outcomes=dict.fromkeys(research.OUTCOMES, "success"),
            model_target_available=True,
            all_required_outcomes_passed=True,
            original_full_rust_gate_required=True,
            product_qualification=False,
            three_installed_upgrades_proven=False,
        )
        self.write("required-outcomes.json", self.required)
        scoped = ["just", "test", "--locked"]
        for package in research.PACKAGES:
            scoped += ["-p", package]
        native = [
            "just",
            "test",
            "--locked",
            "-p",
            "codex-hepta-infer-worker-host",
            "--lib",
            "--profile",
            "hepta-public-initial-v2",
            "-E",
        ]
        self.records = {}
        for name, count, command in (
            ("scoped-rust.json", 1, scoped + ["--no-capture"]),
            (
                "ordinary-native.json",
                2,
                native + [research.ORDINARY, "--run-ignored", "only", "--no-capture"],
            ),
            (
                "three-rounds-native.json",
                1,
                native
                + [research.THREE_ROUNDS, "--run-ignored", "only", "--no-capture"],
            ),
        ):
            log = self.root / (name + ".log")
            log.write_text("synthetic parser fixture " + name)
            state = dict(commit=self.source, dirty=False, tree="2" * 40)
            record = dict(
                schema_version=1,
                status="passed",
                command=command,
                command_exit_code=0,
                exit_code=0,
                returncode=0,
                observed_failed_tests=0,
                observed_passed_tests=count,
                minimum_tests=count,
                timed_out=False,
                output_limit_exceeded=False,
                source_sha=self.source,
                tested_sha=self.source,
                before=state,
                after=state,
                run_id="synthetic-run",
                run_attempt="1",
                job="cold-ordinary-three-rounds",
                lane="source-head",
                log_file=log.name,
                log_bytes=log.stat().st_size,
                log_sha256=research.digest(log),
            )
            self.records[name] = record
            self.write(name, record)
        current = dict(head_digest="head", record_count=1, file_digest="bytes")
        self.session = dict(
            schema="hepta-controlled-ordinary-public-initial-session-v2",
            withdrawal_refused=False,
            current=current,
            current_before=current,
            current_after=current,
            parent=dict(adapter="actual-parent"),
            home_root="same-owner-home",
            ordinary_context_reads=1,
            product_qualification_issued=False,
        )
        self.loop = dict(
            schema="hepta-controlled-public-initial-three-round-loop-v2",
            controlled_test_issuer=True,
            same_original_artifact_owner=True,
            completed_rounds=3,
            rounds=[{}, {}, {}],
            ordinary_sessions=[copy.deepcopy(self.session) for _ in range(4)],
            original_current=current,
            same_home_root="same-owner-home",
            beneficial_releases=0,
            installed_children=0,
            product_qualification_issued=False,
        )

    def write(self, name, record):
        (self.root / name).write_text(json.dumps(record))

    def test_complete_gates_bind_same_source_and_actual_log_bytes(self):
        result = research.validate_gates(self.root, self.source)
        self.assertEqual(result["source"], self.source)
        self.assertEqual(
            result["run"],
            ["synthetic-run", "1", "cold-ordinary-three-rounds", "source-head"],
        )
        self.assertEqual(
            result["records"], {p.name: research.digest(p) for p in self.root.iterdir()}
        )

    def test_success_label_cannot_hide_command_failure_or_timeout(self):
        name = "ordinary-native.json"
        for key, value in (
            ("command_exit_code", 100),
            ("observed_failed_tests", 1),
            ("timed_out", True),
            ("output_limit_exceeded", True),
        ):
            with self.subTest(key=key):
                self.write(name, dict(self.records[name], **{key: value}))
                with self.assertRaises(ValueError):
                    research.validate_gates(self.root, self.source)

    def test_missing_real_reopen_or_zero_executed_tests_is_rejected(self):
        name = "ordinary-native.json"
        for change in (
            dict(observed_passed_tests=0),
            dict(observed_passed_tests=1, minimum_tests=1),
            dict(command=["just", "test", "--list"]),
            dict(status="skipped"),
        ):
            with self.subTest(change=change):
                self.write(name, dict(self.records[name], **change))
                with self.assertRaises(ValueError):
                    research.validate_gates(self.root, self.source)

    def test_wrong_source_different_run_and_changed_log_are_rejected(self):
        name = "three-rounds-native.json"
        for change in (
            dict(source_sha="3" * 40),
            dict(run_id="another-run"),
            dict(after=dict(commit=self.source, dirty=True, tree="2" * 40)),
        ):
            with self.subTest(change=change):
                self.write(name, dict(self.records[name], **change))
                with self.assertRaises(ValueError):
                    research.validate_gates(self.root, self.source)
        self.write(name, self.records[name])
        (self.root / (name + ".log")).write_text("changed")
        with self.assertRaisesRegex(ValueError, "log pin"):
            research.validate_gates(self.root, self.source)

    def test_failed_original_gate_remains_failure_despite_completed_others(self):
        self.required["outcomes"]["PROPOSAL_ROUNDS_OUTCOME"] = "failure"
        self.write("required-outcomes.json", self.required)
        with self.assertRaisesRegex(ValueError, "original outcomes"):
            research.validate_gates(self.root, self.source)

    def test_complete_original_owner_loop_preserves_parent_and_current(self):
        before = copy.deepcopy((self.session, self.loop))
        research.validate_ordinary_loop(self.session, self.loop)
        self.assertEqual((self.session, self.loop), before)

    def test_withdrawal_parent_switch_or_incomplete_original_loop_is_rejected(self):
        for change in ("withdrawal", "parent", "current", "incomplete"):
            with self.subTest(change=change):
                loop = copy.deepcopy(self.loop)
                if change == "withdrawal":
                    loop["ordinary_sessions"][-1]["withdrawal_refused"] = True
                elif change == "parent":
                    loop["ordinary_sessions"][-1]["parent"]["adapter"] = (
                        "different-parent"
                    )
                elif change == "current":
                    loop["ordinary_sessions"][-1]["current_after"] = dict(
                        record_count=2
                    )
                else:
                    loop["completed_rounds"] = 2
                with self.assertRaises(ValueError):
                    research.validate_ordinary_loop(self.session, loop)

    def test_wrong_profile_or_proposal_ancestry_stops_before_runtime_access(self):
        values = dict(
            research_profile=research.PROFILE,
            round=1,
            proposal_parent=Path("/parent"),
            parent=Path("/parent"),
            proposal_parent_sha256="same",
            parent_sha256="same",
            proposal_training_lineage=[],
        )
        for change in (
            dict(research_profile="old-v2"),
            dict(round=2),
            dict(proposal_parent=Path("/other")),
            dict(proposal_training_lineage=[{}]),
        ):
            with (
                self.subTest(change=change),
                patch.object(research.subprocess, "check_output") as process,
            ):
                with self.assertRaises(ValueError):
                    research.validate_request(SimpleNamespace(**dict(values, **change)))
                process.assert_not_called()


if __name__ == "__main__":
    unittest.main()
