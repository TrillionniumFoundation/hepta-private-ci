"""Online check policy with actual pinned SQLite effects and readbacks."""

import json

from .model_heads import head_score
from .model_protocol import ARMS, EVENT, cases, digest, public_view


class Pilot:
    def __init__(self, journal, dependencies, backend, plan):
        self.journal, self.backend, self.plan = journal, backend, plan
        self.runtime, self.c = dependencies["runtime"], dependencies["contracts"]
        self.heads, self.prior = None, None
        self.calibration_rows, self.trajectories = [], []

    def scope(self, goal, attempt, tick, event=EVENT, state_version=None):
        return self.c.Scope(goal["task_id"], attempt, self.runtime.sha(goal),
                            tick if state_version is None else state_version,
                            "sqlite_two_field_ack_only_model_pilot_v1", event, tick, max(3, tick))

    def identity(self, arm):
        base = self.backend.identities["qwen"]["base_sha256"]
        adapter = None
        if arm == "bases_two":
            base = digest([base, self.backend.identities["smol"]["base_sha256"]])
        if arm == "readout_heads_two":
            adapter = digest([head["adapter_sha256"] for head in self.heads[:2]])
        if arm in ("constant_prior", "fixed_check"):
            base = digest({"fitted_training_prior": self.prior})
        return self.c.ModelIdentity(base, adapter, digest({"plan": digest(self.plan), "arm": arm}))

    def readout(self, index, view, context):
        feature = self.backend.features(view, {**context, "head_index": index})
        head = self.heads[index]
        with self.journal.operation("trained_readout", {**context, "head_index": index}) as receipt:
            score = head_score(head, feature["values"], feature["base_sha256"])
            result = {key: value for key, value in feature.items() if key != "values"}
            result.update(score=score, feature_operation_id=feature["operation_id"], operation_id=receipt["operation_id"], adapter_sha256=head["adapter_sha256"])
            receipt.update(result)
        return result

    def assess(self, arm, view, context):
        members = []
        if arm in ("constant_prior", "fixed_check"):
            score = self.prior
        elif arm == "readout_heads_two":
            members = [self.readout(index, view, context) for index in (0, 1)]
        else:
            roster = {"single": [("qwen", "neutral")], "repeat_two": [("qwen", "neutral"), ("qwen", "neutral")],
                      "roles_two": [("qwen", "neutral"), ("qwen", "auditor")], "bases_two": [("qwen", "neutral"), ("smol", "neutral")]}
            for index, (model, role) in enumerate(roster[arm]):
                members.append(self.backend.score(model, role, view, {**context, "voter_index": index}))
        with self.journal.operation("score_aggregation", context) as receipt:
            if members:
                score = sum(member["score"] for member in members) / len(members)
            result = {"assessment_id": receipt["operation_id"], "arm": arm, "context": context,
                      "view": view, "evidence_sha256": digest(view), "score": score, "members": members,
                      "calibrated": False, "production_authority": "NONE"}
            receipt.update(result)
            self.journal.append("assessments.jsonl", result)
        return result

    def host(self, kind, context, function, *args, **kwargs):
        with self.journal.operation(kind, context) as receipt:
            result = function(*args, **kwargs)
            receipt["result"] = result
            return result, receipt["operation_id"]

    def database(self, case, attempt):
        directory = self.journal.directory / "state" / digest({"case": case["goal"]["task_id"], "attempt": attempt})[:24]
        directory.mkdir(parents=True, exist_ok=False)
        path = directory / "effects.sqlite"
        self.host("host_initialize", {"case_id": case["goal"]["task_id"], "split": case["split"], "arm": attempt}, self.runtime.initialize, path, case["goal"])
        return path

    def panel(self, split):
        training = []
        for case in cases(split):
            goal, acks, pending = case["goal"], [], []
            context = {"split": split, "case_id": goal["task_id"], "attempt": split + "/uninterrupted_panel"}
            database = self.database(case, context["attempt"])
            for tick in (0, 1, 2, 3):
                if tick:
                    effect, _ = self.host("host_effect", {**context, "tick": tick}, self.runtime.execute_step, database, goal, case["fault"], tick)
                    acks.append(effect["ack"])
                view = public_view(acks)
                if split == "train" and tick in (0, 2, 3):
                    feature = self.backend.features(view, {**context, "tick": tick})
                    pending.append({"case_id": goal["task_id"], "source_group": case["source_group"], "split": split, "tick": tick,
                                    "feature": feature["values"], "feature_operation_id": feature["operation_id"], "evidence_sha256": digest(view)})
                elif split == "calibration" and tick in (0, 3):
                    for arm in ARMS:
                        assessment = self.assess(arm, view, {**context, "arm": arm, "tick": tick})
                        pending.append({"case_id": goal["task_id"], "source_group": case["source_group"], "tick": tick, **assessment})
                    # Extra role/head are separate diagnostics, outside the two-voter comparison.
                    role = self.backend.score("qwen", "skeptic", view, {**context, "tick": tick, "diagnostic": True})
                    head = self.readout(2, view, {**context, "tick": tick, "diagnostic": True})
                    self.journal.append("diagnostic_predictions.jsonl", {**context, "tick": tick, "role": role, "head": head})
            label, label_operation = self.host("independent_outcome_label", context, self.runtime.outcome, database, goal)
            self.journal.append("panel_labels.jsonl", {**context, "source_group": case["source_group"], "label": label, "label_operation_id": label_operation, "all_three_effect_steps_completed": True})
            for row in pending:
                row.update(label=label, label_operation_id=label_operation)
                if split == "train":
                    training.append(row)
                    self.journal.append("training_features.jsonl", row)
                else:
                    self.calibration_rows.append(row)
                    self.journal.append("calibration_observations.jsonl", row)
        return training

    def calibrate(self):
        for arm in ARMS:
            for tick in (0, 3):
                rows = [row for row in self.calibration_rows if row["arm"] == arm and row["tick"] == tick]
                report = self.c.CalibrationReport(
                    self.c.Scope("calibration-panel", arm + "/tick/" + str(tick), digest(rows), 0,
                                 "sqlite_two_field_ack_only_model_pilot_v1", EVENT, 3, 3),
                    self.identity(arm),
                    tuple(sorted({case["source_group"] for case in cases("train")})) if arm in ("readout_heads_two", "constant_prior", "fixed_check") else (),
                    tuple(sorted({case["source_group"] for case in cases("calibration")})),
                    tuple(sorted({case["source_group"] for case in cases("confirmation")})),
                    digest(rows), "brier", "proper_scoring_rule", sum((row["score"] - row["label"]) ** 2 for row in rows) / len(rows), len(rows), "unknown",
                    ("diagnostic only; no calibration map fitted", "shared synthetic templates are not independent natural tasks", "uninterrupted fixed-effect policy labels; online stopping changes the estimand", "pretraining distributions unknown; no drift guarantee"))
                self.journal.append("calibration_reports.jsonl", json.loads(self.c.canonical_json(report)))

    def check(self, database, case, arm, tick, mandatory=False):
        context = {"case_id": case["goal"]["task_id"], "split": case["split"], "arm": arm, "tick": tick}
        keys = ("property", "assumptions", "checker_id", "checker_version", "evidence_sha256", "checked_step", "verdict", "reason", "residual_obligations")
        saw_nonproved = False
        for readback in range(2 if mandatory else 1):
            report, _ = self.host("mandatory_host_check" if mandatory else "optional_host_check", context,
                                  self.runtime.inspect, database, case["goal"], tick, accept=mandatory)
            saw_nonproved |= report["verdict"] != "proved"
            receipt = self.c.VerificationReceipt(self.scope(case["goal"], arm, tick, "actual_goal_and_owner_snapshot_property", report["state_version"]), **{key: report[key] for key in keys})
            self.journal.append("verification_receipts.jsonl", json.loads(self.c.canonical_json(receipt)))
            if report["reason"] != "missing_ack_requires_readback" or readback:
                break
            self.host("host_reconcile_without_replay", context, self.runtime.reconcile, database, case["goal"], tick)
        return {**report, "saw_nonproved": saw_nonproved}

    def trajectory(self, case, arm, intervention=None):
        name = arm if intervention is None else "intervention/" + intervention["name"]
        context = {"split": "confirmation", "case_id": case["goal"]["task_id"], "arm": name}
        self.journal.append("trajectory_attempts.jsonl", {**context, "status": "started"})
        row = {**context, "source_group": case["source_group"], "fault": case["fault"], "risk": None,
               "accepted": False, "outcome_error": None, "interrupted": False, "detected_step": None,
               "injected_step": None, "reached_step": 0, "status": "failed", "initial_assessment": None}
        database, acks = None, []
        remaining = 1.0 if intervention else 0.4
        try:
            database = self.database(case, name)
            if intervention is None:
                initial = self.assess(arm, public_view([]), {**context, "tick": 0})
                row.update(risk=initial["score"], initial_assessment=initial)
            for tick in (1, 2, 3):
                effect, _ = self.host("host_effect", {**context, "tick": tick}, self.runtime.execute_step, database, case["goal"], case["fault"], tick)
                acks.append(effect["ack"])
                row["reached_step"] = tick
                if tick not in ((2,) if intervention else (2, 3)):
                    continue
                view = public_view(acks)
                assessment = self.assess(arm, view, {**context, "tick": tick})
                raw_score = assessment["score"]
                policy_score, cost = (intervention["risk"], intervention["cost"]) if intervention else (raw_score, 0.2)
                risk = self.c.RiskPrediction(self.scope(case["goal"], name, tick), self.identity(arm), raw_score, tick, digest(view))
                self.journal.append("risk_predictions.jsonl", json.loads(self.c.canonical_json(risk)))
                decision = self.c.select_check(policy_score, cost, 1.0, remaining)
                if arm == "fixed_check" and intervention is None:
                    decision = "check" if tick == 3 and remaining >= cost else "defer"
                decision_row = {**context, "tick": tick, "assessment_id": assessment["assessment_id"], "evidence_sha256": digest(view),
                                "matched_evidence_parent_sha256": digest({"view": view, "model": self.identity(arm).base_sha256, "prompts": [member["prompt_sha256"] for member in assessment["members"]]}),
                                "raw_model_score": raw_score, "policy_risk_input": policy_score, "declared_check_cost": cost,
                                "budget_before": remaining, "selection": decision, "intervention": intervention}
                self.journal.append("decisions.jsonl", decision_row)
                if intervention:
                    row["risk"] = raw_score
                if decision == "blocked":
                    row["interrupted"] = True
                    break
                if decision != "check":
                    continue
                report = self.check(database, case, name, tick)
                remaining = round(remaining - cost, 10)
                if report["saw_nonproved"] and row["detected_step"] is None:
                    row["detected_step"] = tick
                if report["verdict"] != "proved" and report["reason"] != "missing_ack_requires_readback":
                    row["interrupted"] = True
                    break
            if not row["interrupted"]:
                report = self.check(database, case, name, 4, mandatory=True)
                row["accepted"] = report["accepted"]
                if report["saw_nonproved"] and row["detected_step"] is None:
                    row["detected_step"] = 4
            row["outcome_error"], _ = self.host("independent_outcome_label", context, self.runtime.outcome, database, case["goal"])
            row["status"] = "completed"
        except BaseException as error:
            row["status"] = "cancelled" if isinstance(error, KeyboardInterrupt) else "failed"
            row["failure"] = {"type": type(error).__name__, "message": str(error)}
            raise
        finally:
            injected = None if case["fault"] == "clean" else 3 if case["fault"] == "stale_read" else 2
            row["injected_step"] = injected if injected is not None and row["reached_step"] >= injected else None
            self.trajectories.append(row)
            self.journal.append("trajectory_rows.jsonl", row)
            self.journal.append("trajectory_attempts.jsonl", {**context, "status": row["status"]})
        return row
