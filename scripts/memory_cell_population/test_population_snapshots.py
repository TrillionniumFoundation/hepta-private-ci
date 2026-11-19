"""File consistency and typed reporting controls, without model execution."""

from contextlib import ExitStack
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import population_aggregate as reporting
import population_audit as audit
import population_audit_artifacts as artifacts


def consistent(function):
    # The original implementation has no audit read scope. Keeping its actual
    # reader here makes the same replacement controls expose the old behavior.
    return getattr(artifacts, "_consistent_reads", lambda value: value)(function)


ENGINEERING = (
    "matched_adapter_budget",
    "matched_candidate_updates",
    "router_overhead_within_one_percent",
    "parent_unchanged",
    "source_groups_preserved",
    "final_owner_admission",
    "selection_unchanged",
    "selection_preceded_final_reads",
    "exact_typed_baseline",
    "both_precommitted_codecs_measured",
)
RESEARCH = (
    "parent_source_quality",
    "split_preserves_parent_correct_semantic",
    "parent_final_quality",
    "split_preserves_parent_correct_final_semantic",
    "split_retention_nonnegative",
    "router_supported_coverage",
    "router_eligible_oracle_quality",
    "router_eligible_oracle_regret",
    "router_beats_expected_uniform_random",
    "router_beats_metadata_capability",
    "router_raw_ood_rejection",
    "selected_heterogeneous_retention",
    "selected_heterogeneous_transfer",
    "int8_storage_and_quality",
    "net_compression_advantage",
)


def trial_rows():
    return [
        {
            "seed": seed,
            "protocol_sha256": "a" * 64,
            "source_identity": {"source_manifest_sha256": "b" * 64},
            "training": {"costs": {"total_optimizer_updates": 2560}},
            "engineering_gates": dict.fromkeys(ENGINEERING, True),
            "research_gates": {
                key: key != "net_compression_advantage" for key in RESEARCH
            },
            "summary": {"split_retention_gain": 0.125},
        }
        for seed in (1907, 2719, 4051)
    ]


class SnapshotReadTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.path = self.root / "evidence.json"
        self.path.write_bytes(b'{"value":"first"}\n')

    def replace(self, raw=b'{"value":"other"}\n'):
        replacement = self.root / "replacement"
        replacement.write_bytes(raw)
        os.replace(replacement, self.path)

    def test_unchanged_bytes_and_nested_reads_are_accepted(self):
        @consistent
        def nested():
            return artifacts._read(self.path)

        @consistent
        def read():
            return artifacts._read(self.path), nested()

        self.assertEqual(read(), (self.path.read_bytes(), self.path.read_bytes()))

    def test_replacement_between_captured_reads_is_rejected(self):
        @consistent
        def read():
            first = artifacts._read(self.path)
            self.replace()
            return first, artifacts._read(self.path)

        with self.assertRaisesRegex(ValueError, "evidence changed during audit"):
            read()

    def test_nested_scope_cannot_reset_an_outer_file_binding(self):
        @consistent
        def nested():
            return artifacts._read(self.path)

        @consistent
        def read():
            artifacts._read(self.path)
            self.replace()
            return nested()

        with self.assertRaisesRegex(ValueError, "evidence changed during audit"):
            read()

    def test_separate_audits_accept_new_versions(self):
        read = consistent(lambda: artifacts._read(self.path))
        self.assertEqual(read(), self.path.read_bytes())
        self.replace()
        self.assertEqual(read(), self.path.read_bytes())

    def test_exception_does_not_leak_bindings_to_a_later_audit(self):
        @consistent
        def fail():
            artifacts._read(self.path)
            raise RuntimeError("intentional audit interruption")

        with self.assertRaisesRegex(RuntimeError, "intentional"):
            fail()
        self.replace()
        self.assertEqual(
            consistent(lambda: artifacts._read(self.path))(), self.path.read_bytes()
        )

    def test_replacement_after_path_check_cannot_change_consumed_file(self):
        real_stat = Path.stat
        events = []

        def swap_after_lstat(path, *args, **kwargs):
            result = real_stat(path, *args, **kwargs)
            if (
                path == self.path
                and kwargs.get("follow_symlinks") is False
                and not events
            ):
                self.replace()
                events.append("replaced")
            return result

        with patch.object(Path, "stat", swap_after_lstat):
            with self.assertRaisesRegex(ValueError, "evidence"):
                artifacts._read(self.path)
        self.assertEqual(events, ["replaced"])

    def test_existing_link_type_and_size_rejections_remain(self):
        target = self.root / "linked.json"
        target.symlink_to(self.path)
        with self.assertRaises(ValueError):
            artifacts._read(target)
        with self.assertRaises(ValueError):
            artifacts._read(self.root)
        large = self.root / "oversized"
        with large.open("wb") as stream:
            stream.truncate(64 * 1024 * 1024 + 1)
        with self.assertRaises(ValueError):
            artifacts._read(large)


class AuditResultBindingTests(unittest.TestCase):
    """Only entrypoint readback is exercised; raw science validators are stubs."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def single_fixture(self):
        result = {
            "seed": 1907,
            "training": {},
            "selection": {},
            "final": {},
            "codec": {},
            "baseline": {},
            "costs": {},
            "research_gates": {"retained_negative": False},
        }
        raw = json.dumps(result, sort_keys=True).encode()
        (self.root / "result.json").write_bytes(raw)
        (self.root / "raw-evidence-inventory.json").write_text("{}")
        return result, raw

    def single_validators(self, gates):
        stack = ExitStack()
        for name, value in (
            ("_inputs", {}),
            ("_training", ({}, {})),
            ("_selection", {}),
            ("_final", {"single": {}}),
            ("_codecs", None),
            ("_baselines", None),
            ("_costs", None),
        ):
            stack.enter_context(patch.object(audit, name, return_value=value))
        stack.enter_context(patch.object(audit, "_gates", side_effect=gates))
        return stack

    def test_unchanged_single_result_returns_digest_of_audited_bytes(self):
        result, raw = self.single_fixture()
        with self.single_validators(lambda _: None):
            report = audit.audit_trial(self.root)
        self.assertEqual(report["result_sha256"], hashlib.sha256(raw).hexdigest())
        self.assertEqual(report["research_gates"], result["research_gates"])

    def test_replaced_result_cannot_receive_the_old_validation(self):
        result, _ = self.single_fixture()

        def replace_after_validation(value):
            self.assertEqual(value, result)
            changed = deepcopy(result)
            changed["research_gates"]["retained_negative"] = True
            replacement = self.root / "replacement.json"
            replacement.write_text(json.dumps(changed))
            os.replace(replacement, self.root / "result.json")

        with self.single_validators(replace_after_validation):
            with self.assertRaisesRegex(ValueError, "evidence changed during audit"):
                audit.audit_trial(self.root)

    def test_cohort_rejects_result_replaced_after_individual_audit(self):
        results = trial_rows()
        for result in results:
            directory = self.root / f"seed-{result['seed']}"
            directory.mkdir()
            (directory / "result.json").write_text(json.dumps(result))
        (self.root / "aggregate.json").write_text(
            json.dumps(reporting.aggregate(results))
        )
        calls = []

        def individual(directory):
            raw = artifacts._read(directory / "result.json")
            result = json.loads(raw)
            calls.append(result["seed"])
            report = {
                "seed": result["seed"],
                "passed": True,
                "result_sha256": hashlib.sha256(raw).hexdigest(),
            }
            if len(calls) == 3:
                changed = dict(results[0], source_readback_marker="replaced")
                replacement = self.root / "replacement.json"
                replacement.write_text(json.dumps(changed))
                os.replace(replacement, self.root / "seed-1907" / "result.json")
            return report

        with patch.object(audit, "audit_trial", side_effect=individual):
            with self.assertRaisesRegex(ValueError, "evidence changed during audit"):
                audit.audit_population(self.root)
        self.assertEqual(calls, [1907, 2719, 4051])


class AggregateGateTypeTests(unittest.TestCase):
    def test_complete_boolean_core_and_extended_gates_are_accepted(self):
        for extended in (False, True):
            with self.subTest(extended=extended):
                rows = trial_rows()
                if extended:
                    for row in rows:
                        row["engineering_gates"].update(
                            source_identity_unchanged=True,
                            selection_bytes_unchanged_after_codecs=True,
                        )
                result = reporting.aggregate(rows)
                self.assertTrue(result["engineering_passed"])
                self.assertTrue(
                    result["claim_gates"]["matched_budget_fission_advantage"]
                )
                self.assertFalse(result["claim_gates"]["general_memory"])
                self.assertFalse(
                    result["claim_gates"]["net_memory_compression_advantage"]
                )

    def test_nonboolean_engineering_values_are_rejected(self):
        for value in (1, 0, "true", "false", None, [], {}, float("nan")):
            with self.subTest(value=value):
                rows = trial_rows()
                rows[0]["engineering_gates"]["final_owner_admission"] = value
                with self.assertRaisesRegex(ValueError, "boolean engineering"):
                    reporting.aggregate(rows)

    def test_empty_missing_and_unregistered_gates_are_rejected(self):
        for mode in ("empty", "missing", "unregistered"):
            with self.subTest(mode=mode):
                rows = trial_rows()
                gates = rows[0]["engineering_gates"]
                if mode == "empty":
                    gates.clear()
                elif mode == "missing":
                    del gates["final_owner_admission"]
                else:
                    gates["unregistered_gate"] = True
                with self.assertRaisesRegex(ValueError, "boolean engineering"):
                    reporting.aggregate(rows)

    def test_optional_engineering_scope_cannot_differ_between_seeds(self):
        rows = trial_rows()
        rows[0]["engineering_gates"]["source_identity_unchanged"] = True
        with self.assertRaisesRegex(ValueError, "identical engineering gate sets"):
            reporting.aggregate(rows)

    def test_explicit_negative_engineering_outcome_remains_negative(self):
        rows = trial_rows()
        rows[0]["engineering_gates"]["final_owner_admission"] = False
        result = reporting.aggregate(rows)
        self.assertFalse(result["engineering_passed"])
        self.assertFalse(any(result["claim_gates"].values()))
        self.assertIs(
            result["per_seed"][0]["engineering_gates"]["final_owner_admission"], False
        )


if __name__ == "__main__":
    unittest.main()
