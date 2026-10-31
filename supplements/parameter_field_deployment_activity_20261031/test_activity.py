"""Complete synthetic populations for interpretation, not scientific observations."""

from copy import deepcopy
import hashlib
from itertools import product
import json
import unittest

from . import activity as a


def digest(value):
    """Fixture identities only; production uses the unchanged native state recipe."""
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def b_paths():
    paths = []
    for seed, schedule, method in product(
        a.B_SEEDS, range(106000, 106016), a.B_METHODS
    ):
        initial = {k: digest((seed, schedule, k)) for k in a.COMPONENTS}
        trace = []
        for i in range(6):
            action = a.BASELINES[seed]
            if method == "fixed_taper":
                action = [action, action, 2, 1, 1, 0][i]
            receipt = {
                "action_index": action,
                "start": 48 * i,
                "end": 48 * (i + 1),
                "logical_clock": 48 * (i + 1),
                "remaining_steps": 288 - 48 * (i + 1),
                "schedule_id": schedule,
                "multiplier": a.MULTIPLIERS[action],
                "before": deepcopy(initial),
                "candidate": deepcopy(initial),
                "after": deepcopy(initial),
                "accepted": True,
                "guard_delta": 0.0,
                "clock_advances_on_rejection": True,
            }
            trace.append(
                {
                    "decision": i,
                    "before": digest((method, i)),
                    "choice": {
                        "chosen_action": action,
                        "override": action != a.BASELINES[seed],
                        "fallback_reason": None,
                    },
                    "transaction": receipt,
                }
            )
        path = {
            "id": f"seed-{seed}-schedule-{schedule}-{method}",
            "seed": seed,
            "schedule_id": schedule,
            "method": method,
            "trace": trace,
        }
        paths.append(path)
    refresh_b(paths)
    return paths


def refresh_b(paths):
    indexed = {(p["seed"], p["schedule_id"], p["method"]): p for p in paths}
    for path in paths:
        for i, row in enumerate(path["trace"]):
            parts = {
                k: digest((path["seed"], path["schedule_id"], i, k))
                for k in a.B_SECTIONS
            }
            parts.update(
                {
                    k: digest(
                        ("different native recipe", row["transaction"]["after"][k])
                    )
                    for k in a.COMPONENTS
                }
            )
            row["state"] = {
                "components": parts,
                "dynamics": digest(parts),
                "controller_history": digest((path["method"], i)),
            }
        path["overrides"] = sum(row["choice"]["override"] for row in path["trace"])
        path["accepted_overrides"] = sum(
            row["choice"]["override"] and row["transaction"]["accepted"]
            for row in path["trace"]
        )
    for path in paths:
        baseline = indexed[(path["seed"], path["schedule_id"], "ordinary")]
        differences = [
            left["state"]["dynamics"] != right["state"]["dynamics"]
            for left, right in zip(path["trace"], baseline["trace"], strict=True)
        ]
        first = next((i for i, different in enumerate(differences) if different), None)
        path.update(
            first_legal_divergence_decision=first,
            first_legal_divergence_clock=None if first is None else 48 * (first + 1),
            terminal_reference_tail_state_equal=not differences[-1],
        )


def c_paths():
    paths, components = [], {}
    for mode, seed, policy in product(
        a.C_MODES, range(801, 809), ("baseline", "field")
    ):
        state = {
            "schema": "hepta.fullstudy.C.training-state.1",
            "model_config": {"mode": mode},
            "model": {"weight": [float(seed)], "buffer": [1.0]},
            "parameter_names": ["weight"],
            "requires_grad": [True],
            "optimizer": {"state": {}, "param_groups": [{"params": [0]}]},
        }
        whole = digest(state)
        metadata = {
            "schema": "hepta.fullstudy.C.endpoint.1",
            "mode": mode,
            "seed": seed,
            "policy": policy,
            "clock": 96,
            "schedule": 8000,
            "config": {"mode": mode},
            "warmstart_state_sha256": whole,
        }
        trace = [
            {
                "decision": i,
                "before": whole,
                "choice": {"chosen_action": 2, "override": False, "certificate": False},
                "transaction": {
                    "action": 2,
                    "start": 16 * i,
                    "end": 16 * (i + 1),
                    "schedule": 8000,
                    "multiplier": 1.0,
                    "before": whole,
                    "candidate": whole,
                    "after": whole,
                    "accepted": True,
                    "guard_delta": 0.0,
                    "clock_advances": True,
                },
            }
            for i in range(6)
        ]
        path = {
            "mode": mode,
            "seed": seed,
            "policy": policy,
            "metadata": metadata,
            "state_sha256": whole,
            "checkpoint": {
                "path": f"endpoints/{mode}-seed-{seed}-{policy}.pt.gz",
                "bytes": 1,
                "sha256": digest(metadata),
            },
            "decision_state_sha256": [whole] * 6,
            "trace": trace,
            "first_legal_divergence_decision": None,
            "first_legal_divergence_clock": None,
            "overrides": 0,
            "accepted_overrides": 0,
        }
        record = {"state": state, "state_sha256": whole, "metadata": metadata}
        paths.append(path)
        components[(mode, seed, policy)] = a.terminal_components(record, path, digest)
    return paths, components


class ActivityTests(unittest.TestCase):
    def test_full_b_population_counts_history_without_claiming_parameter_activity(self):
        result = a.audit_b(b_paths())
        self.assertEqual(
            (result["path_population"], result["decision_population"]), (240, 1440)
        )
        field = result["counts_by_method"]["field12"]
        self.assertEqual(
            (
                field["paths"],
                field["decisions"],
                field["paired_controller_history_difference"],
            ),
            (48, 288, 288),
        )
        self.assertEqual(result["field_activity_status"], "registered_inactive")
        self.assertEqual(
            result["deployment_action_regret"], "not_identifiable_from_selected_actions"
        )

    def test_b_rejected_changed_candidate_is_not_committed_activity(self):
        paths = b_paths()
        row = paths[1]["trace"][0]
        row["choice"].update(chosen_action=3, override=True)
        row["transaction"].update(
            action_index=3,
            multiplier=2.0,
            accepted=False,
            guard_delta=-0.1,
            candidate={key: digest(("discarded", key)) for key in a.COMPONENTS},
        )
        refresh_b(paths)
        result = a.audit_b(paths)
        field = result["counts_by_method"]["field12"]
        self.assertEqual(
            (
                field["requested_override"],
                field["accepted_override"],
                field["candidate_parameters_change"],
                field["committed_parameters_change"],
            ),
            (1, 0, 1, 0),
        )
        self.assertEqual(result["field_activity_status"], "registered_inactive")

    def test_b_accepted_override_alone_is_not_activity_but_committed_pair_change_is(
        self,
    ):
        paths = b_paths()
        row = paths[1]["trace"][0]
        row["choice"].update(chosen_action=3, override=True)
        row["transaction"].update(action_index=3, multiplier=2.0)
        refresh_b(paths)
        self.assertEqual(
            a.audit_b(paths)["field_activity_status"], "registered_inactive"
        )
        changed = {key: digest(("committed", key)) for key in a.COMPONENTS}
        for i, row in enumerate(paths[1]["trace"]):
            row["transaction"].update(
                candidate=deepcopy(changed), after=deepcopy(changed)
            )
            if i:
                row["transaction"]["before"] = deepcopy(changed)
        refresh_b(paths)
        result = a.audit_b(paths)
        self.assertEqual(
            result["field_activity_status"], "parameter_optimizer_change_observed"
        )
        self.assertEqual(
            result["paths"][1]["first_parameter_optimizer_divergence_clock"], 48
        )

    def test_b_missing_duplicate_baseline_chain_and_nonfinite_rejected(self):
        original = b_paths()
        bad = [original[:-1], original[:-1] + [deepcopy(original[0])]]
        for case in ("baseline", "chain", "nan", "rollback", "recipe"):
            paths = deepcopy(original)
            row = paths[1]["trace"][1]
            if case == "baseline":
                row["choice"]["override"] = True
            elif case == "chain":
                row["transaction"]["before"]["parameters"] = digest("wrong entry")
            elif case == "nan":
                row["choice"]["predicted_advantages"] = [float("nan"), 1, 0, 2]
            elif case == "rollback":
                row["transaction"].update(accepted=False, guard_delta=-1)
                row["transaction"]["after"]["optimizer"] = digest("not restored")
            else:
                row["state"]["components"]["parameters"] = digest(
                    "contradictory recipe"
                )
            bad.append(paths)
        for paths in bad:
            with self.subTest(population=len(paths)), self.assertRaises(ValueError):
                a.audit_b(paths)

    def test_c_full_population_terminal_components_and_buffers_are_separate(self):
        paths, terminal = c_paths()
        result = a.audit_c(paths, terminal)
        self.assertEqual(
            (result["path_population"], result["decision_population"]), (32, 192)
        )
        self.assertEqual(result["counts_by_policy"]["field"]["decisions"], 96)
        self.assertEqual(result["field_activity_status"], "registered_inactive")
        item = terminal[("ordinary", 801, "field")]
        self.assertEqual(item["parameters"], digest({"weight": [801.0]}))
        self.assertNotEqual(
            item["parameters"], digest({"weight": [801.0], "buffer": [1.0]})
        )

    def test_c_checkpoint_buffer_only_change_and_invalid_named_parameter_inventory(
        self,
    ):
        paths, terminal = c_paths()
        path = deepcopy(paths[1])
        state = {
            "schema": "hepta.fullstudy.C.training-state.1",
            "model_config": path["metadata"]["config"],
            "model": {"weight": [801.0], "buffer": [2.0]},
            "parameter_names": ["weight"],
            "requires_grad": [True],
            "optimizer": {"state": {}, "param_groups": [{"params": [0]}]},
        }
        path["state_sha256"] = digest(state)
        record = {
            "state": state,
            "state_sha256": digest(state),
            "metadata": path["metadata"],
        }
        actual = a.terminal_components(record, path, digest)
        baseline = terminal[("ordinary", 801, "field")]
        self.assertNotEqual(actual["state_sha256"], baseline["state_sha256"])
        self.assertEqual(
            [actual[k] for k in a.COMPONENTS], [baseline[k] for k in a.COMPONENTS]
        )
        record["state_sha256"] = digest("unbound record")
        with self.assertRaises(ValueError):
            a.terminal_components(record, path, digest)
        record["state_sha256"] = path["state_sha256"]
        state["parameter_names"] = ["weight", "weight"]
        state["requires_grad"] = [True, True]
        with self.assertRaises(ValueError):
            a.terminal_components(record, path, digest)

    def test_c_intermediate_whole_state_divergence_and_terminal_equality_keep_components_unknown(
        self,
    ):
        paths, terminal = c_paths()
        path = paths[1]
        distinct = digest("intermediate RNG or other unclassified state")
        path["trace"][0]["transaction"].update(candidate=distinct, after=distinct)
        path["decision_state_sha256"][0] = distinct
        path["trace"][1]["before"] = distinct
        path["trace"][1]["transaction"]["before"] = distinct
        path.update(first_legal_divergence_decision=0, first_legal_divergence_clock=16)
        result = a.audit_c(paths, terminal)
        self.assertEqual(result["field_activity_status"], "whole_state_change_only")
        self.assertTrue(
            all(
                not any(row["terminal_paired_component_difference"].values())
                for row in result["paths"]
            )
        )
        self.assertTrue(
            all(
                row["intermediate_parameter_optimizer_activity"]
                == "not_separately_recorded"
                for row in result["paths"]
            )
        )

    def test_c_terminal_component_change_can_be_observed_without_assigning_first_component_clock(
        self,
    ):
        paths, terminal = c_paths()
        path = paths[1]
        final = digest("terminal with changed optimizer")
        path["trace"][-1]["transaction"].update(candidate=final, after=final)
        path["decision_state_sha256"][-1] = path["state_sha256"] = final
        path.update(first_legal_divergence_decision=5, first_legal_divergence_clock=96)
        terminal[("ordinary", 801, "field")].update(
            state_sha256=final, optimizer=digest("changed optimizer")
        )
        result = a.audit_c(paths, terminal)
        self.assertEqual(
            result["field_activity_status"], "parameter_optimizer_change_observed"
        )
        self.assertTrue(
            result["first_parameter_optimizer_divergence_clock"].startswith("unknown")
        )

    def test_c_missing_checkpoint_wrong_binding_zero_action_and_false_equality_rejected(
        self,
    ):
        for case in ("missing", "binding", "zero", "equality"):
            paths, terminal = c_paths()
            if case == "missing":
                terminal.pop(("ordinary", 801, "field"))
            elif case == "binding":
                terminal[("ordinary", 801, "field")]["metadata"] = {"wrong": "binding"}
            elif case == "zero":
                row = paths[1]["trace"][0]
                row["choice"].update(chosen_action=0, override=True)
                row["transaction"].update(
                    action=0,
                    multiplier=0,
                    candidate=digest("changed"),
                    after=digest("changed"),
                )
            else:
                terminal[("ordinary", 801, "field")]["optimizer"] = digest(
                    "unequal inside equal whole state"
                )
            with self.subTest(case=case), self.assertRaises(ValueError):
                a.audit_c(paths, terminal)


if __name__ == "__main__":
    unittest.main()
