"""Behavioral and adversarial tests using actual immutable input files and Git."""

import copy
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

import hepta_cell_research_gate as gate


class ResearchGateTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "source"
        self.artifacts = self.root / "artifacts"
        self.source.mkdir()
        self.artifacts.mkdir()
        self.git("init", "-q")
        self.git("config", "user.name", "Research gate fixture")
        self.git("config", "user.email", "fixture@example.invalid")
        (self.source / "runtime.py").write_text("VALUE = 1\n")
        self.git("add", "runtime.py")
        self.git("commit", "-qm", "immutable fixture source")
        self.configuration = {
            "schema": "hepta.cell-joint-config.v1",
            "source": {
                "repository": "example/research-gate",
                "commit": self.git("rev-parse", "HEAD"),
                "tree": self.git("rev-parse", "HEAD^{tree}"),
            },
            "artifacts": {
                role: self.bind(role, (role + "\n").encode())
                for role in (
                    "runtime",
                    "incumbent_model",
                    "candidate_model",
                    "trainer",
                    "data",
                    "evaluator",
                    "budget",
                    "adoption_rules",
                )
            },
            "required_workflows": [".github/workflows/research.yml"],
        }
        self.configuration["ci_evidence"] = self.bind(
            "ci.json",
            {
                "total_count": 1,
                "workflow_runs": [
                    {
                        "id": 9,
                        "head_sha": self.configuration["source"]["commit"],
                        "repository": {"full_name": "example/research-gate"},
                        "path": ".github/workflows/research.yml",
                        "status": "completed",
                        "conclusion": "success",
                        "run_attempt": 1,
                        "html_url": "https://example.invalid/actions/9",
                    }
                ],
            },
        )
        self.configuration_binding = self.bind("joint.json", self.configuration)
        self.protocol = {
            "schema": "hepta.cell-research-protocol.v1",
            "joint_configuration_sha256": self.configuration_binding["sha256"],
            "registration": self.bind("registration.txt", b"fixture registration\n"),
            "cost_unit": "fixture_units",
            "experiments": {
                name: {
                    "baselines": list(gate.BASELINES[name]),
                    "minimum_independent_fits": 2,
                    "minimum_net_gain": 0.1,
                    "retention_floor": -0.02,
                    "minimum_cost_fraction_saved": 0.1,
                    "maximum_total_cost": 1000,
                    "decision_rule": "all_fit_means",
                }
                for name in (
                    "MEM-1",
                    "CTRL-1",
                    "VERIFY-1",
                    "PERC-1",
                    "PRED-1",
                    "ACT-1",
                    "CREDIT-1",
                    "HCSN-1",
                    "STABILITY-1",
                    "ORG-1",
                    "IMPROVER-1",
                )
            },
        }
        self.manifest = {
            "schema": "hepta.cell-research-review.v1",
            "joint_configuration": self.configuration_binding,
            "protocol": self.bind("protocol.json", self.protocol),
            "foundation": None,
            "experiments": {},
        }

    def git(self, *arguments):
        return (
            subprocess.check_output(
                ["git", "-C", str(self.source), *arguments], stderr=subprocess.PIPE
            )
            .decode()
            .strip()
        )

    def bind(self, name, value):
        data = value if isinstance(value, bytes) else json.dumps(value).encode()
        (self.artifacts / name).write_bytes(data)
        return {
            "path": name,
            "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        }

    def assess(self):
        return gate.assess(self.manifest, self.source, self.artifacts)

    def experiment(self, name="MEM-1"):
        subject = {
            "experiment_id": name,
            "joint_configuration_sha256": self.configuration_binding["sha256"],
            "protocol_sha256": self.manifest["protocol"]["sha256"],
        }
        rows, fits = [], {}
        for fit in range(2):
            for arm in ("candidate", *self.protocol["experiments"][name]["baselines"]):
                binding = self.bind(f"{name}-{arm}-{fit}.bin", f"{arm}:{fit}".encode())
                fits[binding["sha256"]] = binding
                rows.append(
                    {
                        "attempt_id": f"{name}/{arm}/{fit}",
                        "arm": arm,
                        "fit_id": f"fit-{fit}",
                        "fit_sha256": binding["sha256"],
                        "case_id": "case-1",
                        "status": "completed",
                        "net_utility": 1 if arm == "candidate" else 0.7,
                        "retention": 0.5,
                        "costs": {
                            key: 1 if arm == "candidate" else 2
                            for key in gate.COST_CATEGORIES
                        },
                        "evidence_kind": "real",
                        "common_start_sha256": None,
                        "improver_sha256": None,
                    }
                )
        return {
            "subject": subject,
            "kind": "real",
            "registry": {
                "schema": "hepta.cell-attempt-inventory.v1",
                **subject,
                "attempt_ids": [row["attempt_id"] for row in rows],
            },
            "attempts": {
                "schema": "hepta.cell-research-attempts.v1",
                **subject,
                "rows": rows,
            },
            "design": {
                "schema": "hepta.cell-research-design.v1",
                **subject,
                "fit_artifacts": fits,
                "common_start_artifacts": {},
                "improver_lineage": [],
            },
        }

    def put(self, record):
        name = record["subject"]["experiment_id"]
        document = {
            "schema": "hepta.cell-research-experiment.v1",
            **record["subject"],
            "evidence_kind": record["kind"],
        }
        for field in ("registry", "attempts", "design"):
            document[field] = self.bind(f"{name}-{field}.json", record[field])
        self.manifest["experiments"][name] = self.bind(f"{name}.json", document)

    def screen(self, record):
        self.put(record)
        return self.assess()["experiments"][record["subject"]["experiment_id"]]

    def test_empty_evidence_is_not_vacuously_ready(self):
        original = copy.deepcopy(self.manifest)
        for omitted in (
            (),
            ("joint_configuration",),
            ("protocol",),
            ("joint_configuration", "protocol"),
        ):
            with self.subTest(omitted=omitted):
                self.manifest = copy.deepcopy(original)
                for field in omitted:
                    self.manifest[field] = None
                result = self.assess()
                for stage in result["stages"].values():
                    self.assertFalse(stage["mechanical_ready"])
                    self.assertFalse(stage["substantive_evidence_ready"])
                    self.assertTrue(stage["trusted_review_required"])

    def test_old_stage_schema_and_self_authenticated_fields_reject(self):
        for update in (
            {"schema": "hepta.cell-rsi.stage-status.v1"},
            {"stages": {"1": {"accepted": True}}},
            {"owner_authenticated": True},
            {"production_qualification": True},
        ):
            with self.subTest(update=update):
                original = copy.deepcopy(self.manifest)
                self.manifest.update(update)
                with self.assertRaises(ValueError):
                    self.assess()
                self.manifest = original

    def test_same_tree_new_commit_cannot_reuse_original_source_evidence(self):
        self.git("commit", "--allow-empty", "-qm", "different execution identity")
        with self.assertRaises(ValueError):
            self.assess()

    def test_missing_or_tampered_bound_bytes_reject(self):
        for role in ("runtime", "evaluator", "budget", "adoption_rules"):
            with self.subTest(role=role):
                path = self.artifacts / role
                original = path.read_bytes()
                path.write_bytes(b"x" * len(original))
                with self.assertRaises(ValueError):
                    self.assess()
                path.write_bytes(original)
        (self.artifacts / "registration.txt").unlink()
        with self.assertRaises((ValueError, OSError)):
            self.assess()

    def test_missing_nonfinite_boolean_and_invalid_thresholds_reject(self):
        original = copy.deepcopy(self.protocol)
        for field, value in (
            ("maximum_total_cost", None),
            ("maximum_total_cost", float("nan")),
            ("maximum_total_cost", True),
            ("maximum_total_cost", -1),
            ("minimum_independent_fits", 1),
            ("minimum_independent_fits", 2.5),
            ("minimum_net_gain", 0),
            ("retention_floor", 0.5),
            ("minimum_cost_fraction_saved", 1.1),
        ):
            with self.subTest(field=field, value=value):
                self.protocol = copy.deepcopy(original)
                if value is None:
                    del self.protocol["experiments"]["MEM-1"][field]
                else:
                    self.protocol["experiments"]["MEM-1"][field] = value
                self.manifest["protocol"] = self.bind("protocol.json", self.protocol)
                with self.assertRaises(ValueError):
                    self.assess()

    def test_descriptive_success_never_authenticates_science_or_owner(self):
        result = self.screen(self.experiment())
        self.assertTrue(result["mechanical_ready"])
        self.assertTrue(result["numerical_screen_ready"])
        self.assertTrue(result["descriptive_threshold_met"])
        self.assertFalse(result["substantive_evidence_ready"])
        self.assertFalse(result["independent_training_verified"])

    def test_registry_cannot_omit_duplicate_or_invent_an_attempt(self):
        original = self.experiment()
        for change in ("missing", "duplicate", "phantom", "wrong_protocol"):
            with self.subTest(change=change):
                record = copy.deepcopy(original)
                if change == "missing":
                    record["registry"]["attempt_ids"].pop()
                elif change == "duplicate":
                    record["attempts"]["rows"].append(
                        copy.deepcopy(record["attempts"]["rows"][0])
                    )
                elif change == "phantom":
                    record["registry"]["attempt_ids"].append("lost-started-attempt")
                else:
                    record["attempts"]["protocol_sha256"] = "a" * 64
                with self.assertRaises(ValueError):
                    self.screen(record)

    def test_unknown_or_missing_cost_is_not_zero(self):
        original = self.experiment()
        for field in ("missing", "unknown"):
            record = copy.deepcopy(original)
            costs = record["attempts"]["rows"][0]["costs"]
            if field == "missing":
                del costs["training"]
            else:
                costs["training"] = None
            self.assertFalse(self.screen(record)["numerical_screen_ready"])
        for value in (True, -1, float("inf")):
            record = copy.deepcopy(original)
            record["attempts"]["rows"][0]["costs"]["training"] = value
            with self.assertRaises(ValueError):
                self.screen(record)
        for value in (True, -1, "unknown-as-text"):
            with self.subTest(known_cost=value):
                record = copy.deepcopy(original)
                record["attempts"]["rows"][0]["costs"].update(
                    training=None, setup=value
                )
                with self.assertRaises(ValueError):
                    self.screen(record)
        self.protocol["experiments"]["MEM-1"]["maximum_total_cost"] = 1e100
        self.manifest["protocol"] = self.bind("protocol.json", self.protocol)
        record = self.experiment()
        for row in record["attempts"]["rows"]:
            row["costs"] = {key: 0 for key in gate.COST_CATEGORIES}
            row["costs"]["inference"] = 1e90 if row["arm"] == "candidate" else 1e-300
        with self.assertRaises(ValueError):
            self.screen(record)

    def test_campaign_budget_cannot_be_spent_again_for_each_arm(self):
        self.protocol["experiments"]["MEM-1"]["maximum_total_cost"] = 100
        self.manifest["protocol"] = self.bind("protocol.json", self.protocol)
        result = self.screen(self.experiment())
        totals = result["observed_cost_totals"]
        self.assertTrue(all(value < 100 for value in totals.values()))
        self.assertGreater(sum(totals.values()), 100)
        self.assertFalse(result["numerical_screen_ready"])

    def test_fit_aliases_and_extra_episodes_cannot_create_training_repeats(self):
        record = self.experiment()
        candidates = [
            row for row in record["attempts"]["rows"] if row["arm"] == "candidate"
        ]
        candidates[1]["fit_sha256"] = candidates[0]["fit_sha256"]
        result = self.screen(record)
        self.assertEqual(result["distinct_candidate_artifacts"], 1)
        self.assertFalse(result["numerical_screen_ready"])
        duplicate = copy.deepcopy(candidates[0])
        duplicate["attempt_id"] += "/retry"
        record["attempts"]["rows"].append(duplicate)
        record["registry"]["attempt_ids"].append(duplicate["attempt_id"])
        self.assertFalse(self.screen(record)["numerical_screen_ready"])

    def test_fixture_scope_and_pending_failed_attempts_cannot_disappear(self):
        original = self.experiment()
        for status in ("pending", "unknown", "censored", "failed", "cancelled"):
            with self.subTest(status=status):
                record = copy.deepcopy(original)
                record["attempts"]["rows"][0].update(
                    status=status, net_utility=None, retention=None
                )
                self.assertFalse(self.screen(record)["numerical_screen_ready"])
        original["attempts"]["rows"][0]["evidence_kind"] = "fixture"
        with self.assertRaises(ValueError):
            self.screen(original)
        original["kind"] = "fixture"
        for row in original["attempts"]["rows"]:
            row["evidence_kind"] = "fixture"
        self.assertFalse(self.screen(original)["numerical_screen_ready"])

    def test_one_bad_fit_cannot_hide_in_pooled_successful_episodes(self):
        record = self.experiment()
        candidate = next(
            row for row in record["attempts"]["rows"] if row["arm"] == "candidate"
        )
        candidate["net_utility"] = 0.69
        result = self.screen(record)
        self.assertTrue(result["comparisons"])
        self.assertFalse(result["descriptive_threshold_met"])

    def test_later_stage_evidence_cannot_skip_missing_predecessors(self):
        self.put(self.experiment("ORG-1"))
        result = self.assess()
        self.assertTrue(result["experiments"]["ORG-1"]["descriptive_threshold_met"])
        self.assertIn("S0", result["stages"]["S4"]["blocked_by_prior_stage"])
        self.assertFalse(result["stages"]["S4"]["substantive_evidence_ready"])

    def test_improver_comparison_requires_bound_common_start_and_lineage(self):
        record = self.experiment("IMPROVER-1")
        self.assertFalse(self.screen(record)["numerical_screen_ready"])
        start = self.bind("common-start.bin", b"same original state")
        previous = self.bind("previous-improver.bin", b"previous program")
        current = self.bind("current-improver.bin", b"current program")
        record["design"]["common_start_artifacts"] = {start["sha256"]: start}
        for name, program, parent in (
            ("previous", previous, None),
            ("current", current, previous),
        ):
            lineage = {
                "schema": "hepta.cell-improver-lineage.v1",
                "improver": program,
                "parent": parent,
            }
            record["design"]["improver_lineage"].append(
                self.bind(name + "-lineage.json", lineage)
            )
        for row in record["attempts"]["rows"]:
            row["common_start_sha256"] = start["sha256"]
            row["improver_sha256"] = (
                current if row["arm"] == "candidate" else previous
            )["sha256"]
        self.assertTrue(self.screen(record)["numerical_screen_ready"])
        changed_start = self.bind("changed-start.bin", b"different initial state")
        record["design"]["common_start_artifacts"][changed_start["sha256"]] = (
            changed_start
        )
        record["attempts"]["rows"][0]["common_start_sha256"] = changed_start["sha256"]
        self.assertFalse(self.screen(record)["numerical_screen_ready"])
        record["attempts"]["rows"][0]["common_start_sha256"] = start["sha256"]
        record["design"]["improver_lineage"][0] = self.bind(
            "previous-lineage.json",
            {
                "schema": "hepta.cell-improver-lineage.v1",
                "improver": previous,
                "parent": current,
            },
        )
        with self.assertRaises(ValueError):
            self.screen(record)


if __name__ == "__main__":
    unittest.main()
