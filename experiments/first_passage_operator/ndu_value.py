"""New planning-profile binding around the unchanged original native Q32 owner.

The original maintenance adapter remains frozen. This adapter changes the
objective/plan envelope, not native recursive utility, rounding, cost bounds,
rejection rules or authority. Actual trajectories retain its external ledger
validator through inheritance.
"""

from experiments.first_passage_cell.ndu import (
    Q32, RECURSIVE_PROFILE, SCHEMA, NativeNduPort, object_digest, q32,
)

OBJECTIVE = {
    "schema": "hepta.regenerative.maintenance-objective.v1",
    "recursive_profile": RECURSIVE_PROFILE,
    "running_rate": 0.6,
    "failure_penalty": 0.5,
    "control_interval": 0.5,
    "maximum_horizon": 2.0,
    "utility_unit": "task-return",
    "discount_per_control_interval": 1.0,
    "repair_charge": "actual public price once per executed repair",
}


class BellmanNduPort(NativeNduPort):
    """Preserve native algorithms while binding each new forecast to its plan."""

    def _snapshot(self, parameters, observation, context):
        snapshot = super()._snapshot(parameters, observation, context)
        snapshot["profile"] = OBJECTIVE
        snapshot["objective_digest"] = object_digest(OBJECTIVE)
        snapshot["schema"] = "hepta.regenerative.ndu-snapshot.v1"
        return snapshot

    def evaluate_paths(self, paths, snapshot, *, generation=1, resource_budget=1_000_000,
                       risk_ceiling=1.0):
        plan = snapshot.get("continuation_plan", snapshot.get("plan_policy"))
        if plan not in {"FINITE_HORIZON_REPLAN_SAME_BELLMAN_RECURSION", "WAIT_AFTER_CURRENT",
                        "ACTUALLY_EXECUTED_ACTIONS"}:
            raise ValueError("a declared forecast or actually executed continuation plan is required")
        objective = object_digest(OBJECTIVE)
        bound_snapshot = {**snapshot, "objective": OBJECTIVE, "objective_digest": objective,
                          "native_binary_sha256": self.binary_sha256,
                          "native_source_manifest_sha256": self.source_manifest_sha256}
        snapshot_digest = object_digest(bound_snapshot)
        supplied = dict(paths)
        names = {str(name).upper() for name in supplied}
        if "STOP" in names and "ABSTAIN" in names:
            raise ValueError("duplicate native abstention alternatives")
        if not names.intersection({"STOP", "ABSTAIN"}):
            supplied["ABSTAIN"] = {"events": [{"instant": 0.0, "discount": 1.0}],
                                   "terminal": 0.0, "resource_cost": 0.0, "risk": 0.0}
        candidates, native_names = [], {}
        for name, path in supplied.items():
            native_id = "abstain" if str(name).upper() in {"STOP", "ABSTAIN"} else str(name).lower()
            if native_id in native_names:
                raise ValueError("duplicate native candidate mapping")
            native_names[native_id] = str(name).upper()
            events = [{"event_digest": object_digest([snapshot_digest, name, index + 1, event]),
                       "preference_digest": objective, "instant_q32": q32(event["instant"]),
                       "discount_q32": q32(event.get("discount", 1.0))}
                      for index, event in enumerate(path["events"])]
            candidates.append({"id": native_id, "verified": path.get("verified", True),
                               "verification_digest": object_digest(["contract-checked", snapshot_digest, name]),
                               "support_digest": object_digest(["candidate-path", snapshot_digest, name, path]),
                               "resource_cost_q32": q32(path.get("resource_cost", 0.0)),
                               "risk_q32": q32(path.get("risk", 0.0)), "uncertainty_q32": 0,
                               "terminal_q32": q32(path.get("terminal", 0.0)), "events": events})
        request = {"schema": SCHEMA, "recursive_profile": RECURSIVE_PROFILE,
                   "objective_digest": objective, "snapshot_digest": snapshot_digest,
                   "generation": int(generation), "utility_unit": "task-return",
                   "resource_unit": "task-cost", "risk_unit": "probability",
                   "resource_budget_q32": q32(resource_budget), "risk_ceiling_q32": q32(risk_ceiling),
                   "candidates": candidates}
        # Original port independently recomputes every signed-Q32 recurrence and
        # receipt digest, then checks the unchanged native build identity.
        response = self._invoke(request)
        return {"schema": "hepta.regenerative.native-evaluation.v1", "request": request,
                "response": response, "snapshot": bound_snapshot,
                "action_values": {native_names[row["id"]]: row["values_q32"][0] / Q32
                                  for row in response["paths"]},
                "native_candidate_to_action": native_names, "binary_sha256": self.binary_sha256,
                "source_manifest_sha256": self.source_manifest_sha256}
