"""Recovery-origin fixtures never count as real models, reviews or run results."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import five_causal_experiments as c
import question_relevance_trial as training
import relevance_recovery as recovery
import select_question_relevance_trial as trial
import select_recovery_origin as origin
import test_relevance_recovery as fixture


def metadata():
    run = {"id": origin.RECOVERY_RUN, "head_sha": origin.RECOVERY_SOURCE,
           "path": origin.RECOVERY_WORKFLOW, "run_attempt": 1,
           "repository": {"full_name": origin.REPOSITORY},
           "head_repository": {"full_name": origin.REPOSITORY},
           "status": "completed", "conclusion": "success"}
    artifacts = {"total_count": 1, "artifacts": [
        {"id": 123, "name": origin.ARTIFACT_NAME, "expired": False,
         "size_in_bytes": 100, "digest": "sha256:" + "a" * 64,
         "workflow_run": {"id": origin.RECOVERY_RUN, "head_sha": origin.RECOVERY_SOURCE}}]}
    return run, artifacts


def rewrite(path, value):
    Path(path).write_bytes(c.canonical(value) + b"\n")


def reseal(root):
    """Fixture-only rehash: tests exercise invariants beyond an outer ZIP hash."""
    root = Path(root); study = root / "study"
    m = c.load(root / "recovery-manifest.json")
    m["file_hashes"] = {p.relative_to(study).as_posix(): c.file_sha(p)
                        for p in sorted(study.rglob("*")) if p.is_file() and p.name != "report.json"}
    rewrite(root / "recovery-manifest.json", m)
    report = c.load(study / "report.json")
    report["recovery_manifest_sha256"] = c.digest(m)
    rewrite(study / "report.json", report)


def completed_fixture(root):
    root = Path(root); study = root / "study"
    (root / "source").mkdir(parents=True)
    (root / "source/tested-commit.txt").write_text(origin.RECOVERY_SOURCE)
    c.write_new(study / "plan.json", training.PLAN | {"training": {"fixture_only": True}})
    c.write_new(study / "public-inputs.json", fixture.cases())
    c.write_new(study / "train-plan.json", {"fixture_only": True})
    c.write_new(study / "train-compilation.json", {"fixture_only": True})
    all_raw, cancelled, restarted, summaries = [], [], [], {}
    for arm in origin.protocol.ARMS:
        raw, events = fixture.arm_files(study, arm)
        all_raw.extend(raw)
        if arm == recovery.RESTART: restarted.extend(events)
        else: cancelled.extend(events)
        summaries[arm] = {"model_integrity_verified": True,
            "training": c.load(study / arm / "training-receipt.json") if arm != "frozen_reader" else None,
            "origin": "restarted_from_base" if arm == recovery.RESTART else "verified_cancelled_artifact_completed_arm",
            "integrity_basis": "fresh_strict_saved_checkpoint_reload_no_new_generation",
            "historical_in_memory_integrity_receipt_available": arm == recovery.RESTART}
    c.write_new(study / "raw-answers.json", all_raw)
    fixture.journal(root / "provenance/cancelled-events.jsonl", cancelled)
    fixture.journal(root / "restarted/events.jsonl", restarted)
    interrupted_rows = fixture.optim_rows()[:163]
    fixture.journal(root / "provenance/interrupted-optimizer.jsonl", interrupted_rows)
    m = {"schema": recovery.PROFILE, "execution_source": origin.RECOVERY_SOURCE,
         "original_source": recovery.CANCELLED_SOURCE, "original_run": recovery.CANCELLED_RUN,
         "original_status": "cancelled", "original_artifact": recovery.CANCELLED_ARTIFACT,
         "original_artifact_sha256": recovery.CANCELLED_SHA,
         "reused_arms": list(recovery.REUSE), "restarted_arms": [recovery.RESTART],
         "optimizer_state_resumed": False, "original_failure_relabelled": False,
         "interrupted_work": recovery.optimizer_census(interrupted_rows),
         "scientific_plan_sha256": c.digest(c.load(study / "plan.json")),
         "production_accepted": False, "file_hashes": {}}
    c.write_new(root / "recovery-manifest.json", m)
    report = {"schema": recovery.PROFILE + ".result", "errors": [], "arms": summaries,
        "plan_sha256": m["scientific_plan_sha256"], "recovery_manifest_sha256": c.digest(m),
        "raw_sha256": c.file_sha(study / "raw-answers.json"), "planned_rows": 112,
        "successful_model_calls_across_origins": 108, "new_generation_calls": 27,
        "reused_generation_calls": 81, "new_optimizer_updates": 112, "new_training_forwards": 864,
        "old_interrupted_cost_is_additional": True, "reader_adequacy_established": False,
        "independent_confirmation": False, "production_accepted": False, "five_experiments_completed": False}
    c.write_new(study / "report.json", report)
    reseal(root)
    return root


class MetadataTests(unittest.TestCase):
    def test_exact_success_selects_one_external_digest(self):
        result = origin.select_completed_artifact(*metadata())
        self.assertTrue(result["ready"])
        self.assertEqual(result["artifact_sha256"], "a" * 64)
        self.assertEqual(result["original_status"], "cancelled")
        self.assertFalse(result["model_execution_completed"])

    def test_pending_cancelled_and_failed_are_not_model_success(self):
        for status, conclusion in (("queued", None), ("in_progress", None),
                                   ("completed", "cancelled"), ("completed", "failure")):
            run, artifacts = metadata(); run.update(status=status, conclusion=conclusion)
            result = origin.select_completed_artifact(run, artifacts)
            self.assertFalse(result["ready"]); self.assertIsNone(result["artifact_id"])

    def test_wrong_source_run_and_workflow_fail(self):
        for key, value in (("head_sha", "b" * 40), ("id", 1), ("path", ".github/workflows/other.yml")):
            run, artifacts = metadata(); run[key] = value
            with self.assertRaises(c.Invalid): origin.select_completed_artifact(run, artifacts)

    def test_wrong_repository_and_missing_attempt_fail(self):
        for key in ("repository", "head_repository", "run_attempt"):
            run, artifacts = metadata(); run[key] = None if key == "run_attempt" else {"full_name": "other/repo"}
            with self.assertRaises(c.Invalid): origin.select_completed_artifact(run, artifacts)

    def test_missing_duplicate_or_wrong_name_is_not_fallback(self):
        for mode in ("missing", "duplicate", "name"):
            run, a = metadata()
            if mode == "missing": a.update(total_count=0, artifacts=[])
            elif mode == "duplicate": a["artifacts"].append(deepcopy(a["artifacts"][0])); a["total_count"] = 2
            else: a["artifacts"][0]["name"] = "older-success"
            with self.assertRaises(c.Invalid): origin.select_completed_artifact(run, a)

    def test_incomplete_page_fails(self):
        run, a = metadata(); a["total_count"] = 101
        with self.assertRaises(c.Invalid): origin.select_completed_artifact(run, a)

    def test_digest_expiry_and_boolean_identity_fail(self):
        for key, value in (("digest", None), ("digest", "sha256:no"), ("expired", True),
                           ("id", True), ("size_in_bytes", 0)):
            run, a = metadata(); a["artifacts"][0][key] = value
            with self.assertRaises(c.Invalid): origin.select_completed_artifact(run, a)

    def test_artifact_run_binding_is_required(self):
        run, a = metadata(); a["artifacts"][0]["workflow_run"]["head_sha"] = "b" * 40
        with self.assertRaises(c.Invalid): origin.select_completed_artifact(run, a)

    def test_metadata_not_mutated(self):
        run, a = metadata(); before = c.digest([run, a])
        origin.select_completed_artifact(run, a)
        self.assertEqual(c.digest([run, a]), before)

    def test_cli_writes_deferred_receipt_with_nonzero_exit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); run, a = metadata(); run["status"] = "queued"; run["conclusion"] = None
            c.write_new(root / "run.json", run); c.write_new(root / "artifacts.json", a)
            result = origin.main(["--run-json", str(root / "run.json"), "--artifacts-json", str(root / "artifacts.json"), "--output", str(root / "out.json")])
            self.assertEqual(result, 3); self.assertFalse(c.load(root / "out.json")["ready"])


class MaterialTests(unittest.TestCase):
    def test_complete_recovery_keeps_all_112_slots_and_three_origins(self):
        with tempfile.TemporaryDirectory() as d:
            root = completed_fixture(d)
            study, report, cases, joined = origin.validate_recovery_training(root, origin.RECOVERY_SOURCE)
            self.assertEqual(len(cases), 28); self.assertEqual(report["planned_rows"], 112)
            self.assertEqual(set(joined), set(origin.protocol.ARMS))
            self.assertEqual(len(c.load(study / "raw-answers.json")), 112)

    def reject_change(self, filename, mutate, *, seal=True):
        with tempfile.TemporaryDirectory() as d:
            root = completed_fixture(d); p = root / filename
            value = c.load(p); mutate(value); rewrite(p, value)
            if seal: reseal(root)
            with self.assertRaises((c.Invalid, KeyError, ValueError)):
                origin.validate_recovery_training(root, origin.RECOVERY_SOURCE)

    def test_wrong_execution_source_rejected(self):
        self.reject_change("recovery-manifest.json", lambda x: x.update(execution_source="c" * 40))

    def test_original_cancelled_status_cannot_be_changed(self):
        self.reject_change("recovery-manifest.json", lambda x: x.update(original_status="success"))

    def test_wrong_original_artifact_rejected(self):
        self.reject_change("recovery-manifest.json", lambda x: x.update(original_artifact=1))

    def test_omitted_or_false_work_is_not_free_reuse(self):
        for key, value in (("new_optimizer_updates", 0), ("new_generation_calls", 108),
                           ("reused_generation_calls", 0), ("old_interrupted_cost_is_additional", False)):
            self.reject_change("study/report.json", lambda x, k=key, v=value: x.update({k: v}))

    def test_unknown_interrupted_tail_preserved(self):
        with tempfile.TemporaryDirectory() as d:
            root = completed_fixture(d); origin.validate_recovery_training(root, origin.RECOVERY_SOURCE)
            receipt = origin.origin_receipt(root)
            self.assertEqual(receipt["interrupted_work"]["completed_updates"], 81)
            self.assertTrue(receipt["interrupted_work"]["unobserved_tail_cost_unknown"])
            self.assertEqual(receipt["new_followthrough_optimizer_updates"], 0)

    def test_interrupted_journal_must_match_manifest(self):
        self.reject_change("recovery-manifest.json", lambda x: x["interrupted_work"].update(completed_updates=0))

    def test_historical_integrity_cannot_be_invented(self):
        self.reject_change("study/report.json", lambda x: x["arms"]["repeat_empty"].update(historical_in_memory_integrity_receipt_available=True))

    def test_origin_label_cannot_be_swapped(self):
        self.reject_change("study/report.json", lambda x: x["arms"]["repeat_empty"].update(origin="restarted_from_base"))

    def test_raw_seal_is_checked_even_when_new_manifest_is_pinned(self):
        self.reject_change("study/repeat_empty-raw-seal.json", lambda x: x.update(sha256="c" * 64))

    def test_exact_raw_journal_join_cannot_be_replaced_by_summary(self):
        with tempfile.TemporaryDirectory() as d:
            root = completed_fixture(d); p = root / "provenance/cancelled-events.jsonl"
            rows = recovery.read_chain(p); rows[0]["answer"] = "other output"; p.unlink(); fixture.journal(p, rows)
            with self.assertRaises(c.Invalid): origin.validate_recovery_training(root, origin.RECOVERY_SOURCE)

    def test_failure_markers_block_recovery(self):
        for name in ("failure.json", "restarted/failure.json"):
            with tempfile.TemporaryDirectory() as d:
                root = completed_fixture(d); c.write_new(root / name, {"failed": True})
                with self.assertRaises(c.Invalid): origin.validate_recovery_training(root, origin.RECOVERY_SOURCE)

    def test_no_production_or_reader_qualification(self):
        self.reject_change("study/report.json", lambda x: x.update(reader_adequacy_established=True))

    def test_missing_original_denominator_cannot_be_silently_removed(self):
        self.reject_change("study/public-inputs.json", lambda x: x.pop())

    def test_legacy_default_does_not_accept_new_recovery(self):
        with tempfile.TemporaryDirectory() as d:
            root = completed_fixture(d)
            with self.assertRaises(c.Invalid): trial.load_training_origin(root)
            self.assertEqual(trial.load_training_origin(root, origin.RECOVERY_SOURCE)[1]["planned_rows"], 112)


class PlanTests(unittest.TestCase):
    def test_legacy_configuration_stays_byte_identical(self):
        expected = trial.PLAN | {"training_archive_sha256": "a" * 64, "original_archive_sha256": "b" * 64}
        self.assertEqual(c.canonical(origin.execution_plan(trial.PLAN, "a" * 64, "b" * 64)), c.canonical(expected))

    def test_new_origin_has_distinct_schema_and_preserves_scientific_inputs(self):
        before = c.digest(trial.PLAN)
        config = origin.execution_plan(trial.PLAN, "a" * 64, "b" * 64, origin.RECOVERY_SOURCE)
        self.assertNotEqual(config["schema"], trial.PLAN["schema"])
        self.assertEqual(config["original_training_status"], "cancelled")
        for k in ("arms", "profile", "select_archive_sha256", "maximum_input_tokens", "maximum_output_tokens", "vocabulary_projection", "new_optimizer_updates"):
            self.assertEqual(config[k], trial.PLAN[k])
        self.assertEqual(c.digest(trial.PLAN), before)

    def test_unknown_source_rejected_before_model_import_or_output(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "unused"
            with self.assertRaises(c.Invalid): trial.run(None, None, "a" * 64, None, None, out, recovery_source="latest")
            self.assertFalse(out.exists())

    def test_external_archive_pin_is_still_mandatory(self):
        with self.assertRaises(c.Invalid): origin.execution_plan(trial.PLAN, None, "a" * 64, origin.RECOVERY_SOURCE)

    def test_default_validation_has_no_recovery_fallback(self):
        with patch.object(trial, "validate_training", side_effect=c.Invalid("old failure")) as old:
            with patch.object(origin, "validate_recovery_training") as new:
                with self.assertRaises(c.Invalid): trial.load_training_origin(Path("unused"))
                old.assert_called_once(); new.assert_not_called()


if __name__ == "__main__":
    unittest.main()
