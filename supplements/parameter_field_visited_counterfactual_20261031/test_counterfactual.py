"""Synthetic state-machine fixtures; no scientific inputs, model or Torch import."""

from copy import deepcopy
import unittest

from . import counterfactual as c


def item(name):
    return {"path": "synthetic/" + name, "bytes": 1, "sha256": c.digest(name)}


class Backend:
    def __init__(self, spec, rejected=()):
        self.spec, self.rejected = spec, set(rejected)
        self.work, self.events = 0, []
        self.lock = None
        self.restore_parent()

    def restore_parent(self):
        self.value = self.momentum = 0
        self.clock = self.spec["clock"]
        self.history = list(range(self.spec["decision"]))
        self.events.append(("restore", self.clock))

    def native(self):
        if self.spec["stage"] == "C":
            return c.digest((self.value, self.momentum))
        return {
            "parameters": c.digest(self.value),
            "optimizer": c.digest(self.momentum),
        }

    def snapshot(self):
        physical = (
            (self.value, self.momentum, self.clock)
            if self.spec["stage"] == "B"
            else (self.value, self.momentum)
        )
        complete = (physical, self.history) if self.spec["stage"] == "B" else physical
        return {
            "clock": self.clock,
            "complete_sha256": c.digest(complete),
            "dynamics_sha256": c.digest(physical),
            "native": self.native(),
        }

    def transition(self, action, clock):
        before, saved = self.native(), (self.value, self.momentum)
        if action:
            self.value += action
            self.momentum = action
        candidate = self.native()
        accepted = action not in self.rejected
        if not accepted:
            self.value, self.momentum = saved
        self.clock = clock + self.spec["grain"]
        self.work += self.spec["grain"]
        self.events.append(("transition", action, clock))
        return {
            "action": action,
            "start": clock,
            "end": self.clock,
            "schedule": self.spec["schedule"],
            "multiplier": c.MULTIPLIERS[action],
            "native_before": before,
            "native_candidate": candidate,
            "native_after": self.native(),
            "accepted": accepted,
            "guard_delta": 0.25 if accepted else -0.25,
            "guard_outputs_sha256": c.digest(("guard outputs", candidate)),
            "fixed_guard_sha256": c.digest("fixed original guard"),
            "tape_sha256": c.digest((self.spec["seed"], self.spec["schedule"], clock)),
            "clock_advances": True,
            "scheduled_gradient_microsteps": self.spec["grain"],
        }

    def advance_original(self, lock):
        receipt = self.transition(
            lock["original_choice"]["chosen_action"], self.spec["clock"]
        )
        if self.spec["stage"] == "B":
            self.history.append((receipt["action"], receipt["accepted"]))
        self.events.append(("original_continuation",))
        return receipt

    def scheduled_microsteps(self):
        return self.work

    def seal_state(self, kind, action):
        self.events.append(("seal", kind, action))
        return {
            "artifact": item(f"{self.spec['id']}-{kind}-{action}"),
            "state_sha256": self.snapshot()["complete_sha256"],
        }


def prepare(spec, *, rejected=(), override=False):
    backend = Backend(spec, rejected)
    baseline = spec["baseline"]
    scores = [0.0] * 4
    selected = (3 if baseline != 3 else 2) if override else baseline
    if override:
        scores[selected] = 0.2
    lock = {
        "parent_id": spec["id"],
        "parent_state_sha256": backend.snapshot()["complete_sha256"],
        "source_trace": item("original-trace"),
        "frozen_head": item("original-head"),
        "persisted_choice_lock": item("choice-lock"),
        "fixed_guard_sha256": c.digest("fixed original guard"),
        "original_choice": {
            "chosen_action": selected,
            "override": override,
            "threshold": 0.1,
            "predicted_advantages": scores,
        },
    }
    if spec["stage"] == "B":
        lock["frozen_predictors"] = {
            name: {
                "head": lock["frozen_head"]
                if name == "field12"
                else item(name + "-head"),
                "choice": deepcopy(lock["original_choice"]),
            }
            for name in c.PREDICTORS
        }
    receipt = backend.advance_original(lock)
    lock["original_transaction_fingerprint"] = c.digest(c.stable_transition(receipt))
    lock["actual_successor_sha256"] = backend.snapshot()["complete_sha256"]
    backend.work = 0
    backend.events.clear()
    backend.restore_parent()
    return lock, backend


def scored(record, values=None):
    spec = record["parent"]
    values = values if values is not None else [0.1, 0.2, 0.3, 0.4]
    scores = [
        {
            role: {
                "artifact": item(f"action-{action}-{role}"),
                "panel_sha256": c.digest((spec["stage"], role)),
                "emissions_sha256": c.digest((action, role)),
                "rows": c.ROWS[spec["stage"]][role],
                "means": {o: values[action] for o in c.OBSERVERS},
            }
            for role in c.ROLES
        }
        for action in range(4)
    ]
    reference = {
        "artifact": item("frozen-reference-clean"),
        "panel_sha256": c.digest((spec["stage"], "clean")),
        "emissions_sha256": c.digest("reference outputs"),
        "rows": c.ROWS[spec["stage"]]["clean"],
        "means": {o: 0.35 for o in c.OBSERVERS},
    }
    return scores, reference


class CounterfactualTests(unittest.TestCase):
    def test_fixed_shadow_heads_reuse_the_same_Q_without_claiming_their_own_occupancy(
        self,
    ):
        spec = list(c.PARENTS.values())[5]
        lock, backend = prepare(spec, override=True)
        lock["frozen_predictors"]["full_current_state"]["choice"] = {
            "predicted_advantages": [0.0, 0.4, 0.0, 0.1],
            "threshold": 0.2,
            "chosen_action": 1,
            "override": True,
        }
        lock["frozen_predictors"]["history6"]["choice"] = {
            "predicted_advantages": [0.0, 0.3, 0.0, 0.1],
            "threshold": 0.4,
            "chosen_action": 2,
            "override": False,
        }
        record = c.enumerate_parent(spec, lock, backend)
        before = backend.work
        scores, reference = scored(record, [0.1, 0.4, 0.3, 0.2])
        result = c.reduce_parent(record, scores, reference)[
            "frozen_predictor_comparison"
        ]
        self.assertEqual(backend.work, before)
        self.assertAlmostEqual(
            result["chosen_gain_increments"]["full_current_state-minus-field12"][
                "task"
            ]["reward"],
            0.2,
        )
        self.assertAlmostEqual(
            result["chosen_gain_increments"]["history6-minus-field12"]["task"]["audit"],
            0.1,
        )
        self.assertFalse(result["own_closed_loop_policy_value_is_estimated"])
        self.assertFalse(result["information_oracle_or_irreducible_information_bound"])
        self.assertFalse(result["original_W_reflection_reachability_established"])
        for reason in ("missing", "changed_field"):
            bad = deepcopy(lock)
            if reason == "missing":
                bad["frozen_predictors"].pop("history6")
            else:
                bad["frozen_predictors"]["field12"]["choice"]["threshold"] = 0.25
            with self.assertRaises(ValueError):
                c.check_lock(spec, bad)

    def test_fixed_complete_population_and_physical_work(self):
        inventory = c.work_inventory()
        self.assertEqual(len(c.PARENTS), 384)
        self.assertEqual((inventory["B"]["paths"], inventory["C"]["paths"]), (48, 16))
        self.assertEqual(
            (inventory["B"]["primary_tails"], inventory["C"]["primary_tails"]),
            (1152, 384),
        )
        self.assertEqual(inventory["total_microsteps"], 284160)
        self.assertEqual(inventory["B"]["total_microsteps"], 255744)
        self.assertEqual(inventory["C"]["total_microsteps"], 28416)

    def test_b_and_c_all_arms_matched_tails_audit_and_original_continuation(self):
        for position in (0, 5, 96, 288, 383):
            spec = list(c.PARENTS.values())[position]
            lock, backend = prepare(spec, override=True)
            result = c.enumerate_parent(spec, lock, backend)
            expected = 5 * (spec["steps"] - spec["clock"]) + spec["grain"]
            self.assertEqual(result["physical_microsteps"], expected)
            self.assertEqual(backend.work, expected)
            self.assertEqual([r["action"] for r in result["branches"]], list(range(4)))
            for action, branch in enumerate(result["branches"]):
                self.assertEqual(
                    [r["action"] for r in branch["transactions"]],
                    [action] + [spec["baseline"]] * (5 - spec["decision"]),
                )
            self.assertEqual(backend.events[-1], ("original_continuation",))
            self.assertFalse(result["endpoint_values_opened_here"])
            self.assertFalse(result["scientific_admission_performed_here"])

    def test_rejected_override_keeps_paid_work_and_need_not_equal_baseline_arm(self):
        spec = list(c.PARENTS.values())[5]
        lock, backend = prepare(spec, rejected=(3,), override=True)
        result = c.enumerate_parent(spec, lock, backend)
        rejected = result["branches"][3]
        first = rejected["transactions"][0]
        self.assertFalse(first["accepted"])
        self.assertEqual(first["native_after"], first["native_before"])
        self.assertNotEqual(first["native_after"], first["native_candidate"])
        self.assertNotEqual(
            rejected["first"]["dynamics_sha256"],
            result["branches"][2]["first"]["dynamics_sha256"],
        )
        self.assertEqual(result["physical_microsteps"], 288)

    def test_wrong_parent_changed_choice_changed_tape_and_unpaid_work_fail_closed(self):
        spec = list(c.PARENTS.values())[0]
        for corruption in ("parent", "choice", "tape", "work"):
            lock, backend = prepare(spec)
            if corruption == "parent":
                lock["parent_state_sha256"] = c.digest("different parent")
            elif corruption == "choice":
                lock["original_choice"]["chosen_action"] = 1
            elif corruption == "tape":
                original = backend.transition

                def transition(action, clock):
                    receipt = original(action, clock)
                    receipt["tape_sha256"] = c.digest((action, clock))
                    return receipt

                backend.transition = transition
            else:
                original = backend.transition

                def transition(action, clock):
                    receipt = original(action, clock)
                    if action == 0:
                        backend.work -= spec["grain"]
                    return receipt

                backend.transition = transition
            with self.subTest(corruption=corruption), self.assertRaises(ValueError):
                c.enumerate_parent(spec, lock, backend)
            if corruption != "work":
                self.assertNotIn(("original_continuation",), backend.events)

    def test_independent_audit_and_actual_successor_must_match(self):
        spec = list(c.PARENTS.values())[5]
        for corruption in ("audit", "actual"):
            lock, backend = prepare(spec)
            if corruption == "actual":
                lock["actual_successor_sha256"] = c.digest("wrong historical successor")
            else:
                original, calls = backend.transition, [0]

                def transition(action, clock):
                    calls[0] += 1
                    receipt = original(action, clock)
                    if calls[0] == 5:
                        receipt["guard_delta"] = 0.5
                    return receipt

                backend.transition = transition
            with self.subTest(corruption=corruption), self.assertRaises(ValueError):
                c.enumerate_parent(spec, lock, backend)

    def test_advantage_regret_prediction_residual_and_retention_signs(self):
        spec = list(c.PARENTS.values())[5]
        lock, backend = prepare(spec, override=True)
        record = c.enumerate_parent(spec, lock, backend)
        scores, reference = scored(record, [0.1, 0.4, 0.3, 0.2])
        result = c.reduce_parent(record, scores, reference)
        effects = result["effects"]["task"]["reward"]
        self.assertAlmostEqual(effects["chosen_advantage"], -0.1)
        self.assertAlmostEqual(effects["attainable_gain"], 0.1)
        self.assertAlmostEqual(effects["finite_panel_regret"], 0.2)
        self.assertAlmostEqual(
            result["chosen_clean_minus_original_frozen_or_warmstart"]["audit"], -0.15
        )
        diagnostic = result["frozen_threshold_diagnostic"]
        self.assertAlmostEqual(diagnostic["probe_reward_overprediction"][3], 0.3)
        self.assertTrue(diagnostic["chosen_exceeds_threshold"])
        self.assertFalse(diagnostic["certificate"])

    def test_equal_state_missing_arm_and_misaligned_panel_cannot_be_scored_as_advantage(
        self,
    ):
        spec = list(c.PARENTS.values())[5]
        lock, backend = prepare(spec)
        record = c.enumerate_parent(spec, lock, backend)
        for corruption in ("equal_state", "missing_arm", "panel", "nan", "rows"):
            bad, (scores, reference) = deepcopy(record), scored(record)
            if corruption == "equal_state":
                bad["branches"][3]["terminal"] = deepcopy(
                    bad["branches"][2]["terminal"]
                )
            elif corruption == "missing_arm":
                scores.pop()
            elif corruption == "panel":
                scores[0]["task"]["panel_sha256"] = c.digest("unpaired panel")
            elif corruption == "nan":
                scores[0]["probe"]["means"]["reward"] = float("nan")
            else:
                scores[0]["clean"]["rows"] -= 1
            with self.subTest(corruption=corruption), self.assertRaises(ValueError):
                c.reduce_parent(bad, scores, reference)

    def test_complete_grid_rejects_duplicates_and_missing_parents(self):
        rows = []
        for spec in c.PARENTS.values():
            lock, backend = prepare(spec)
            record = c.enumerate_parent(spec, lock, backend)
            scores, reference = scored(record)
            rows.append(c.reduce_parent(record, scores, reference))
        summary = c.complete_summary(rows)
        self.assertEqual(summary["parent_population"], 384)
        self.assertEqual(len(summary["per_architecture_and_seed"]), 19)
        self.assertFalse(summary["statistical_efficacy_or_adoption_claim"])
        for bad in (rows[:-1], rows[:-1] + [rows[0]]):
            with self.assertRaises(ValueError):
                c.complete_summary(bad)


if __name__ == "__main__":
    unittest.main()
