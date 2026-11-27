"""Synthetic contract checks; these fixtures are never execution evidence."""

import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from .controllers import ControlPlan
from .objective import canonical_sha
from .stopped_collect_contract import (
    BEHAVIOR_SHA,
    SCHEDULES,
    read_original,
    verify_completed,
    verify_selection,
)
from .test_recursive_contract import numerical_records


def selected_fixture():
    old = ["old-fit-" + str(i) for i in range(40)]
    tuning = ["old-tune-" + str(i) for i in range(8)]
    groups = sorted(
        ["new-" + str(i) for i in range(12)],
        key=lambda v: hashlib.sha256(v.encode()).digest(),
    )
    phases = {"calibration": groups[:6], "diagnostic": groups[6:]}
    catalog, selected = [], []
    for phase, identities in phases.items():
        for group in identities:
            for family in sorted(SCHEDULES):
                case = {
                    "id": group + "-" + family,
                    "source_id": group,
                    "role": "train",
                    "episode_group": group + "-receipt",
                    "task_family": family,
                    "packet": {},
                    "reference": {},
                }
                catalog.append(case)
                selected.append(
                    {"case": case, "exploration": SCHEDULES[family], "phase": phase}
                )
    selection = {
        "schema": "ndu.portfolio.fresh-selection.v1",
        "confirmation_access": False,
        "isolator_change_authorized": False,
        "maximum_episodes": 60,
        "collection_wall_limit_seconds": 600,
        "weights_sha256": BEHAVIOR_SHA,
        "original_fit_groups": old,
        "original_tuning_groups": tuning,
        "groups": phases,
    }
    return (
        selection,
        selected,
        catalog,
        {"groups": {"training": old, "tuning": tuning}},
        [],
    )


def episode_fixture():
    rows = numerical_records(ControlPlan())
    for index, row in enumerate(rows):
        row["behavior_weights_sha256"] = BEHAVIOR_SHA
        row["previous_record_sha256"] = (
            rows[index - 1]["record_sha256"] if index else None
        )
        row["record_sha256"] = canonical_sha(
            {k: v for k, v in row.items() if k != "record_sha256"}
        )
    request = {
        "profile": {"original_operation_id": rows[0]["origin_run_id"]},
        "case": {"id": rows[0]["episode_id"], "source_id": rows[0]["source_group"]},
        "config": {"rubric_sha256": rows[0]["rubric_sha256"]},
        "exploration": [row["action"] for row in rows],
    }
    result = {
        "schema": "ndu.real.episode-result.v1",
        "terminal_status": "Completed",
        "original_operation_id": rows[0]["origin_run_id"],
        "case_id": rows[0]["episode_id"],
        "source_group_id": rows[0]["source_group"],
        "split": "train",
        "memory_mode": "reset",
        "model_sha256": BEHAVIOR_SHA,
        "rubric_sha256": rows[0]["rubric_sha256"],
        "utility_profile_sha256": rows[0]["utility_profile_sha256"],
        "control_profile_sha256": rows[0]["behavior_control_profile_sha256"],
        "actions": request["exploration"],
        "confirmation_evaluated": False,
        "gross_score": rows[-1]["after_score"],
    }
    launch = {
        "schema": "ndu.real.actor-isolation.v1",
        "enforced_before_actor_exec": True,
        "exit_code": 0,
        "launcher_source_sha256": "a" * 64,
    }
    trajectory = {
        "steps": [
            {
                "action": {"action": row["action"]},
                "parameters_unchanged": True,
                "weights_sha256": BEHAVIOR_SHA,
                **{
                    key: row[key]
                    for key in (
                        "candidate_features",
                        "candidate_metadata",
                        "public_metadata",
                        "remaining_seconds",
                        "legal_actions",
                    )
                },
                "observed_action_seconds": row["duration_seconds"],
            }
            for row in rows
        ]
    }
    raw = ("\n".join(json.dumps(row) for row in rows) + "\n").encode()
    return request, result, launch, trajectory, raw, {"isolator_sha256": "a" * 64}


class StoppedCollectionContractTests(unittest.TestCase):
    def test_frozen_selection_has_twelve_disjoint_five_family_groups(self):
        groups = verify_selection(*selected_fixture())
        self.assertEqual(
            {key: len(value) for key, value in groups.items()},
            {"calibration": 6, "diagnostic": 6},
        )
        self.assertFalse(set(groups["calibration"]) & set(groups["diagnostic"]))

    def test_same_count_but_different_old_roster_is_rejected(self):
        inputs = copy.deepcopy(selected_fixture())
        inputs[3]["groups"]["training"] = [
            "different-original-source",
            *inputs[3]["groups"]["training"][1:],
        ]
        with self.assertRaisesRegex(ValueError, "roster"):
            verify_selection(*inputs)

    def test_confirmation_or_quarantined_source_cannot_be_selected(self):
        inputs = copy.deepcopy(selected_fixture())
        inputs[2][0]["role"] = "confirmation"
        with self.assertRaises(ValueError):
            verify_selection(*inputs)
        inputs = copy.deepcopy(selected_fixture())
        inputs[4].append(inputs[0]["groups"]["calibration"][0])
        with self.assertRaises(ValueError):
            verify_selection(*inputs)

    def test_postselection_action_or_phase_changes_are_rejected(self):
        for key, value in (
            ("exploration", ["WRITE_TEXT", "STOP"]),
            ("phase", "diagnostic"),
        ):
            inputs = copy.deepcopy(selected_fixture())
            inputs[1][0][key] = value
            with self.assertRaisesRegex(ValueError, "fixed selection"):
                verify_selection(*inputs)

    def test_original_v2_bytes_validate_without_duration_or_schema_conversion(self):
        fixture = episode_fixture()
        original = fixture[4]
        rows = verify_completed(*fixture)
        self.assertEqual(len(rows), 3)
        self.assertEqual([row["duration_seconds"] for row in rows], [0.1] * 3)
        self.assertEqual(fixture[4], original)

    def test_failed_budget_stopped_and_changed_actions_cannot_supply_training_rows(
        self,
    ):
        for status in ("Failed", "BudgetStop", "Unresolved"):
            fixture = list(episode_fixture())
            fixture[1]["terminal_status"] = status
            with self.assertRaises(ValueError):
                verify_completed(*fixture)
        fixture = list(episode_fixture())
        fixture[3]["steps"] = fixture[3]["steps"][1:]
        with self.assertRaisesRegex(ValueError, "sequence"):
            verify_completed(*fixture)

    def test_unenforced_launch_or_wrong_model_is_rejected(self):
        fixture = list(episode_fixture())
        fixture[2]["enforced_before_actor_exec"] = False
        with self.assertRaisesRegex(ValueError, "isolation"):
            verify_completed(*fixture)
        fixture = list(episode_fixture())
        fixture[3]["steps"][0]["weights_sha256"] = "b" * 64
        with self.assertRaisesRegex(ValueError, "model"):
            verify_completed(*fixture)

    def test_valid_rows_cannot_disagree_with_actual_actor_content_or_cost(self):
        for key, value in (
            ("observed_action_seconds", 0.9),
            ("public_metadata", [0.0] * 16),
        ):
            fixture = list(episode_fixture())
            fixture[3]["steps"][0][key] = value
            with self.assertRaisesRegex(ValueError, "original actor"):
                verify_completed(*fixture)

    def test_incomplete_or_legacy_rows_are_not_silently_upgraded(self):
        fixture = list(episode_fixture())
        fixture[4] = fixture[4].rstrip()
        with self.assertRaisesRegex(ValueError, "Incomplete"):
            verify_completed(*fixture)
        fixture = list(episode_fixture())
        fixture[4] = fixture[4].replace(
            b"training-transition.v2", b"training-transition.v1"
        )
        with self.assertRaises(ValueError):
            verify_completed(*fixture)

    def test_readback_checks_original_digest_without_rewriting(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "original.json"
            path.write_bytes(b'{"value":1}\n')
            raw, pin = read_original(path)
            path.write_bytes(b'{"value":2}\n')
            with self.assertRaisesRegex(ValueError, "pin"):
                read_original(path, pin["sha256"])
            self.assertNotEqual(path.read_bytes(), raw)
            self.assertEqual(path.read_bytes(), b'{"value":2}\n')


if __name__ == "__main__":
    unittest.main()
