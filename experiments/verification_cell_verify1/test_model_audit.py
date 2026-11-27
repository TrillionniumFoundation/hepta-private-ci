import copy
import unittest

from .model_audit import inference_bindings, panel_bindings
from .model_protocol import cases, digest, public_view


def inference_fixture(heads=False):
    arm = "readout_heads_two" if heads else "single"
    context = {"split": "confirmation", "case_id": "unit-case", "arm": arm, "tick": 0}
    view, prompt = public_view([]), "unit-only prompt"
    members, operations = [], []
    for index in range(2 if heads else 1):
        member = {"operation_id": "member/" + str(index), "score": 0.3, "base_sha256": "a" * 64,
                  "adapter_sha256": str(index) * 64 if heads else None, "prompt_sha256": digest(prompt), "evidence_sha256": digest(view)}
        detail = {"status": "completed", "model": "qwen", "role": "neutral", "view": view, "prompt": prompt,
                  "context": {**context, "head_index": index}, **member}
        if heads:
            feature_id = "feature/" + str(index)
            operations.append({**detail, "operation_id": feature_id, "kind": "model_features", "adapter_sha256": None})
            member["feature_operation_id"] = feature_id
        operations.append({**detail, **member, "kind": "trained_readout" if heads else "model_score"})
        members.append(member)
    assessment = {"assessment_id": "aggregation", "arm": arm, "context": context, "view": view,
                  "evidence_sha256": digest(view), "score": 0.3, "members": members, "calibrated": False, "production_authority": "NONE"}
    operations.append({"operation_id": "aggregation", "kind": "score_aggregation", "status": "completed", **assessment})
    row = {"case_id": "unit-case", "arm": arm, "status": "completed", "risk": 0.3, "initial_assessment": assessment, "reached_step": 0}
    return [assessment], operations, [row]


class LedgerAuditTests(unittest.TestCase):
    def test_smoke_forward_cannot_replace_missing_policy_inference(self):
        assessments, operations, rows = inference_fixture()
        self.assertTrue(inference_bindings(assessments, operations, rows, []))
        smoke = copy.deepcopy(operations[0])
        smoke["context"] = {"split": "backend_check"}
        self.assertFalse(inference_bindings(assessments, [smoke, operations[1]], rows, []))
        self.assertFalse(inference_bindings(assessments, operations[1:], rows, []))

    def test_readout_needs_its_actual_feature_forward(self):
        assessments, operations, rows = inference_fixture(heads=True)
        self.assertTrue(inference_bindings(assessments, operations, rows, []))
        missing_feature = [op for op in operations if op["operation_id"] != "feature/1"]
        self.assertFalse(inference_bindings(assessments, missing_feature, rows, []))

    def test_missing_or_duplicate_decision_cannot_hide_policy_cost(self):
        assessments, operations, rows = inference_fixture()
        post = copy.deepcopy(assessments[0])
        post.update(assessment_id="post-assessment", view=public_view([True, True]))
        post["context"]["tick"] = 2
        post["evidence_sha256"] = digest(post["view"])
        member = post["members"][0]
        member.update(operation_id="post-model", prompt_sha256=digest("unit-post"), evidence_sha256=post["evidence_sha256"])
        model = {**copy.deepcopy(operations[0]), **member, "context": post["context"], "view": post["view"], "prompt": "unit-post"}
        operations += [model, {"operation_id": "post-assessment", "kind": "score_aggregation", "status": "completed", **post}]
        assessments.append(post)
        rows[0]["reached_step"] = 2
        decision = {**post["context"], "assessment_id": post["assessment_id"], "raw_model_score": 0.3,
                    "evidence_sha256": post["evidence_sha256"], "selection": "defer",
                    "matched_evidence_parent_sha256": digest({"view": post["view"], "model": "a" * 64, "prompts": [member["prompt_sha256"]]})}
        self.assertTrue(inference_bindings(assessments, operations, rows, [decision]))
        self.assertFalse(inference_bindings(assessments, operations, rows, []))
        self.assertFalse(inference_bindings(assessments, operations, rows, [decision, decision]))

    def test_duplicate_panel_cannot_replace_missing_case(self):
        plan = {"cases": {split: cases(split) for split in ("train", "calibration")}}
        labels, operations = [], []
        for split, roster in plan["cases"].items():
            for case in roster:
                context = {"split": split, "case_id": case["goal"]["task_id"], "attempt": split + "/panel"}
                label_id = "label/" + context["case_id"]
                labels.append({**context, "source_group": case["source_group"], "label": False, "all_three_effect_steps_completed": True, "label_operation_id": label_id})
                operations.append({"operation_id": label_id, "kind": "independent_outcome_label", "status": "completed", "context": context, "result": False})
                for tick in (1, 2, 3):
                    operations.append({"operation_id": context["case_id"] + "/" + str(tick), "kind": "host_effect", "status": "completed", "context": {**context, "tick": tick}, "result": {"replayed": False}})
        self.assertTrue(panel_bindings(labels, operations, plan))
        duplicated = [labels[0], labels[0]] + labels[2:]
        self.assertEqual(len(duplicated), 24)
        self.assertFalse(panel_bindings(duplicated, operations, plan))


if __name__ == "__main__":
    unittest.main()
