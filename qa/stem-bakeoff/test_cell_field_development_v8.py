"""Full-reference census and disk recovery retain deliberate/actual failures."""

import copy
import hashlib
from itertools import product
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from cell_field_development_artifacts_v8 import materialize_checkpoints, read_compressed, save_result
from cell_field_development_audit_v8 import per_source_nll
from cell_field_development_selection_v8 import (CANDIDATE, GROUPS, POLICIES, SEEDS,
    select_configuration, summarize_configuration)
from cell_field_policy_v8 import execute_policy
from cell_field_safety_portfolio_v8 import repair_sequence
from cell_learning_models import canonical
from test_cell_field_policy_v7 import fixture


def complete_family(gain=.01):
    rows = [{"version": v, "task": t, "head": h, "seed": s, "policy": p,
        "status": "completed", "completed_steps": 32, "error": None, "audit_passed": True,
        "cpu_ns": 50 if p == CANDIDATE else 100, "selection_sources_sha256": v+t,
        "future_losses": np.full(512, .5-gain if p == CANDIDATE else .5),
        "old_differences": np.full(512, -.03 if p == CANDIDATE else -.01)}
        for (v, t, h), s, p in product(GROUPS, SEEDS, POLICIES)]
    parity = [{"fit_id": f"{v}-{t}-seed{s}-{h}", "configuration_index": 0, "passed": True}
        for (v, t, h), s in product(GROUPS, SEEDS)]
    return rows, parity


class DevelopmentV8Tests(unittest.TestCase):
    def test_missing_full_or_partial_trajectory_never_enters_equal32_comparisons(self):
        rows, parity = complete_family()
        self.assertTrue(summarize_configuration(0, rows, parity)["plausible"])
        for mutation in ("missing_full", "stopped", "parity_missing", "parity_failed", "parity_wrong_fit", "parity_wrong_config"):
            changed, checks = copy.deepcopy(rows), copy.deepcopy(parity)
            if mutation == "missing_full":
                changed.pop(3)
            elif mutation == "stopped":
                changed[0].update(status="not_executed_rejected", completed_steps=24)
            elif mutation == "parity_missing":
                checks.pop()
            elif mutation == "parity_failed":
                checks[0]["passed"] = False
            elif mutation == "parity_wrong_fit":
                checks[0]["fit_id"] = "other-fit"
            else:
                checks[0]["configuration_index"] = 1
            summary = summarize_configuration(0, changed, checks)
            self.assertFalse(summary["eligible"])
            if mutation in ("missing_full", "stopped"):
                self.assertFalse(summary["groups"][0]["available"])
                self.assertEqual(summary["groups"][0]["future"], [])

    def test_weak_development_gain_stays_diagnostic_and_never_opens_confirmation(self):
        rows, parity = complete_family(gain=.005)
        summaries = [summarize_configuration(i, rows,
            [{**row, "configuration_index": i} for row in parity]) for i in range(12)]
        result = select_configuration(summaries)
        self.assertEqual(result["selected_scope"], "diagnostic_only")
        self.assertFalse(result["confirmation_plausibility_passed"])
        self.assertFalse(result["scientific_acceptance"])
        self.assertFalse(result["fresh_confirmation_executed"])

    def test_actual_stride2_disk_artifacts_recover_complete_and_failed_step18(self):
        for fail in (False, True):
            state, train, panels, anchors, config = fixture()
            config.update(commit_stride=2, relinearizations=0)
            calls = []

            def observed(*args, **kwargs):
                calls.append(1)
                if fail and len(calls) == 10:
                    raise RuntimeError("injected infrastructure-level repair interruption")
                return repair_sequence(*args, **kwargs)

            with patch("cell_field_policy_v8.repair_sequence", new=observed):
                result = execute_policy(state, train, panels, panels, anchors, "future_field_h8", config)
            count = 18 if fail else 32
            self.assertEqual(result["record"]["completed_steps"], count)
            selection = (np.zeros((512, 8)), np.tile(np.arange(4), 128))
            inputs = {"split": {"current_train": train}, "current_panels": panels, "old_panels": panels,
                "selection": {"old": selection, "future": selection}}
            with tempfile.TemporaryDirectory() as temp:
                path = Path(temp)/"case"
                row = save_result(path, {"fit_id": "fixture"}, state, inputs, anchors, "future_field_h8", config,
                    result, {"cpu_ns": result["record"]["cpu_ns"]+1000, "wall_ns": result["record"]["wall_ns"]+1000},
                    per_source_nll(state, selection))
                self.assertEqual(row["audit_passed"], not fail)
                saved = read_compressed(path/"controller-checkpoints.json.gz")
                trace = read_compressed(path/"trace.json.gz")
                raw = canonical(saved[str(count)])
                self.assertEqual(raw, canonical(result["controllers"][-1]))
                self.assertEqual(hashlib.sha256(raw).hexdigest(), trace["controller_sha256"][-1])
                actions, states = materialize_checkpoints(path, state, inputs, anchors, "future_field_h8", config)
                np.testing.assert_array_equal(actions, result["actions"])
                self.assertEqual(states[-1].digest(), result["state"].digest())
                for step in (0, 16, 17):
                    self.assertEqual((path/"selected-checkpoints"/str(step)/"controller.json").read_bytes(),
                        canonical(result["controllers"][step]))


if __name__ == "__main__":
    unittest.main()
