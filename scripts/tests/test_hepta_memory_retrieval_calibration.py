"""Offline calibration fixtures are not product measurements or activation evidence."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from scripts import hepta_memory_retrieval_calibration as c


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


class CalibrationTests(unittest.TestCase):
    def setUp(self):
        self.head = "a" * 40
        self.tree = "b" * 40
        self.policy = {
            "schema": "hepta.memory-retrieval.calibration-policy.v1",
            "policy_id": "policy:unit-calibration",
            "baseline_system": "owner_rrf",
            "required_systems": list(c.STANDARD_SYSTEMS),
            "risk_strata": ["ordinary", "high-risk"],
            "minimum_groups_per_partition_stratum": 100,
            "vector_channel_enabled": False,
            "threshold_grid": {
                "minimum_total_score_q32": [0, c.Q32_ONE // 2],
                "maximum_ood_q32": [0, c.Q32_ONE],
                "minimum_distinct_channels": [1, 2],
            },
            "limits": {
                "false_accept_ppm_of_groups": 0,
                "harmful_accept_ppm_of_groups": 0,
                "false_abstain_ppm_of_positive_groups": 0,
            },
        }
        rows = []
        sample = 0
        for partition, time_base in (("calibration", 1), ("holdout", 1_000_000)):
            for risk_index, risk in enumerate(self.policy["risk_strata"]):
                for group_index in range(100):
                    positive = group_index % 2 == 0
                    group = f"{partition}:{risk}:{group_index:03d}"
                    query_digest = digest(f"query:{group}")
                    event_time = time_base + risk_index * 10_000 + group_index
                    for system in self.policy["required_systems"]:
                        rows.append({
                            "sample_id": f"sample:{sample:06d}",
                            "query_group": group,
                            "query_digest": query_digest,
                            "partition": partition,
                            "risk_stratum": risk,
                            "system": system,
                            "event_time_micros": event_time,
                            "target_should_recall": positive,
                            "selected": True,
                            "output_correct": positive,
                            "output_harmful": False,
                            "source_current": True,
                            "score_q32": c.Q32_ONE if positive else c.Q32_ONE // 4,
                            "ood_q32": 0 if positive else c.Q32_ONE,
                            "distinct_channels": 2 if positive else 1,
                            "contradiction": False,
                        })
                        sample += 1
        self.dataset = {
            "schema": "hepta.memory-retrieval.calibration-input.v1",
            "source_head": self.head,
            "source_tree": self.tree,
            "dataset_id": "dataset:unit-calibration",
            "policy_sha256": "",
            "annotation_protocol_digest": digest("annotation-protocol"),
            "vector_channel_enabled": False,
            "system_configuration_digests": {
                system: digest(f"config:{system}")
                for system in self.policy["required_systems"]
            },
            "rows": rows,
        }

    def calibrate(self):
        self.dataset["policy_sha256"] = hashlib.sha256(
            c.canonical(self.policy)
        ).hexdigest()
        return c.calibrate(
            self.dataset, self.policy, self.head, self.tree
        )

    def refused(self):
        with self.assertRaises(c.CalibrationError):
            self.calibrate()

    def rows(self, **matches):
        return [
            row
            for row in self.dataset["rows"]
            if all(row[key] == value for key, value in matches.items())
        ]

    def test_future_holdout_candidate_has_no_authority(self):
        receipt = self.calibrate()
        self.assertEqual(receipt["status"], "candidate_generated")
        self.assertTrue(receipt["future_holdout"])
        self.assertFalse(receipt["holdout_used_for_selection"])
        self.assertFalse(receipt["vector_channel_enabled"])
        self.assertFalse(receipt["productionPolicyApproved"])
        self.assertFalse(receipt["productExecutionProved"])
        self.assertFalse(receipt["independentAcceptance"])
        self.assertFalse(receipt["activation"])
        self.assertFalse(receipt["release"])
        for system in receipt["systems"]:
            self.assertEqual(
                system["selected_policy"],
                {
                    "minimum_total_score_q32": c.Q32_ONE // 2,
                    "maximum_ood_q32": 0,
                    "minimum_distinct_channels": 2,
                    "abstain_on_contradiction": True,
                    "vector_channel_enabled": False,
                },
            )
            self.assertEqual(
                system["holdout"]["overall"]["false_accept_count"], 0
            )
            self.assertEqual(
                system["holdout"]["overall"]["false_abstain_count"], 0
            )

    def test_holdout_outcomes_do_not_select_the_policy(self):
        before = {
            system["system"]: system["selected_policy"]
            for system in self.calibrate()["systems"]
        }
        for row in self.rows(partition="holdout"):
            if not row["target_should_recall"]:
                row["score_q32"] = c.Q32_ONE
                row["ood_q32"] = 0
                row["distinct_channels"] = 2
        after = self.calibrate()
        self.assertEqual(
            before,
            {
                system["system"]: system["selected_policy"]
                for system in after["systems"]
            },
        )
        self.assertGreater(
            next(
                system
                for system in after["systems"]
                if system["system"] == "hnmf_full"
            )["holdout"]["overall"]["false_accept_count"],
            0,
        )

    def test_standard_paired_ablations_are_required(self):
        self.policy["required_systems"].remove("hnmf_no_inhibition")
        self.dataset["system_configuration_digests"].pop("hnmf_no_inhibition")
        self.dataset["rows"] = [
            row
            for row in self.dataset["rows"]
            if row["system"] != "hnmf_no_inhibition"
        ]
        self.refused()

    def test_missing_one_paired_system_row_is_refused(self):
        self.dataset["rows"].pop()
        self.refused()

    def test_query_digest_cannot_cross_future_partition(self):
        calibration = self.rows(partition="calibration")[0]
        holdout = self.rows(partition="holdout")[0]
        holdout["query_digest"] = calibration["query_digest"]
        self.refused()

    def test_query_group_target_label_must_match_across_systems(self):
        row = self.rows(
            partition="calibration", system="hnmf_full"
        )[0]
        row["target_should_recall"] = not row["target_should_recall"]
        self.refused()

    def test_future_partition_must_be_strictly_later(self):
        self.rows(partition="holdout")[0]["event_time_micros"] = 1
        self.refused()

    def test_vector_is_refused_in_policy_and_dataset(self):
        self.policy["vector_channel_enabled"] = True
        self.refused()
        self.policy["vector_channel_enabled"] = False
        self.dataset["vector_channel_enabled"] = True
        self.refused()

    def test_policy_and_system_configuration_are_content_bound(self):
        self.dataset["policy_sha256"] = "0" * 64
        with self.assertRaises(c.CalibrationError):
            c.calibrate(self.dataset, self.policy, self.head, self.tree)
        self.dataset["system_configuration_digests"].pop("lexical")
        self.refused()

    def test_unselected_output_cannot_claim_correctness_or_harm(self):
        row = self.dataset["rows"][0]
        row["selected"] = False
        row["output_correct"] = True
        self.refused()
        row["output_correct"] = False
        row["output_harmful"] = True
        self.refused()

    def test_boolean_is_not_an_integer_or_boolean_substitute(self):
        self.dataset["rows"][0]["score_q32"] = True
        self.refused()
        self.dataset["rows"][0]["score_q32"] = c.Q32_ONE
        self.dataset["rows"][0]["source_current"] = 1
        self.refused()

    def test_stale_and_contradictory_outputs_are_gated(self):
        for row in self.rows(
            partition="holdout", system="hnmf_full", risk_stratum="ordinary"
        )[:2]:
            row["source_current"] = False
        for row in self.rows(
            partition="holdout", system="hnmf_full", risk_stratum="high-risk"
        )[:2]:
            row["contradiction"] = True
        receipt = self.calibrate()
        full = next(
            system
            for system in receipt["systems"]
            if system["system"] == "hnmf_full"
        )
        self.assertEqual(
            full["holdout"]["overall"]["stale_rejected_count"], 2
        )
        self.assertEqual(
            full["holdout"]["overall"]["contradiction_rejected_count"], 2
        )

    def test_no_feasible_candidate_is_explicit_failure(self):
        row = next(
            row
            for row in self.rows(
                partition="calibration", system="hnmf_full"
            )
            if not row["target_should_recall"]
        )
        row["score_q32"] = c.Q32_ONE
        row["ood_q32"] = 0
        row["distinct_channels"] = 2
        row["output_harmful"] = True
        receipt = self.calibrate()
        self.assertEqual(receipt["status"], "no_feasible_candidate")
        full = next(
            system
            for system in receipt["systems"]
            if system["system"] == "hnmf_full"
        )
        self.assertIsNone(full["selected_policy"])
        self.assertIsNone(full["holdout"])

    def test_limits_apply_to_each_risk_stratum_not_only_aggregate(self):
        self.policy["limits"]["false_accept_ppm_of_groups"] = 5_000
        row = next(
            row
            for row in self.rows(
                partition="calibration",
                system="owner_rrf",
                risk_stratum="high-risk",
            )
            if not row["target_should_recall"]
        )
        row["score_q32"] = c.Q32_ONE
        row["ood_q32"] = 0
        row["distinct_channels"] = 2
        receipt = self.calibrate()
        owner = next(
            system
            for system in receipt["systems"]
            if system["system"] == "owner_rrf"
        )
        self.assertIsNone(owner["selected_policy"])

    def test_grid_and_minimum_evidence_are_bounded(self):
        self.policy["minimum_groups_per_partition_stratum"] = 99
        self.refused()
        self.policy["minimum_groups_per_partition_stratum"] = 100
        self.policy["threshold_grid"]["minimum_total_score_q32"] = list(range(17))
        self.policy["threshold_grid"]["maximum_ood_q32"] = list(range(16))
        self.policy["threshold_grid"]["minimum_distinct_channels"] = list(range(1, 9))
        self.calibrate()
        self.policy["threshold_grid"]["maximum_ood_q32"] = list(range(32))
        self.refused()

    def test_ceiling_ppm_cannot_round_a_failure_down(self):
        self.assertEqual(c.ceiling_ppm(1, 101), 9901)

    def test_raw_json_rejects_duplicates_and_nonfinite_constants(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input.json"
            for value in ('{"x":1,"x":2}', '{"x":NaN}', '{"x":Infinity}'):
                path.write_text(value)
                with self.assertRaises(c.CalibrationError):
                    c.load(path)

    def test_content_addressed_retention_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            first = c.retain({"unit_fixture": True}, directory)
            second = c.retain({"unit_fixture": True}, directory)
            self.assertEqual(first, second)
            self.assertEqual(json.loads(first.read_bytes()), {"unit_fixture": True})
            first.write_text("corrupt")
            with self.assertRaises(c.CalibrationError):
                c.retain({"unit_fixture": True}, directory)


class SourceBindingTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.git("init", "-q")
        self.git("config", "user.name", "calibration unit test")
        self.git("config", "user.email", "calibration@example.invalid")
        (self.root / "source.txt").write_text("source candidate\n")
        self.git("add", "source.txt")
        self.git("commit", "-qm", "fixture")
        self.head = self.git("rev-parse", "HEAD")

    def git(self, *args):
        return subprocess.run(
            ["git", "-C", str(self.root), *args],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    def test_source_commit_tree_and_parents_are_observed(self):
        self.assertEqual(
            c.bind_source(self.root, self.head),
            {
                "commit": self.head,
                "tree": self.git("rev-parse", "HEAD^{tree}"),
                "parents": [],
            },
        )
        (self.root / "source.txt").write_text("second source\n")
        self.git("commit", "-qam", "second")
        second = self.git("rev-parse", "HEAD")
        self.assertEqual(c.bind_source(self.root, second)["parents"], [self.head])

    def test_wrong_dirty_or_non_repository_source_is_refused(self):
        with self.assertRaises(c.CalibrationError):
            c.bind_source(self.root, "a" * 40)
        (self.root / "dirty.txt").write_text("dirty\n")
        with self.assertRaises(c.CalibrationError):
            c.bind_source(self.root, self.head)
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(c.CalibrationError):
                c.bind_source(Path(directory), self.head)


if __name__ == "__main__":
    unittest.main()
