"""Negative controls: distinct generating commits cannot be pooled as one trial."""

from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from reader_dual_run_census import ORIGINAL, REPAIRED, checked_run, read_json, reconcile
from reader_external_artifact_audit import COHORTS, checked_metadata

PLAN = "9840a25487af444914dca24c818d98ff798ebc1610ea8dfdd827187c31ad1897"
PUBLIC = "31c6f191ecf62095779f7c9a5dd6c5b2f89c6ae408fe9c26f74e017a2d62c47a"


def pair(run_id, *, partial=False):
    source, _ = COHORTS[run_id]
    count = int(partial)
    outer = dict(
        schema="hepta.memory-cell.reader-external-artifact-audit.v1",
        expected_original_model_calls=80,
        generating_source_commit=source,
        generating_run_id=run_id,
        github_artifact_count=count,
        absent_artifact_count=16 - count,
        original_attempt_rows=count,
        original_succeeded_generation_rows=count,
        completed_original_journal_shards=0,
        github_outer_zip_sha256_verified=True,
        all_original_inner_sha256sums_verified=True,
        original_run_and_source_bound=True,
        original_model_task_score=None,
        parametric_learning_gain=None,
        new_model_calls_by_this_audit=0,
        production_accepted=False,
        dispositions=({"incomplete_original_journal": 1} if partial else {}),
        shards=[],
    )
    bound = dict(
        schema="hepta.memory-cell.reader-source-bound-original-receipts.v1",
        frozen_plan_sha256=PLAN,
        frozen_source_zip_sha256=PUBLIC,
        original_generating_commit=source,
        original_run_id=run_id,
        original_ground_truth_parsed=False,
        new_model_calls=0,
        reader_capacity_effect=None,
        learned_memory_gain_proven=False,
        independent_sufficiency_review=False,
        production_accepted=False,
        github_qualified_artifact_count=count,
        original_attempt_rows=count,
        source_bound_successful_generations=count,
        complete_five_arm_shards=0,
        eligible_source_bound_shards=count,
        source_bindings=[],
    )
    if partial:
        outer["shards"] = [
            dict(
                artifact_id=run_id,
                artifact_name="memory-reader-bottleneck-smol-1.7b-2",
                github_zip_sha256="a" * 64,
                tier="smol-1.7b",
                case_index=2,
                raw_attempt_rows=1,
                raw_success_rows=1,
                full_original_journal=False,
                outcome="incomplete_original_journal",
            )
        ]
        bound["source_bindings"] = [
            dict(
                artifact_id=run_id,
                github_zip_sha256="a" * 64,
                tier="smol-1.7b",
                case_index=2,
                rows=1,
                succeeded=1,
                full_original_pair=False,
                exact_source_bound=True,
            )
        ]
    return outer, bound


class TwoRunCensusTests(unittest.TestCase):
    def test_original_and_repaired_calls_stay_in_separate_ledgers(self):
        first, first_bound = pair(ORIGINAL, partial=True)
        second, second_bound = pair(REPAIRED)
        result = reconcile(first, first_bound, second, second_bound)
        self.assertEqual(result["original"]["successful_original_generations"], 1)
        self.assertEqual(result["repaired"]["successful_original_generations"], 0)
        self.assertIsNone(result["cross_commit_pairwise_model_task_scores"])
        self.assertFalse(result["concatenate_original_answer_journals"])
        self.assertFalse(result["production_accepted"])

    def test_empty_queue_has_no_invented_model_calls(self):
        first, first_bound = pair(ORIGINAL)
        second, second_bound = pair(REPAIRED)
        result = reconcile(first, first_bound, second, second_bound)
        self.assertEqual(result["original"]["observed_original_attempts"], 0)
        self.assertEqual(result["repaired"]["observed_original_attempts"], 0)

    def test_mixing_original_and_repaired_metadata_is_illegal(self):
        first, first_bound = pair(ORIGINAL, partial=True)
        second, second_bound = pair(REPAIRED)
        with self.assertRaisesRegex(ValueError, "unqualified"):
            reconcile(second, second_bound, first, first_bound)

    def test_both_generating_heads_exactly_registered_before_collection(self):
        for run_id, (source, branch) in COHORTS.items():
            with self.subTest(run_id=run_id):
                run = dict(
                    id=run_id,
                    head_sha=source,
                    head_branch=branch,
                    name="MemoryCell real Reader capacity and one-premise ablation",
                    event="push",
                    run_attempt=1,
                    repository={"full_name": "TrillionniumFoundation/hepta-private-ci"},
                    status="queued",
                )
                metadata = {"total_count": 0, "artifacts": []}
                self.assertEqual(
                    checked_metadata(run, metadata, run_id=run_id, source=source),
                    [],
                )
                spoofed = deepcopy(run)
                spoofed["head_branch"] = "main"
                with self.assertRaises(ValueError):
                    checked_metadata(spoofed, metadata, run_id=run_id, source=source)

    def test_repaired_run_cannot_use_an_alternative_commit(self):
        source, branch = COHORTS[REPAIRED]
        run = dict(
            id=REPAIRED,
            head_sha="f" * 40,
            head_branch=branch,
            name="MemoryCell real Reader capacity and one-premise ablation",
            event="push",
            run_attempt=1,
            repository={"full_name": "TrillionniumFoundation/hepta-private-ci"},
            status="queued",
        )
        with self.assertRaisesRegex(ValueError, "pinned source"):
            checked_metadata(
                run,
                {"total_count": 0, "artifacts": []},
                run_id=REPAIRED,
                source="f" * 40,
            )
        self.assertEqual(len(source), 40)

    def test_cross_source_zip_or_wrong_task_cannot_be_inserted(self):
        original, bound = pair(ORIGINAL, partial=True)
        for field in ("artifact_id", "github_zip_sha256", "case_index"):
            with self.subTest(field=field):
                altered = deepcopy(bound)
                if field == "artifact_id":
                    altered["source_bindings"][0][field] += 1
                elif field == "github_zip_sha256":
                    altered["source_bindings"][0][field] = "b" * 64
                else:
                    altered["source_bindings"][0][field] = 6
                with self.assertRaises(ValueError):
                    checked_run(original, altered, run_id=ORIGINAL)

    def test_succeeded_count_cannot_exceed_original_external_rows(self):
        original, bound = pair(ORIGINAL, partial=True)
        bound["source_bound_successful_generations"] = 5
        with self.assertRaisesRegex(ValueError, "does not reconcile"):
            checked_run(original, bound, run_id=ORIGINAL)

    def test_no_fake_human_review_or_model_parameter_gain(self):
        for field, value in (
            ("production_accepted", True),
            ("original_model_task_score", 1),
            ("parametric_learning_gain", 0.25),
        ):
            with self.subTest(field=field):
                original, bound = pair(REPAIRED)
                original[field] = value
                with self.assertRaisesRegex(ValueError, "unqualified"):
                    checked_run(original, bound, run_id=REPAIRED)

    def test_forged_disposition_census_is_rejected(self):
        outer, bound = pair(ORIGINAL, partial=True)
        outer["dispositions"] = {"hardware_ineligible": 1}
        with self.assertRaisesRegex(ValueError, "disposition census"):
            checked_run(outer, bound, run_id=ORIGINAL)

    def test_noninteger_call_counts_cannot_pass_as_boolean(self):
        outer, bound = pair(ORIGINAL, partial=True)
        outer["shards"][0]["raw_attempt_rows"] = True
        bound["source_bindings"][0]["rows"] = True
        with self.assertRaisesRegex(ValueError, "cross-run artifact"):
            checked_run(outer, bound, run_id=ORIGINAL)

    def test_duplicate_json_keys_and_nonfinite_source_receipts_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "original.json"
            for raw in (b'{"run":1,"run":2}', b'{"runtime":NaN}', b"[]"):
                with self.subTest(raw=raw):
                    path.write_bytes(raw)
                    with self.assertRaises(ValueError):
                        read_json(path)


if __name__ == "__main__":
    unittest.main()
