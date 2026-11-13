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

    def task_bound_experiment(self):
        record = self.experiment()
        record["units"]["schema"] = "hepta.cell-research-units.v2"
        for index, case in enumerate(record["units"]["cases"]):
            case["task_artifact"] = self.bind(
                f"task-{index}.json", {"terminal_goal": f"fixture-goal-{index}"}
            )
        return record

    def test_task_bound_units_read_original_bytes_without_admitting_science(self):
        result = self.screen(self.task_bound_experiment())
        units = result["statistical_units"]
        self.assertEqual(
            {
                key: units[key]
                for key in (
                    "task_artifact_bytes_verified",
                    "distinct_task_artifacts",
                    "task_semantics_verified",
                    "natural_source_groups",
                    "sample_count_is_product",
                    "independence_verified",
                )
            },
            {
                "task_artifact_bytes_verified": True,
                "distinct_task_artifacts": 2,
                "task_semantics_verified": False,
                "natural_source_groups": 2,
                "sample_count_is_product": False,
                "independence_verified": False,
            },
        )
        self.assertTrue(result["descriptive_threshold_met"])
        reviewed = self.assess()
        self.assertFalse(reviewed["research_advancement"])
        self.assertFalse(reviewed["authority_granted"])
        self.assertFalse(result["new_milestone_eligible"])

    def test_identical_task_bytes_cannot_alias_sources_families_or_splits(self):
        for changed in ("source", "family", "split"):
            with self.subTest(changed=changed):
                record = self.task_bound_experiment()
                first, second = record["units"]["cases"]
                second["task_artifact"] = self.bind(
                    "task-alias.json",
                    (self.artifacts / first["task_artifact"]["path"]).read_bytes(),
                )
                if changed == "family":
                    second.update(
                        source_group_id=first["source_group_id"], task_family="image"
                    )
                elif changed == "split":
                    second["split"] = "confirmation"
                with self.assertRaisesRegex(
                    ValueError, "conflicting statistical units"
                ):
                    self.screen(record)

    def test_normalized_source_aliases_cannot_inflate_natural_group_count(self):
        for alternate in ("SOURCE-1", "ＳＯＵＲＣＥ-１"):
            with self.subTest(alternate=alternate):
                record = self.task_bound_experiment()
                record["units"]["cases"][1]["source_group_id"] = alternate
                with self.assertRaisesRegex(
                    ValueError, "aliased natural source-group identity"
                ):
                    self.screen(record)

    def test_repeated_exact_source_ids_share_one_natural_group(self):
        record = self.task_bound_experiment()
        record["units"]["cases"][1]["source_group_id"] = "source-1"
        result = self.screen(record)
        self.assertEqual(result["statistical_units"]["natural_source_groups"], 1)
        self.assertIn(
            "INSUFFICIENT_SOURCE_GROUPS", result["statistical_units"]["blockers"]
        )

    def test_same_unit_task_repetition_preserves_group_counts_and_weights(self):
        record = self.task_bound_experiment()
        before = self.screen(record)
        record["units"]["cases"].append(
            {**record["units"]["cases"][0], "case_id": "repeat-case"}
        )
        for row in copy.deepcopy(record["attempts"]["rows"]):
            if row["case_id"] != "case-1":
                continue
            original = row["attempt_id"]
            row.update(case_id="repeat-case", attempt_id=original + "/repeat")
            record["attempts"]["rows"].append(row)
            record["units"]["planned_attempts"].append(
                {key: row[key] for key in ("attempt_id", "arm", "fit_id", "case_id")}
            )
            record["units"]["cost_coverage"][row["attempt_id"]] = copy.deepcopy(
                record["units"]["cost_coverage"][original]
            )
        after = self.screen(record)
        self.assertEqual(after["comparisons"], before["comparisons"])
        for key in (
            "natural_source_groups",
            "task_families",
            "model_initializations",
            "distinct_task_artifacts",
        ):
            self.assertEqual(
                after["statistical_units"][key], before["statistical_units"][key]
            )
        self.assertGreater(after["attempt_denominator"], before["attempt_denominator"])

    def test_task_byte_replacement_and_wrong_hash_are_rejected(self):
        record = self.task_bound_experiment()
        binding = record["units"]["cases"][0]["task_artifact"]
        task_path = self.artifacts / binding["path"]
        original = task_path.read_bytes()
        task_path.write_bytes(original.replace(b"fixture-goal-0", b"fixture-goal-X"))
        self.assertEqual(task_path.stat().st_size, binding["bytes"])
        with self.assertRaisesRegex(ValueError, "artifact bytes or identity changed"):
            self.screen(record)
        task_path.write_bytes(original)
        binding["sha256"] = "f" * 64
        with self.assertRaisesRegex(ValueError, "artifact bytes or identity changed"):
            self.screen(record)

    def contrasting_task_experiment(self):
        self.protocol["experiments"]["MEM-1"]["maximum_total_cost"] = 10000
        self.manifest["protocol"] = self.bind("protocol.json", self.protocol)
        record = self.task_bound_experiment()
        for row in record["attempts"]["rows"]:
            row["net_utility"] = (
                1.7 if row["arm"] == "candidate" and row["case_id"] == "case-1" else 0.7
            )
            row["retention"] = 0.5
        self.repeat_task(record, "negative-task")
        record["units"]["cases"][-1]["task_artifact"] = self.bind(
            "negative-task.json", {"terminal_goal": "another-fixture-goal"}
        )
        for row in record["attempts"]["rows"]:
            if row["case_id"] == "negative-task" and row["arm"] == "candidate":
                row["net_utility"] = -0.3
        return record

    def repeat_task(self, record, case_id):
        record["units"]["cases"].append(
            {**record["units"]["cases"][0], "case_id": case_id}
        )
        for row in copy.deepcopy(record["attempts"]["rows"]):
            if row["case_id"] != "case-1":
                continue
            original = row["attempt_id"]
            row.update(case_id=case_id, attempt_id=original + "/" + case_id)
            record["attempts"]["rows"].append(row)
            record["units"]["planned_attempts"].append(
                {key: row[key] for key in ("attempt_id", "arm", "fit_id", "case_id")}
            )
            record["units"]["cost_coverage"][row["attempt_id"]] = copy.deepcopy(
                record["units"]["cost_coverage"][original]
            )

    def test_task_aliases_do_not_reweight_distinct_tasks_within_a_family(self):
        record = self.contrasting_task_experiment()
        before = self.screen(record)
        for index in range(8):
            self.repeat_task(record, f"positive-alias-{index}")
        after = self.screen(record)
        self.assertEqual(after["comparisons"], before["comparisons"])
        self.assertEqual(before["comparisons"]["rag"]["minimum_fit_mean_gain"], 0)
        self.assertFalse(after["descriptive_threshold_met"])
        self.assertEqual(
            (before["attempt_denominator"], after["attempt_denominator"]), (24, 88)
        )
        self.assertEqual(
            (before["observed_campaign_total"], after["observed_campaign_total"]),
            (672, 2464),
        )
        for key in (
            "natural_source_groups",
            "task_families",
            "model_initializations",
            "distinct_task_artifacts",
        ):
            self.assertEqual(
                before["statistical_units"][key], after["statistical_units"][key]
            )
        # Legacy v1 has no bound task identity: retain its original case weighting.
        record["units"]["schema"] = "hepta.cell-research-units.v1"
        for case in record["units"]["cases"]:
            del case["task_artifact"]
        legacy = self.screen(record)
        self.assertAlmostEqual(
            legacy["comparisons"]["rag"]["minimum_fit_mean_gain"], 0.4
        )
        self.assertFalse(legacy["new_milestone_eligible"])

    def test_repeated_task_failures_keep_outcomes_costs_and_unknown_coverage(self):
        record = self.contrasting_task_experiment()
        self.repeat_task(record, "failed-repeat")
        for row in record["attempts"]["rows"]:
            if row["case_id"] == "failed-repeat" and row["arm"] == "candidate":
                row.update(status="failed", net_utility=-0.3)
        result = self.screen(record)
        self.assertAlmostEqual(
            result["comparisons"]["rag"]["minimum_fit_mean_gain"], -0.25
        )
        self.assertEqual(result["attempt_counts"], {"completed": 30, "failed": 2})
        self.assertEqual(result["statistical_units"]["planned_attempts"], 32)
        self.assertEqual(result["observed_campaign_total"], 896)
        self.assertTrue(result["full_cost_records_complete"])
        self.assertFalse(result["descriptive_threshold_met"])
        self.assertFalse(self.assess()["authority_granted"])
        for row in record["attempts"]["rows"]:
            if row["status"] == "failed":
                row["costs"]["recovery"] = None
                record["units"]["cost_coverage"][row["attempt_id"]]["recovery"] = (
                    "unknown"
                )
        incomplete = self.screen(record)
        self.assertEqual(incomplete["attempt_counts"], result["attempt_counts"])
        self.assertEqual(incomplete["attempt_denominator"], 32)
        self.assertIsNone(incomplete["observed_campaign_total"])
        self.assertFalse(incomplete["full_cost_records_complete"])
        self.assertEqual(incomplete["comparisons"], {})
        self.assertIn("INCOMPLETE_COST_COVERAGE", incomplete["blockers"])

    def test_units_version_and_case_fields_are_strict_and_legacy_is_unchanged(self):
        legacy = self.screen(self.experiment())
        self.assertNotIn("task_artifact_bytes_verified", legacy["statistical_units"])
        self.assertNotIn("distinct_task_artifacts", legacy["statistical_units"])
        for change in ("missing-binding", "legacy-extra-binding", "unknown-schema"):
            with self.subTest(change=change):
                record = self.task_bound_experiment()
                if change == "missing-binding":
                    del record["units"]["cases"][0]["task_artifact"]
                elif change == "legacy-extra-binding":
                    record["units"]["schema"] = "hepta.cell-research-units.v1"
                else:
                    record["units"]["schema"] = "hepta.cell-research-units.v3"
                with self.assertRaises(ValueError):
                    self.screen(record)
        for key in ("experiment_id", "protocol_sha256", "joint_configuration_sha256"):
            record = self.task_bound_experiment()
            record["units"][key] = (
                "other-experiment" if key == "experiment_id" else "f" * 64
            )
            with self.subTest(binding=key), self.assertRaises(ValueError):
                self.screen(record)

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
            self.screen(self.experiment("CTRL-1"))["numerical_screen_ready"]
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
