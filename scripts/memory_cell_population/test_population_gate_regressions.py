"""Regressions for incomplete compression accounting and mixed-runtime cohorts."""

from copy import deepcopy
import unittest

from population_aggregate import aggregate, assess_trial
import test_population_reporting as reporting_fixtures


class PopulationGateRegressions(unittest.TestCase):
    def setUp(self):
        self.fixture = reporting_fixtures.PopulationAggregateTests(
            "test_positive_fission_keeps_general_and_net_compression_claims_closed"
        )

    def perfect_supported_inputs(self):
        arguments = self.fixture.inputs(single=0.875, split=1.0, metadata=0.875)
        for group in arguments[2]["metrics"]["selected"].values():
            group["accuracy"] = 1.0
        arguments[2]["routing"]["supported_retention_coverage"] = 1.0
        arguments[2]["routing"]["raw_ood_reject_rate"] = 1.0
        arguments[2]["parent_semantic_recall"] = 1.0
        return arguments

    def test_a_smaller_lower_bound_does_not_establish_net_system_savings(self):
        arguments = self.perfect_supported_inputs()
        arguments[5].update(
            retained_data_and_model_lower_bound_bytes=999,
            actual_experiment_directory_bytes_before_result=1000000,
            runtime_libraries_and_code_not_in_lower_bound=True,
            full_system_costs_and_comparable_baseline_accounted=False,
        )
        self.assertEqual(
            arguments[4]["smallest_complete_exact_representation"]["bytes"], 1000
        )
        report = assess_trial(*arguments)
        self.assertTrue(all(report["engineering_gates"].values()))
        self.assertFalse(report["research_gates"]["net_compression_advantage"])
        del arguments[5]["full_system_costs_and_comparable_baseline_accounted"]
        self.assertFalse(
            assess_trial(*arguments)["research_gates"]["net_compression_advantage"]
        )

    def test_complete_accounting_flag_cannot_replace_measured_comparable_costs(self):
        arguments = self.perfect_supported_inputs()
        arguments[5]["full_system_costs_and_comparable_baseline_accounted"] = True
        for actual, exact in (
            (None, None),
            (999, None),
            (None, 1000),
            (0, 1000),
            (-1, 1000),
            (True, 1000),
            (999, False),
            (999.0, 1000),
            (999, float("nan")),
        ):
            with self.subTest(actual=actual, exact=exact):
                arguments[5]["complete_system_storage_bytes"] = actual
                arguments[4]["complete_equivalent_system_bytes"] = exact
                with self.assertRaisesRegex(
                    ValueError, "complete equivalent system bytes"
                ):
                    assess_trial(*arguments)

    def test_complete_accounting_needs_strict_byte_gain_and_equal_supported_quality(
        self,
    ):
        arguments = self.perfect_supported_inputs()
        arguments[5].update(
            full_system_costs_and_comparable_baseline_accounted=True,
            complete_system_storage_bytes=999,
            retained_data_and_model_lower_bound_bytes=1,
        )
        arguments[4]["complete_equivalent_system_bytes"] = 1000
        self.assertTrue(
            assess_trial(*arguments)["research_gates"]["net_compression_advantage"]
        )
        arguments[5]["complete_system_storage_bytes"] = 1000
        self.assertFalse(
            assess_trial(*arguments)["research_gates"]["net_compression_advantage"]
        )
        arguments[5]["complete_system_storage_bytes"] = 999
        arguments[2]["metrics"]["selected"]["known"]["accuracy"] = 95 / 96
        self.assertFalse(
            assess_trial(*arguments)["research_gates"]["net_compression_advantage"]
        )

    def trials_with_runtime(self):
        trials = [self.fixture.trial(seed) for seed in (1907, 2719, 4051)]
        identity = {
            "source_manifest_sha256": "b" * 64,
            "git_head": "c" * 40,
            "python": "3.12.3",
            "platform": "registered-platform",
            "dependencies": {"torch": "2.5.1", "tokenizers": "0.22.0"},
        }
        for trial in trials:
            trial["source_identity"] = deepcopy(identity)
        return trials

    def test_same_source_hash_cannot_hide_dependency_or_python_runtime_drift(self):
        original = self.trials_with_runtime()
        for category, key, changed in (
            ("dependencies", "torch", "2.6.0"),
            ("dependencies", "tokenizers", "0.22.1"),
            (None, "python", "3.13.0"),
            (None, "git_head", "d" * 40),
        ):
            trials = deepcopy(original)
            identity = trials[1]["source_identity"]
            (identity[category] if category else identity)[key] = changed
            with (
                self.subTest(category=category, key=key),
                self.assertRaisesRegex(ValueError, "runtime identity"),
            ):
                aggregate(trials)

    def test_identical_runtime_is_accepted_independent_of_dict_and_seed_order(self):
        trials = self.trials_with_runtime()
        identity = trials[1]["source_identity"]
        identity["dependencies"] = dict(
            reversed(list(identity["dependencies"].items()))
        )
        trials[1]["source_identity"] = dict(reversed(list(identity.items())))
        result = aggregate(list(reversed(trials)))
        self.assertTrue(result["engineering_passed"])
        self.assertEqual(result["seeds"], [1907, 2719, 4051])


if __name__ == "__main__":
    unittest.main()
