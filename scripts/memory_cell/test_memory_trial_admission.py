"""Structural fixtures only: synthetic records never count as new model evidence."""
import hashlib
import unittest

from factorial_evidence_gate import ARMS, CONDITIONS, READERS, TASKS, COST_KEYS, sha
from memory_trial_admission import admit


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def fixture():
    cases = [dict(id=f"case-{i}", root=f"family-{i // 2}", task=TASKS[i],
                  answer_sha256=digest(f"gold-{i}"), oracle_source_sha256=digest(f"oracle-{i}"),
                  premise_sha256=digest(f"premise-{i}"), write_snapshot_sha256=digest(f"write-{i}"),
                  write_completed_at="2026-10-14T02:00:00Z",
                  task_revealed_at="2026-10-15T02:00:00Z") for i in range(4)]
    snapshots = {arm: dict(sha256=digest(arm), frozen_at="2026-10-14T06:00:00Z")
                 for arm in ARMS}
    for arm in ("learned_read", "knowledge", "knowledge_only"):
        snapshots[arm].update(train_steps=3, training_source_sha256=digest(f"training-{arm}"))
    snapshots["knowledge_only"]["sha256"] = snapshots["knowledge"]["sha256"]
    plan = dict(schema="hepta.memory-factorial.plan.v1", conditions=list(CONDITIONS),
                readers=list(READERS), arms=list(ARMS), tasks=list(TASKS),
                cutoff="2026-10-14T00:00:00Z", reader_revisions={"frozen": "frozen-v1",
                    "reference": "reference-v1"},
                prompt_template_sha256=digest("prompt-template"),
                tool_policy_sha256=digest("same-tools"),
                reader_budget={"total_tokens": 1024}, registered_before_exposure=True,
                tool_permissions_equal=True, arm_snapshots=snapshots, cases=cases)
    raw, scored = [], []
    for case in cases:
        for arm in ARMS:
            for condition in CONDITIONS:
                for reader in READERS:
                    if condition == "none" or arm == "knowledge_only":
                        source = hashlib.sha256(b"").hexdigest()
                        size = 0
                    elif arm in ("event_graph", "knowledge") and condition == "hybrid":
                        source = digest(f"organized-{case['id']}")
                        size = 51
                    else:
                        source = digest(f"{condition}-{arm}-{case['id']}")
                        size = 47
                    text = f"real-model-output-{case['id']}-{arm}-{reader}-{condition}"
                    common = dict(id=case["id"], root=case["root"], arm=arm,
                                  reader=reader, condition=condition,
                                  reader_revision=plan["reader_revisions"][reader],
                                  prompt_digest=plan["prompt_template_sha256"],
                                  tool_policy_sha256=plan["tool_policy_sha256"],
                                  write_snapshot_sha256=case["write_snapshot_sha256"],
                                  memory_state_sha256=plan["arm_snapshots"][arm]["sha256"],
                                  source_digest=source, raw_source_bytes=size,
                                  tokens=500, generated_tokens=20)
                    original = dict(common, answer=text, status="succeeded",
                                    model_call_id=f"{case['id']}|{arm}|{reader}|{condition}")
                    observation = dict(common, plan_sha256=sha(plan),
                                       answer_digest=digest(text),
                                       verified=True, success=condition == "oracle",
                                       cost={k: (1.0 if k == "query" else 0.0) for k in COST_KEYS},
                                       diagnostic_count=1, recovery_success=False)
                    if case["task"] == "program":
                        original["tool_trace_sha256"] = digest(text + "-executed")
                        observation.update(tool_trace_sha256=original["tool_trace_sha256"],
                                           program_exit_code=0, program_test_count=3,
                                           program_tests_passed=3)
                    raw.append(original)
                    scored.append(observation)
    return plan, raw, scored


class AdmissionTest(unittest.TestCase):
    def verify(self, plan, raw, scored):
        return admit(plan, raw, scored, plan_pin=sha(plan), original_pin=sha(raw))

    def test_complete_census_and_conservative_status(self):
        plan, raw, scored = fixture()
        result = self.verify(plan, raw, scored)
        self.assertEqual(result["original_attempts"], 160)
        self.assertEqual(result["paired_source_root_comparisons"]["organization_vs_hybrid"]["ties"], 4)
        self.assertTrue(result["knowledge_same_evidence_comparable"])
        self.assertIsNone(result["amortized_tco"])
        self.assertFalse(result["production_qualified"])
        self.assertFalse(result["independent_human_oracle_certified"])

    def test_wrong_external_plan_pin(self):
        plan, raw, scored = fixture()
        with self.assertRaisesRegex(ValueError, "preregistration pin"):
            admit(plan, raw, scored, plan_pin="0" * 64, original_pin=sha(raw))

    def test_tampered_original_answer(self):
        plan, raw, scored = fixture()
        raw[0]["answer"] = "injected answer after scoring"
        with self.assertRaisesRegex(ValueError, "scored answer differs"):
            self.verify(plan, raw, scored)

    def test_missing_original_attempt(self):
        plan, raw, scored = fixture()
        with self.assertRaisesRegex(ValueError, "incomplete original"):
            self.verify(plan, raw[:-1], scored)

    def test_wrong_reference_evidence(self):
        plan, raw, scored = fixture()
        i = next(i for i, r in enumerate(raw) if r["reader"] == "reference" and r["condition"] == "oracle")
        raw[i]["source_digest"] = scored[i]["source_digest"] = digest("different-reader-source")
        with self.assertRaisesRegex(ValueError, "different evidence"):
            self.verify(plan, raw, scored)

    def test_knowledge_only_raw_source_leak(self):
        plan, raw, scored = fixture()
        i = next(i for i, r in enumerate(raw) if r["arm"] == "knowledge_only")
        raw[i]["raw_source_bytes"] = scored[i]["raw_source_bytes"] = 1
        with self.assertRaisesRegex(ValueError, "leaked raw source"):
            self.verify(plan, raw, scored)

    def test_post_task_training(self):
        plan, raw, scored = fixture()
        plan["arm_snapshots"]["learned_read"]["frozen_at"] = "2026-10-16T00:00:00Z"
        with self.assertRaisesRegex(ValueError, "after task exposure"):
            self.verify(plan, raw, scored)

    def test_changed_tool_permissions(self):
        plan, raw, scored = fixture()
        raw[0]["tool_policy_sha256"] = scored[0]["tool_policy_sha256"] = digest("weaker-baseline-tools")
        with self.assertRaisesRegex(ValueError, "tool permission"):
            self.verify(plan, raw, scored)

    def test_false_program_success(self):
        plan, raw, scored = fixture()
        i = next(i for i, r in enumerate(scored) if r["id"] == "case-3" and r["success"])
        scored[i]["program_tests_passed"] = 2
        with self.assertRaisesRegex(ValueError, "text-only program"):
            self.verify(plan, raw, scored)

    def test_mismatched_knowledge_evidence_is_not_attributed(self):
        plan, raw, scored = fixture()
        idxs = [i for i, r in enumerate(scored) if r["arm"] == "knowledge"
                and r["id"] == "case-0" and r["condition"] == "hybrid"]
        for i in idxs:
            raw[i]["source_digest"] = scored[i]["source_digest"] = digest("other-knowledge-evidence")
        report = self.verify(plan, raw, scored)
        self.assertEqual(report["knowledge_evidence_mismatch_case_ids"], ["case-0"])
        self.assertFalse(report["knowledge_same_evidence_comparable"])
        self.assertEqual(report["stage_gates"]["parametric_knowledge"], "evidence_confounded")


if __name__ == "__main__":
    unittest.main()
