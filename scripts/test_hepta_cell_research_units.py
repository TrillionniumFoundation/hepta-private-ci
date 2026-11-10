"""Exercise grouped review through actual bound files; all inputs are fixtures."""

import copy
import unittest

import hepta_cell_research_gate as gate
import test_hepta_cell_research_gate as fixtures


class ResearchUnitsTests(unittest.TestCase):
    git = fixtures.ResearchGateTests.git
    bind = fixtures.ResearchGateTests.bind
    assess = fixtures.ResearchGateTests.assess

    def setUp(self):
        fixtures.ResearchGateTests.setUp(self)
        self.protocol["schema"] = "hepta.cell-research-protocol.v2"
        for name, spec in self.protocol["experiments"].items():
            spec["sampling"] = {
                "minimum_source_groups": 2,
                "minimum_task_families": 1,
                "minimum_model_initializations": 2,
                "threshold_basis": self.bind(name + "-basis.txt", b"unit-test fixture"),
            }
        self.manifest["protocol"] = self.bind("protocol.json", self.protocol)

    def experiment(self, name="MEM-1"):
        record = fixtures.ResearchGateTests.experiment(self, name)
        for row in copy.deepcopy(record["attempts"]["rows"]):
            row.update(case_id="case-2", attempt_id=row["attempt_id"] + "/case-2")
            record["attempts"]["rows"].append(row)
        fits, initializations = [], {}
        for index in range(2):
            artifact = self.bind(
                f"initialization-{index}.bin", f"init:{index}".encode()
            )
            initializations[artifact["sha256"]] = artifact
            fits.append(
                {
                    "fit_id": f"fit-{index}",
                    "initialization_sha256": artifact["sha256"],
                    "training_operation_id": f"training-{index}",
                }
            )
        record["units"] = {
            "schema": "hepta.cell-research-units.v1",
            **record["subject"],
            "cases": [
                {
                    "case_id": f"case-{i}",
                    "source_group_id": f"source-{i}",
                    "task_family": "text",
                    "split": "development",
                }
                for i in (1, 2)
            ],
            "initializations": initializations,
            "fits": fits,
            "planned_attempts": [],
            "cost_coverage": {},
        }
        for row in record["attempts"]["rows"]:
            record["units"]["planned_attempts"].append(
                {key: row[key] for key in ("attempt_id", "arm", "fit_id", "case_id")}
            )
            record["units"]["cost_coverage"][row["attempt_id"]] = {
                key: "measured" for key in gate.COST_CATEGORIES
            }
        return record

    def screen(self, record):
        name = record["subject"]["experiment_id"]
        record["registry"]["attempt_ids"] = [
            row["attempt_id"] for row in record["attempts"]["rows"]
        ]
        document = {
            "schema": "hepta.cell-research-experiment.v2",
            **record["subject"],
            "evidence_kind": record["kind"],
        }
        for key in ("registry", "attempts", "design", "units"):
            document[key] = self.bind(f"{name}-{key}.json", record[key])
        self.manifest["experiments"][name] = self.bind(name + ".json", document)
        return self.assess()["experiments"][name]

    def test_repeat_cases_do_not_reweight_sources_or_multiply_units(self):
        record = self.experiment()
        for row in record["attempts"]["rows"]:
            if row["case_id"] == "case-2" and row["arm"] == "candidate":
                row["net_utility"] = 0.7
        before = self.screen(record)
        record["units"]["cases"].append(
            {
                **record["units"]["cases"][0],
                "case_id": "case-repeat",
            }
        )
        for row in copy.deepcopy(record["attempts"]["rows"]):
            if row["case_id"] != "case-1":
                continue
            original_id = row["attempt_id"]
            row.update(case_id="case-repeat", attempt_id=original_id + "/repeat")
            record["attempts"]["rows"].append(row)
            record["units"]["planned_attempts"].append(
                {key: row[key] for key in ("attempt_id", "arm", "fit_id", "case_id")}
            )
            record["units"]["cost_coverage"][row["attempt_id"]] = copy.deepcopy(
                record["units"]["cost_coverage"][original_id]
            )
        after = self.screen(record)
        for result in (before, after):
            units = result["statistical_units"]
            self.assertEqual(
                (
                    units["natural_source_groups"],
                    units["task_families"],
                    units["model_initializations"],
                ),
                (2, 1, 2),
            )
            self.assertAlmostEqual(
                result["comparisons"]["rag"]["minimum_fit_mean_gain"], 0.15
            )
            self.assertTrue(result["full_cost_records_complete"])
            self.assertFalse(result["new_milestone_eligible"])
        self.assertGreater(after["attempt_denominator"], before["attempt_denominator"])
        record["units"]["cases"].append(
            {
                **record["units"]["cases"][0],
                "case_id": "case-image",
                "task_family": "image",
            }
        )
        for row in copy.deepcopy(record["attempts"]["rows"]):
            if row["case_id"] != "case-1":
                continue
            original_id = row["attempt_id"]
            row.update(
                case_id="case-image", attempt_id=original_id + "/image", net_utility=0.7
            )
            record["attempts"]["rows"].append(row)
            record["units"]["planned_attempts"].append(
                {key: row[key] for key in ("attempt_id", "arm", "fit_id", "case_id")}
            )
            record["units"]["cost_coverage"][row["attempt_id"]] = copy.deepcopy(
                record["units"]["cost_coverage"][original_id]
            )
        result = self.screen(record)
        self.assertAlmostEqual(
            result["comparisons"]["rag"]["minimum_fit_mean_gain"], 0.075
        )

    def test_initialization_and_operation_aliases_do_not_inflate_counts(self):
        for key, count, blocker in (
            (
                "initialization_sha256",
                "model_initializations",
                "INSUFFICIENT_MODEL_INITIALIZATIONS",
            ),
            (
                "training_operation_id",
                "training_operations",
                "ALIASED_TRAINING_OPERATIONS",
            ),
        ):
            with self.subTest(key=key):
                record = self.experiment()
                fits = record["units"]["fits"]
                fits[1][key] = fits[0][key]
                result = self.screen(record)
                self.assertEqual(result["statistical_units"][count], 1)
                self.assertIn(blocker, result["blockers"])
                self.assertFalse(result["numerical_screen_ready"])

    def test_missing_rejected_interrupted_and_unknown_attempts_remain(self):
        record = self.experiment()
        record["attempts"]["rows"].pop()
        result = self.screen(record)
        self.assertEqual(result["statistical_units"]["planned_attempts"], 16)
        self.assertEqual(
            result["statistical_units"]["attempt_counts"]["not_observed"], 1
        )
        self.assertFalse(result["full_cost_records_complete"])
        self.assertEqual(result["comparisons"], {})
        self.assertFalse(result["numerical_screen_ready"])
        for status in ("rejected", "interrupted", "unknown", "failed", "cancelled"):
            record = self.experiment()
            record["attempts"]["rows"][0].update(status=status, net_utility=None)
            result = self.screen(record)
            self.assertEqual(result["statistical_units"]["attempt_counts"][status], 1)
            self.assertEqual(result["statistical_units"]["planned_attempts"], 16)
            self.assertFalse(result["numerical_screen_ready"])

    def test_numeric_cost_does_not_clear_unknown_coverage_or_missing_cost(self):
        record = self.experiment()
        row = record["attempts"]["rows"][0]
        scope = record["units"]["cost_coverage"][row["attempt_id"]]
        scope["recovery"] = "unknown"
        self.assertFalse(self.screen(record)["full_cost_records_complete"])
        scope["recovery"] = "not_applicable"
        for value in (None, 1):
            row["costs"]["recovery"] = value
            with self.assertRaisesRegex(ValueError, "explicitly zero"):
                self.screen(record)
        del row["costs"]["recovery"]
        with self.assertRaisesRegex(ValueError, "explicitly zero"):
            self.screen(record)
        row["costs"]["recovery"] = 0
        self.assertTrue(self.screen(record)["full_cost_records_complete"])

    def test_source_split_and_observed_unit_drift_refuse(self):
        record = self.experiment()
        cases = record["units"]["cases"]
        cases[1].update(
            source_group_id=cases[0]["source_group_id"], split="confirmation"
        )
        with self.assertRaisesRegex(ValueError, "crosses registered splits"):
            self.screen(record)
        record = self.experiment()
        record["units"]["cases"][1]["split"] = "retention_validation"
        result = self.screen(record)
        self.assertIn("MIXED_EVALUATION_SPLITS", result["blockers"])
        self.assertEqual(result["comparisons"], {})
        record = self.experiment()
        record["attempts"]["rows"][0]["case_id"] = "case-2"
        with self.assertRaisesRegex(ValueError, "changed its statistical unit"):
            self.screen(record)

    def test_experiment_thresholds_are_distinct_and_version_bound(self):
        self.protocol["experiments"]["MEM-1"]["minimum_net_gain"] = 0.4
        self.manifest["protocol"] = self.bind("protocol.json", self.protocol)
        self.assertFalse(
            self.screen(self.experiment("MEM-1"))["numerical_screen_ready"]
        )
        self.assertTrue(
            self.screen(self.experiment("CTRL-1"))["descriptive_threshold_met"]
        )
        record = self.experiment()
        fixtures.ResearchGateTests.put(self, record)
        with self.assertRaisesRegex(ValueError, "protocol versions differ"):
            self.assess()

    def test_no_observations_retains_every_planned_opportunity_as_incomplete(self):
        record = self.experiment()
        planned = sorted(
            row["attempt_id"] for row in record["units"]["planned_attempts"]
        )
        record["attempts"]["rows"] = []
        record["design"]["fit_artifacts"] = {}
        result = self.screen(record)
        self.assertEqual(result["attempt_denominator"], 0)
        self.assertEqual(result["attempt_counts"], {})
        self.assertEqual(result["distinct_candidate_artifacts"], 0)
        units = result["statistical_units"]
        self.assertEqual(units["planned_attempts"], 16)
        self.assertEqual(units["observed_attempts"], 0)
        self.assertEqual(units["attempt_counts"], {"not_observed": 16})
        self.assertEqual(units["unobserved_attempt_ids"], planned)
        self.assertIn("MISSING_PLANNED_ATTEMPTS", result["blockers"])
        self.assertIn("INCOMPLETE_COST_COVERAGE", result["blockers"])
        self.assertFalse(result["full_cost_records_complete"])
        self.assertFalse(result["numerical_screen_ready"])
        self.assertFalse(result["new_milestone_eligible"])
        self.assertEqual(result["comparisons"], {})
        record["units"]["planned_attempts"] = []
        with self.assertRaisesRegex(ValueError, "statistical-unit inventory is empty"):
            self.screen(record)

    def test_pre_fit_failures_keep_status_and_cost_without_fabricated_artifacts(self):
        for status in sorted(gate.STATUSES - {"completed"}):
            with self.subTest(status=status):
                record = self.experiment()
                for row in record["attempts"]["rows"]:
                    row.update(
                        status=status,
                        fit_sha256=None,
                        net_utility=None,
                        retention=None,
                    )
                record["design"]["fit_artifacts"] = {}
                result = self.screen(record)
                self.assertEqual(result["attempt_denominator"], 16)
                self.assertEqual(result["attempt_counts"], {status: 16})
                self.assertEqual(result["distinct_candidate_artifacts"], 0)
                self.assertEqual(result["statistical_units"]["observed_attempts"], 16)
                self.assertEqual(result["observed_campaign_total"], 448)
                self.assertTrue(result["full_cost_records_complete"])
                self.assertFalse(result["numerical_screen_ready"])
                self.assertIn("UNAVAILABLE_FIT_ARTIFACT", result["blockers"])
                self.assertIn("INSUFFICIENT_DISTINCT_FIT_ARTIFACTS", result["blockers"])
                self.assertEqual(result["comparisons"], {})

    def test_missing_fit_does_not_hide_cost_errors_or_count_as_another_fit(self):
        record = self.experiment()
        row = record["attempts"]["rows"][0]
        row.update(status="failed", fit_sha256=None, net_utility=None)
        row["costs"]["failures"] = -1
        with self.assertRaisesRegex(ValueError, "nonnegative"):
            self.screen(record)
        row["costs"]["failures"] = 1
        record["units"]["cost_coverage"][row["attempt_id"]]["recovery"] = "unknown"
        for rows in (
            record["attempts"]["rows"],
            list(reversed(record["attempts"]["rows"])),
        ):
            with self.subTest(failed_first=rows[0]["status"] == "failed"):
                record["attempts"]["rows"] = rows
                result = self.screen(record)
                self.assertEqual(
                    result["attempt_counts"], {"failed": 1, "completed": 15}
                )
                self.assertEqual(result["distinct_candidate_artifacts"], 2)
                self.assertIn("UNAVAILABLE_FIT_ARTIFACT", result["blockers"])
                self.assertIn("INCOMPLETE_COST_COVERAGE", result["blockers"])
                self.assertFalse(result["full_cost_records_complete"])
                self.assertEqual(result["comparisons"], {})

    def test_completed_attempt_still_requires_the_actual_fit_artifact(self):
        record = self.experiment()
        record["attempts"]["rows"][0]["fit_sha256"] = None
        with self.assertRaisesRegex(ValueError, "completed attempt requires"):
            self.screen(record)

    def test_v1_still_refuses_empty_rows_and_missing_fit_artifacts(self):
        self.protocol["schema"] = "hepta.cell-research-protocol.v1"
        for spec in self.protocol["experiments"].values():
            del spec["sampling"]
        self.manifest["protocol"] = self.bind("protocol.json", self.protocol)
        record = fixtures.ResearchGateTests.experiment(self)
        record["registry"]["attempt_ids"] = []
        record["attempts"]["rows"] = []
        fixtures.ResearchGateTests.put(self, record)
        with self.assertRaisesRegex(ValueError, "identity list is empty"):
            self.assess()
        record = fixtures.ResearchGateTests.experiment(self)
        record["attempts"]["rows"][0].update(status="failed", fit_sha256=None)
        fixtures.ResearchGateTests.put(self, record)
        with self.assertRaisesRegex(ValueError, "complete lowercase SHA256"):
            self.assess()


if __name__ == "__main__":
    unittest.main()
