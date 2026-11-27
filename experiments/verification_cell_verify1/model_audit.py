"""Read-only consistency checks on the pilot's actual inference/host ledger."""

from .model_protocol import digest, finite_probability


def inference_bindings(assessments, operations, trajectories, decisions):
    """A smoke forward or dangling member reference cannot qualify policy use."""
    try:
        ops = {row["operation_id"]: row for row in operations}
        assessments_by_id = {row["assessment_id"]: row for row in assessments}
        if len(ops) != len(operations) or len(assessments_by_id) != len(assessments) or not assessments:
            return False
        expected_decisions = {(row["case_id"], row["arm"], tick) for row in trajectories if row["status"] == "completed"
                              for tick in ((2,) if row["arm"].startswith("intervention/") else (2, 3)) if tick <= row["reached_step"]}
        decision_keys = [(row["case_id"], row["arm"], row["tick"]) for row in decisions]
        if len(decision_keys) != len(set(decision_keys)) or set(decision_keys) != expected_decisions:
            return False
        used = set()
        rosters = {"single": [("qwen", "neutral")], "repeat_two": [("qwen", "neutral"), ("qwen", "neutral")],
                   "roles_two": [("qwen", "neutral"), ("qwen", "auditor")], "bases_two": [("qwen", "neutral"), ("smol", "neutral")],
                   "readout_heads_two": [("qwen", "neutral"), ("qwen", "neutral")], "constant_prior": [], "fixed_check": []}
        for assessment in assessments:
            aggregation = ops[assessment["assessment_id"]]
            if aggregation["status"] != "completed" or aggregation["kind"] != "score_aggregation" or any(aggregation[key] != value for key, value in assessment.items()):
                return False
            members, context = assessment["members"], assessment["context"]
            if len(members) != len(rosters[assessment["arm"]]) or assessment["evidence_sha256"] != digest(assessment["view"]) or assessment["view"]["tick"] != context["tick"]:
                return False
            for index, (member, (model, role)) in enumerate(zip(members, rosters[assessment["arm"]])):
                op = ops[member["operation_id"]]
                expected_kind = "trained_readout" if assessment["arm"] == "readout_heads_two" else "model_score"
                if op["operation_id"] in used or op["status"] != "completed" or op["kind"] != expected_kind or any(op["context"].get(key) != value for key, value in context.items()):
                    return False
                used.add(op["operation_id"])
                if any(op[key] != member[key] for key in ("score", "base_sha256", "adapter_sha256", "prompt_sha256", "evidence_sha256")) or member["evidence_sha256"] != assessment["evidence_sha256"]:
                    return False
                finite_probability(member["score"])
                if expected_kind == "trained_readout":
                    feature = ops[member["feature_operation_id"]]
                    if op["feature_operation_id"] != feature["operation_id"] or feature["operation_id"] in used or feature["kind"] != "model_features" or feature["status"] != "completed":
                        return False
                    used.add(feature["operation_id"])
                    if any(feature["context"].get(key) != value for key, value in context.items()) or feature["context"]["head_index"] != index:
                        return False
                    if any(feature[key] != member[key] for key in ("base_sha256", "prompt_sha256", "evidence_sha256")):
                        return False
                    op = feature
                if op["model"] != model or op["role"] != role or op["view"] != assessment["view"] or op["prompt_sha256"] != digest(op["prompt"]):
                    return False
            finite_probability(assessment["score"])
            if members and assessment["score"] != sum(member["score"] for member in members) / len(members):
                return False
        for row in trajectories:
            initial = row.get("initial_assessment")
            if initial is not None:
                if assessments_by_id[initial["assessment_id"]] != initial or initial["context"]["case_id"] != row["case_id"] or initial["context"]["arm"] != row["arm"] or initial["context"]["tick"] != 0 or initial["score"] != row["risk"]:
                    return False
            elif not row["arm"].startswith("intervention/") and row["status"] == "completed":
                return False
        for decision in decisions:
            assessment = assessments_by_id[decision["assessment_id"]]
            if any(assessment["context"].get(key) != decision[key] for key in ("case_id", "arm", "tick", "split")) or decision["raw_model_score"] != assessment["score"] or decision["evidence_sha256"] != assessment["evidence_sha256"]:
                return False
            members = assessment["members"]
            base = digest([member["base_sha256"] for member in members]) if assessment["arm"] == "bases_two" else members[0]["base_sha256"] if members else digest({"fitted_training_prior": assessment["score"]})
            expected_parent = digest({"view": assessment["view"], "model": base, "prompts": [member["prompt_sha256"] for member in members]})
            if decision["matched_evidence_parent_sha256"] != expected_parent:
                return False
            checks = [op for op in operations if op["kind"] == "optional_host_check" and op["status"] == "completed" and all(op["context"].get(key) == decision[key] for key in ("case_id", "arm", "tick"))]
            if len(checks) != int(decision["selection"] == "check"):
                return False
        return True
    except (KeyError, TypeError, ValueError, IndexError):
        return False


def panel_bindings(labels, operations, plan):
    """Require every frozen panel case once, with three effects and actual label."""
    try:
        expected = {(split, case["goal"]["task_id"]): case for split in ("train", "calibration") for case in plan["cases"][split]}
        actual = {(row["split"], row["case_id"]): row for row in labels}
        if len(actual) != len(labels) or set(actual) != set(expected):
            return False
        ops = {row["operation_id"]: row for row in operations}
        for key, row in actual.items():
            label = ops[row["label_operation_id"]]
            if row["source_group"] != expected[key]["source_group"] or row["all_three_effect_steps_completed"] is not True or type(row["label"]) is not bool or label["result"] is not row["label"]:
                return False
            if label["kind"] != "independent_outcome_label" or label["status"] != "completed" or any(label["context"].get(field) != row[field] for field in ("split", "case_id", "attempt")):
                return False
            effects = [op for op in operations if op["kind"] == "host_effect" and op["status"] == "completed" and all(op["context"].get(field) == row[field] for field in ("split", "case_id", "attempt"))]
            if len(effects) != 3 or {op["context"]["tick"] for op in effects} != {1, 2, 3} or any(op["result"]["replayed"] is not False for op in effects):
                return False
        return True
    except (KeyError, TypeError, ValueError):
        return False
