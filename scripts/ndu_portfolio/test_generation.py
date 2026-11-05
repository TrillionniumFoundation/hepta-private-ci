"""Transport/accounting/evaluator integration tests; all generated files are fixtures."""

from dataclasses import replace
from hashlib import sha256
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from .generation import (ActionLimit, JsonlCommand, Session, SyntheticFixtureProvider,
                         digest, verify_artifact)
from .evaluation import EvaluatorManifest, evaluate, panel_report


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        self.t += 0.125
        return self.t


class GenerationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.provider = SyntheticFixtureProvider()

    def session(self, **kwargs):
        args = dict(provider=self.provider, artifact_root=self.root, task_id="task", sample_id="sample",
                    seed=7, dataset_sha256=digest("dataset"), objective_sha256=digest("objective"),
                    budget_compute=10.0, budget_seconds=10.0, baseline="ndu", clock=FakeClock())
        args.update(kwargs)
        return Session(**args)

    def complete(self, session):
        for action in ("reason", "visual_repair", "cross_modal_check", "stop"):
            session.step(action, controller_seconds=0.05, controller_compute=0.1)
        return session

    def evaluator(self, request, timeout):
        self.assertNotIn("baseline", request)
        self.assertNotIn("critic_success_probability", request)
        self.assertNotIn("ndu", request)
        return {"request_sha256": request["request_sha256"],
                "evaluator_sha256": request["evaluator_sha256"], "compute_units": 0.5,
                "outcome": {"task_success": True, "quality": {"text": 0.9, "image": 0.8},
                            "contradictions": 0, "missing_modalities": []}}

    def manifest(self):
        return EvaluatorManifest("external-observer", "frozen-v1", digest("observer"),
                                 digest("rubric"), "synthetic_fixture")

    def score(self, session, **kwargs):
        args = dict(group_id="group", split="test", evaluation_compute_limit=1.0,
                    evaluation_timeout_seconds=1.0, critic_success_probability=0.8)
        args.update(kwargs)
        return evaluate(session, self.evaluator, self.manifest(), "controller", **args)

    def test_smoke_writes_verified_artifacts_and_never_certifies_generation(self):
        session = self.complete(self.session())
        result = session.evidence()
        self.assertEqual(set(result["artifacts"]), {"text", "image"})
        self.assertAlmostEqual(result["total_compute"], 3.4)
        self.assertAlmostEqual(result["total_seconds"], 0.575)
        self.assertEqual(result["status"], "HOLD")
        self.assertIn("synthetic_fixture_not_generation_evidence", result["reasons"])
        with self.assertRaises(ValueError):
            session.step("reason")

    def test_rejected_attempt_is_charged_for_controller(self):
        session = self.session(budget_compute=1.0)
        receipt = session.step("visual_repair", controller_seconds=0.1, controller_compute=0.2)
        self.assertEqual(receipt["status"], "rejected")
        self.assertEqual(receipt["reason"], "insufficient_dispatch_reservation")
        self.assertAlmostEqual(receipt["total_compute"], 0.2)
        self.assertEqual(session.artifacts, {})

    def test_unknown_provider_usage_consumes_reservation_and_cannot_pass(self):
        def fail(request, timeout):
            raise subprocess.TimeoutExpired("fixture", timeout)
        self.provider.generate = fail
        session = self.session()
        receipt = session.step("reason", controller_compute=0.2)
        self.assertEqual(receipt["provider_compute"], 2.0)
        self.assertEqual(receipt["usage_known"], False)
        self.assertAlmostEqual(session.spent_compute, 2.2)
        self.assertIn("unknown_usage_on_attempt", session.evidence()["reasons"])

    def test_frozen_model_revision_cannot_change_mid_run(self):
        session = self.session()
        self.provider.manifest = replace(self.provider.manifest, provider_id="changed")
        receipt = session.step("reason", controller_compute=0.1)
        self.assertEqual(receipt["reason"], "frozen_provider_manifest_changed")
        self.assertEqual(session.artifacts, {})

    def test_request_identity_substitution_is_rejected(self):
        original = self.provider.generate
        def substitute(request, timeout):
            response = original(request, timeout)
            response["request_sha256"] = digest("another request")
            return response
        self.provider.generate = substitute
        receipt = self.session().step("reason")
        self.assertEqual(receipt["status"], "failed")
        self.assertFalse(receipt["usage_known"])

    def test_corrupt_artifact_and_traversal_are_rejected(self):
        path = self.root / "image.png"
        path.write_bytes(b"this is not an image")
        item = {"path": "image.png", "modality": "image", "sha256": sha256(path.read_bytes()).hexdigest()}
        with self.assertRaises(OSError):
            verify_artifact(self.root, item)
        item["path"] = "../outside.txt"
        with self.assertRaises(ValueError):
            verify_artifact(self.root, item)

    def test_deadline_uses_measured_duration(self):
        session = self.session(budget_seconds=0.1)
        receipt = session.step("reason")
        self.assertEqual(receipt["reason"], "deadline_exceeded")
        self.assertIn("total_budget_exceeded", session.evidence()["reasons"])

    def test_missing_delivery_stops_as_failure(self):
        session = self.session()
        session.step("reason")
        receipt = session.step("stop")
        self.assertEqual(receipt["reason"], "missing_required_delivery")

    def test_evaluator_receives_artifacts_without_policy_score_and_cost_is_counted(self):
        row = self.score(self.complete(self.session()))
        self.assertEqual(row["status"], "HOLD")
        self.assertTrue(row["outcome"]["joint_success"])
        self.assertAlmostEqual(row["total_compute"], 3.9)
        self.assertAlmostEqual(row["total_seconds"], 0.7)
        self.assertIn("synthetic_evaluator_not_quality_evidence", row["reasons"])

    def test_evaluator_identity_separation_is_required(self):
        session = self.complete(self.session())
        with self.assertRaises(ValueError):
            evaluate(session, self.evaluator, self.manifest(), "external-observer", group_id="g",
                     split="test", evaluation_compute_limit=1.0, evaluation_timeout_seconds=1.0)

    def test_artifacts_are_rechecked_at_scoring_boundary(self):
        session = self.complete(self.session())
        (self.root / session.artifacts["text"]["path"]).write_text("changed content")
        row = self.score(session)
        self.assertIsNone(row["outcome"])
        self.assertIn("independent_evaluation_failed:ValueError", row["reasons"])
        self.assertEqual(row["evaluation_compute"], 1.0)

    def test_missing_baselines_and_training_overlap_cannot_pass_panel(self):
        row = self.score(self.complete(self.session()))
        report = panel_report([row], [("task", "sample", 7, "test")], training_group_ids=["group"])
        self.assertEqual(report["status"], "HOLD")
        self.assertIn("incomplete_baseline:ordinary_router", report["reasons"])
        self.assertIn("training_evaluation_group_overlap", report["reasons"])
        self.assertEqual(report["ndu_necessity"], "NOT_ESTABLISHED")

    def test_duplicate_case_cannot_inflate_sample_count(self):
        row = self.score(self.complete(self.session()))
        with self.assertRaises(ValueError):
            panel_report([row, row], [("task", "sample", 7, "test")])

    def test_subprocess_jsonl_protocol_and_limits(self):
        command = JsonlCommand([sys.executable, "-c", "import sys,json; print(json.dumps(json.loads(sys.stdin.readline())))"])
        self.assertEqual(command({"request": "x"}, 2.0), {"request": "x"})
        oversized = JsonlCommand([sys.executable, "-c", "print('x'*80)"], response_limit=50)
        with self.assertRaises(ValueError):
            oversized({}, 2.0)
        multiple = JsonlCommand([sys.executable, "-c", "print('{}');print('{}')"])
        with self.assertRaises(ValueError):
            multiple({}, 2.0)

    def test_evaluator_timeout_is_charged_and_recorded(self):
        session = self.complete(self.session())
        def timeout(request, seconds):
            raise subprocess.TimeoutExpired("evaluator", seconds)
        row = evaluate(session, timeout, self.manifest(), "controller", group_id="g", split="test",
                       evaluation_compute_limit=1.0, evaluation_timeout_seconds=1.0)
        self.assertEqual(row["status"], "HOLD")
        self.assertEqual(row["evaluation_compute"], 1.0)
        self.assertIn("independent_evaluation_failed:TimeoutExpired", row["reasons"])

    def test_substituted_evaluator_and_budget_mismatch_fail_closed(self):
        row = self.score(self.complete(self.session()))
        alternative = dict(row, baseline="fixed", budget_compute=20.0)
        report = panel_report([row, alternative], [("task", "sample", 7, "test")],
                              required_baselines=("ndu", "fixed"))
        self.assertIn("unmatched_case_bindings", report["reasons"])
        self.assertEqual(report["status"], "HOLD")

    def test_evaluation_attempt_is_single_use_and_cost_persists(self):
        session = self.complete(self.session())
        row = self.score(session)
        totals = (session.spent_compute, session.spent_seconds)
        self.assertEqual(totals, (row["total_compute"], row["total_seconds"]))
        self.assertEqual(session.evaluation_receipt["compute"], 0.5)
        with self.assertRaisesRegex(ValueError, "evaluation already attempted"):
            self.score(session)
        self.assertEqual((session.spent_compute, session.spent_seconds), totals)

    def test_failed_evaluation_is_also_single_use(self):
        session = self.complete(self.session())
        def timeout(request, seconds):
            raise subprocess.TimeoutExpired("evaluator", seconds)
        row = evaluate(session, timeout, self.manifest(), "controller", group_id="g", split="test",
                       evaluation_compute_limit=1.0, evaluation_timeout_seconds=1.0)
        self.assertAlmostEqual(session.spent_compute, 4.4)
        self.assertEqual(session.evaluation_receipt["status"], "HOLD")
        with self.assertRaisesRegex(ValueError, "evaluation already attempted"):
            self.score(session)
        self.assertEqual(session.spent_compute, row["total_compute"])

    def test_insufficient_evaluator_reservation_cannot_be_retried(self):
        session = self.complete(self.session(budget_compute=5.0))
        row = self.score(session, evaluation_compute_limit=2.0)
        self.assertIn("insufficient_evaluator_reservation", row["reasons"])
        self.assertEqual(row["evaluation_compute"], 0.0)
        with self.assertRaisesRegex(ValueError, "evaluation already attempted"):
            self.score(session, evaluation_compute_limit=0.5)

    def test_missing_and_failed_outcomes_preserve_registered_denominator(self):
        first = self.score(self.complete(self.session()), group_id="g1")
        failed_session = self.complete(self.session(sample_id="failed", artifact_root=self.root / "failed"))
        def timeout(request, seconds):
            raise subprocess.TimeoutExpired("evaluator", seconds)
        failed = evaluate(failed_session, timeout, self.manifest(), "controller", group_id="g2", split="test",
                          evaluation_compute_limit=1.0, evaluation_timeout_seconds=1.0)
        expected = [("task", "sample", 7, "test"), ("task", "failed", 7, "test"),
                    ("task", "missing", 7, "test")]
        report = panel_report([first, failed], expected, required_baselines=("ndu",))
        summary = report["baselines"]["ndu"]["test"]
        self.assertEqual((summary["n_expected"], summary["n_received"], summary["n_observed_outcomes"],
                          summary["n_missing_outcomes"]), (3, 2, 1, 2))
        self.assertEqual(summary["outcome_coverage"], 1 / 3)
        self.assertEqual(summary["all_case_joint_success_rate_lower_bound"], 1 / 3)
        self.assertIsNone(summary["joint_success_rate"])
        self.assertIsNone(summary["wilson_95"])
        self.assertEqual(summary["observed_only_mean_quality"], {"text": 0.9, "image": 0.8})
        self.assertNotIn("mean_quality", summary)
        self.assertAlmostEqual(summary["recorded_only_mean_total_compute"], 4.15)
        without_failed = panel_report([first], expected, required_baselines=("ndu",))
        self.assertEqual(without_failed["baselines"]["ndu"]["test"]["all_case_joint_success_rate_lower_bound"], 1 / 3)
        self.assertEqual(report["status"], "HOLD")

    def test_missing_split_has_zero_coverage_and_optional_group_gate(self):
        row = self.score(self.complete(self.session()))
        expected = [("task", "sample", 7, "test"), ("task", "future", 7, "ood")]
        report = panel_report([row], expected, required_baselines=("ndu",), minimum_independent_test_groups=100)
        self.assertEqual(report["expected_cases_per_split"], {"ood": 1, "test": 1})
        missing = report["baselines"]["ndu"]["ood"]
        self.assertEqual(missing["outcome_coverage"], 0.0)
        self.assertEqual(missing["all_case_joint_success_rate_lower_bound"], 0.0)
        self.assertIsNone(missing["observed_only_mean_quality"])
        self.assertIn("insufficient_independent_test_task_groups", report["reasons"])
        self.assertEqual(report["minimum_independent_test_groups"], 100)
        self.assertEqual(report["ndu_necessity"], "NOT_ESTABLISHED")

    def test_actual_provider_overrun_is_preserved_and_blocks_dispatch(self):
        original = self.provider.generate
        def overrun(request, seconds):
            response = original(request, seconds)
            response["compute_units"] = 5.0
            return response
        self.provider.generate = overrun
        session = self.session(budget_compute=4.0)
        receipt = session.step("reason")
        self.assertEqual(receipt["provider_compute"], 5.0)
        self.assertEqual(receipt["total_compute"], 5.0)
        self.assertEqual(receipt["reason"], "provider_reservation_exceeded")
        self.assertTrue(receipt["usage_known"])
        self.assertEqual(session.artifacts, {})
        blocked = session.step("reason")
        self.assertEqual(blocked["reason"], "controller_budget_exhausted")

    def test_actual_evaluator_overrun_is_preserved(self):
        session = self.complete(self.session())
        def overrun(request, seconds):
            response = self.evaluator(request, seconds)
            response["compute_units"] = 20.0
            return response
        row = evaluate(session, overrun, self.manifest(), "controller", group_id="g", split="test",
                       evaluation_compute_limit=1.0, evaluation_timeout_seconds=1.0)
        self.assertEqual(row["evaluation_compute"], 20.0)
        self.assertAlmostEqual(row["total_compute"], 23.4)
        self.assertAlmostEqual(session.spent_compute, 23.4)
        self.assertIn("evaluator_reservation_exceeded", row["reasons"])
        self.assertIsNone(row["outcome"])

    def test_late_failed_action_does_not_replace_active_artifacts(self):
        session = self.session(budget_seconds=30.0)
        session.step("reason")
        before = session.artifacts.copy()
        clock_values = iter((5.0, 11.0))
        session.clock = lambda: next(clock_values)
        receipt = session.step("reason")
        self.assertEqual(receipt["reason"], "action_deadline_exceeded")
        self.assertEqual(receipt["status"], "failed")
        self.assertEqual(session.artifacts, before)

    def test_controller_usage_is_not_invented_from_defaults(self):
        session = self.session()
        receipt = session.step("reason")
        self.assertEqual(receipt["controller_usage_source"], "unavailable")
        self.assertIn("controller_usage_not_measured", session.evidence()["reasons"])

    def test_relabelling_fixture_as_real_does_not_verify_provenance(self):
        self.provider.manifest = replace(self.provider.manifest, evidence_kind="real")
        session = self.session()
        for action in ("reason", "visual_repair", "stop"):
            session.step(action, controller_seconds=0.05, controller_compute=0.1,
                         controller_usage_source="measured")
        manifest = replace(self.manifest(), evidence_kind="real")
        row = evaluate(session, self.evaluator, manifest, "controller", group_id="g", split="test",
                       evaluation_compute_limit=1.0, evaluation_timeout_seconds=1.0)
        self.assertEqual(row["status"], "HOLD")
        self.assertIn("real_backend_execution_provenance_unverified", row["reasons"])
        self.assertIn("independent_evaluator_provenance_unverified", row["reasons"])
        self.assertEqual(row["execution_provenance"], "DECLARED_UNVERIFIED")

    def test_nonfinite_usage_and_invalid_seed_are_rejected(self):
        with self.assertRaises(ValueError):
            self.session(seed=None)
        with self.assertRaises(ValueError):
            ActionLimit(float("nan"), 1.0)
        with self.assertRaises(ValueError):
            self.session().step("reason", controller_compute=float("nan"))


if __name__ == "__main__":
    unittest.main()
