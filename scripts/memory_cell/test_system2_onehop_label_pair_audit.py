"""Model-free audit tests: all paired outcomes, unknowns, origins, tampering."""

from __future__ import annotations

from dataclasses import asdict
import hashlib
import os
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from system2_multihop_evidence import digest
from system2_multihop_trial import evidence
from system2_onehop_label_ablation import (
    ABSTAIN,
    ALL_ARMS,
    PARENT_SHA256,
    READER_IDENTITY,
    cases,
    load_previous,
    score,
    selected,
)
from system2_onehop_label_pair_audit import (
    audit,
    compare_pairs,
    exact_two_sided_discordance_p,
)

COMMIT = "a" * 40


def fixture(folder):
    folder.mkdir()
    all_rows = []
    all_cases = cases()
    for idx, case in enumerate(all_cases):
        for arm, mode in ALL_ARMS:
            docs = selected(case, arm)
            bundle, _, _ = evidence(case, docs, "answer-only:" + arm)
            if arm == "no_evidence":
                text = ABSTAIN
            elif arm == "decoy_one":
                text = ABSTAIN if mode == "unlabeled" and idx < 14 else "E1"
            elif arm == "single_fact":
                text = case.answer if (mode == "unlabeled" or idx < 4) else "E1"
            elif arm == "target_decoy_two_first":
                text = (
                    case.answer
                    if (
                        mode == "unlabeled"
                        and idx < 16
                        or mode == "labeled"
                        and idx < 2
                    )
                    else "E1 E2"
                )
            else:
                raise AssertionError("unexpected")
            rec = dict(
                reader_identity=READER_IDENTITY,
                reader_profile=digest(("profile", mode)),
                query_digest=digest(asdict(case.question)),
                bundle_digest=bundle.seal(),
                delivered_evidence=bundle.delivered(),
                answer_postprocessed=False,
                trainable_parameters=0,
                token_limit=1024,
                input_tokens=70 + len(docs) * 20 + (5 if mode == "labeled" else 0),
                generated_tokens=6,
                input_ids_digest=digest(("input", arm, idx, mode)),
                generated_ids_digest=digest(("response", text, idx, arm, mode)),
            )
            all_rows.append(
                dict(
                    qid=case.question.identity,
                    arm=arm,
                    presentation=mode,
                    status="succeeded",
                    answer=text,
                    selected=[d.identity for d in docs],
                    reader=rec,
                )
            )
    assert len(all_rows) == 140
    (folder / "starts.jsonl").write_text(
        "".join(
            json.dumps(
                dict(
                    qid=r["qid"],
                    arm=r["arm"],
                    presentation=r["presentation"],
                    status="started",
                )
            )
            + "\n"
            for r in all_rows
        )
    )
    data = b"".join((json.dumps(r, sort_keys=True) + "\n").encode() for r in all_rows)
    rawsha = hashlib.sha256(data).hexdigest()
    (folder / "raw-answers.jsonl").write_bytes(data)
    (folder / "raw-seal.json").write_text(
        json.dumps(dict(sha256=rawsha, rows=140, scoring_started=False))
    )
    scores, groups = score(all_rows, all_cases)
    (folder / "scored.json").write_text(json.dumps(scores))
    idx = {(g["arm"], g["presentation"]): g for g in groups}
    eligible = (
        idx["target_decoy_two_first", "unlabeled"]["exact_answer_only"] >= 15
        and idx["decoy_one", "unlabeled"]["correct_refusals"] >= 18
        and idx["no_evidence", "unlabeled"]["correct_refusals"] >= 18
    )
    summary = dict(
        planned=140,
        recorded=140,
        failed=0,
        groups=groups,
        raw_sha256=rawsha,
        source_sha256=PARENT_SHA256,
        production_accepted=False,
        candidate_disposition=(
            "independent_reader_confirmation_required"
            if eligible
            else "reader_answer_only_not_qualified"
        ),
    )
    (folder / "summary.json").write_text(json.dumps(summary))
    (folder / "plan.json").write_text(
        json.dumps(
            dict(
                schema="hepta.system2.onehop-answer-only-label-ablation.v1",
                source_commit=COMMIT,
                parent_commit="0abf776ccb577755ddba36dea3fa21a078308ad7",
                parent_sha256=PARENT_SHA256,
                parent_raw_sha256="cc04bd7fd7ecc5aed4234f9512c344eb6feffe8dd0e858507bf1688dff4cda61",
                fixed_reader_identity=READER_IDENTITY,
                task_ids=[c.question.identity for c in all_cases],
                source_arms=[
                    "single_fact",
                    "target_decoy_two_first",
                    "decoy_one",
                    "no_evidence",
                ],
                conditions=[list(x) for x in ALL_ARMS],
                planned=140,
                same_prompt_system_in_two_label_variants=True,
                no_weight_update=True,
                production_accepted=False,
            )
        )
    )
    return all_rows


class LabelAuditTests(unittest.TestCase):
    def _parent_archive(self):
        """Resolve an explicit pinned CI artifact at TEST execution time.

        Missing fixtures in source-only local runs are skipped. A hosted suite
        that promised a pinned archive must instead fail closed.
        """
        raw = os.environ.get("HEPTA_SYSTEM2_CARDINALITY_ARCHIVE")
        if not raw:
            if os.environ.get("HEPTA_REQUIRE_CARDINALITY_INTEGRATION") == "1":
                self.fail("required hosted cardinality archive environment absent")
            self.skipTest("original pinned archive not staged in source-only test")
        parent = Path(raw)
        if not parent.is_file():
            self.fail("required pinned original archive missing: " + str(parent))
        return parent

    def test_hosted_missing_archive_fails_closed(self):
        with tempfile.TemporaryDirectory() as root:
            nonexistent = str(Path(root) / "unavailable-parent.zip")
            with patch.dict(
                os.environ,
                {
                    "HEPTA_SYSTEM2_CARDINALITY_ARCHIVE": nonexistent,
                    "HEPTA_REQUIRE_CARDINALITY_INTEGRATION": "1",
                },
            ):
                with self.assertRaisesRegex(
                    AssertionError, "pinned original archive missing"
                ):
                    self._parent_archive()

    def test_source_only_no_staged_archive_skips_without_guessing(self):
        clean = dict(os.environ)
        clean.pop("HEPTA_SYSTEM2_CARDINALITY_ARCHIVE", None)
        clean.pop("HEPTA_REQUIRE_CARDINALITY_INTEGRATION", None)
        with patch.dict(os.environ, clean, clear=True):
            with self.assertRaises(unittest.SkipTest):
                self._parent_archive()

    def test_exact_discordance(self):
        self.assertEqual(exact_two_sided_discordance_p(0, 0), 1.0)
        self.assertEqual(exact_two_sided_discordance_p(1, 0), 1.0)
        self.assertAlmostEqual(exact_two_sided_discordance_p(12, 0), 2 / (2**12))
        self.assertEqual(exact_two_sided_discordance_p(4, 4), 1.0)
        for a, b in ((-1, 0), (1, -1), (0.4, 1)):
            with self.assertRaises(ValueError):
                exact_two_sided_discordance_p(a, b)

    def test_original_pinned_140_call_parent_replays(self):
        # This is completed, real-model historical evidence, not 140 new calls.
        receipt = load_previous(self._parent_archive())
        self.assertEqual(receipt["verified_files"], 25)
        self.assertEqual(len(receipt["by_key"]), 140)

    def test_complete_record_same_sources_and_plan(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t) / "trial"
            fixture(root)
            r = audit(root, self._parent_archive(), generating_commit=COMMIT)
            self.assertEqual((r["planned_model_calls"], r["source_pairs"]), (140, 60))
            self.assertEqual(r["zero_evidence_control"]["prescribed_refusals"], 20)
            self.assertFalse(r["contains_unknown_execution_failures"])
            exact = next(
                item
                for item in r["paired_metrics"]
                if item["arm"] == "target_decoy_two_first"
                and item["metric"] == "exact_answer_only"
            )
            self.assertEqual(
                (
                    exact["both"],
                    exact["labeled_only"],
                    exact["unlabeled_only"],
                    exact["neither"],
                ),
                (2, 0, 14, 4),
            )
            self.assertEqual(exact["planned_denominator_delta_bounds"], [0.7, 0.7])
            costs = next(
                item
                for item in r["token_cost_contrasts"]
                if item["arm"] == "target_decoy_two_first"
            )
            self.assertEqual(costs["exact_input_token_parity_pairs"], 0)
            self.assertEqual(costs["label_minus_no_label_input_token_gap"], [5] * 20)

    def test_missing_pair_retains_planned_denominator_and_unknown_bounds(self):
        rows = []
        with tempfile.TemporaryDirectory() as t:
            root = Path(t) / "trial"
            rows = fixture(root)
        row = next(
            x
            for x in rows
            if x["arm"] == "target_decoy_two_first" and x["presentation"] == "labeled"
        )
        row["status"] = "failed"
        row.pop("answer")
        report = compare_pairs(rows, registered=cases())
        metric = next(
            x
            for x in report["paired_metrics"]
            if x["arm"] == "target_decoy_two_first"
            and x["metric"] == "exact_answer_only"
        )
        self.assertEqual(
            (
                metric["planned_pairs"],
                metric["observed_pairs"],
                metric["unknown_pairs"],
            ),
            (20, 19, 1),
        )
        self.assertIsNone(metric["exact_p_if_complete"])
        self.assertAlmostEqual(
            metric["planned_denominator_delta_bounds"][1]
            - metric["planned_denominator_delta_bounds"][0],
            2 / 20,
        )

    def test_duplicate_or_missing_arm_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t) / "trial"
            rows = fixture(root)
        with self.assertRaises(ValueError):
            compare_pairs(rows[:-1], registered=cases())
        with self.assertRaises(ValueError):
            compare_pairs(rows + rows[:1], registered=cases())
        with self.assertRaises(ValueError):
            compare_pairs(rows + [{**rows[0], "arm": "unknown"}], registered=cases())

    def test_missing_start_event_cannot_be_rescued_by_sealed_answers(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t) / "trial"
            fixture(root)
            p = root / "starts.jsonl"
            p.write_text("\n".join(p.read_text().splitlines()[:-1]) + "\n")
            with self.assertRaisesRegex(ValueError, "start journal"):
                audit(root, self._parent_archive(), generating_commit=COMMIT)

    def test_source_excerpt_mutation_invalidates_source_binding(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t) / "trial"
            fixture(root)
            path = root / "raw-answers.jsonl"
            rows = [json.loads(x) for x in path.read_text().splitlines()]
            rows[0]["reader"]["delivered_evidence"][0]["excerpt"] += " forged"
            raw = b"".join((json.dumps(x) + "\n").encode() for x in rows)
            path.write_bytes(raw)
            seal = json.loads((root / "raw-seal.json").read_text())
            seal["sha256"] = hashlib.sha256(raw).hexdigest()
            (root / "raw-seal.json").write_text(json.dumps(seal))
            with self.assertRaisesRegex(ValueError, "Reader"):
                audit(root, self._parent_archive(), generating_commit=COMMIT)

    def test_raw_seal_tamper_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t) / "trial"
            fixture(root)
            p = root / "raw-answers.jsonl"
            p.write_bytes(p.read_bytes() + b"\n")
            with self.assertRaisesRegex(ValueError, "seal"):
                audit(root, self._parent_archive(), generating_commit=COMMIT)

    def test_modified_scoring_fails_after_resealing_answers(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t) / "trial"
            fixture(root)
            p = root / "scored.json"
            data = json.loads(p.read_text())
            data[0]["exact_answer_only"] = False
            p.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError, "scor"):
                audit(root, self._parent_archive(), generating_commit=COMMIT)

    def test_model_identity_tamper_fails_closed_even_if_new_seal(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t) / "trial"
            fixture(root)
            path = root / "raw-answers.jsonl"
            rows = [json.loads(x) for x in path.read_text().splitlines()]
            rows[1]["reader"]["reader_identity"] = "not_original"
            raw = b"".join((json.dumps(x) + "\n").encode() for x in rows)
            path.write_bytes(raw)
            seal = json.loads((root / "raw-seal.json").read_text())
            seal["sha256"] = hashlib.sha256(raw).hexdigest()
            (root / "raw-seal.json").write_text(json.dumps(seal))
            with self.assertRaisesRegex(ValueError, "Reader"):
                audit(root, self._parent_archive(), generating_commit=COMMIT)

    def test_source_and_commit_drift_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t) / "trial"
            fixture(root)
            with self.assertRaisesRegex(ValueError, "source/condition"):
                audit(root, self._parent_archive(), generating_commit="b" * 40)
            plan = json.loads((root / "plan.json").read_text())
            plan["parent_commit"] = "wrong"
            (root / "plan.json").write_text(json.dumps(plan))
            with self.assertRaisesRegex(ValueError, "source/condition"):
                audit(root, self._parent_archive(), generating_commit=COMMIT)

    def test_disposition_cannot_be_upgraded_after_scoring(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t) / "trial"
            fixture(root)
            summary = json.loads((root / "summary.json").read_text())
            summary["candidate_disposition"] = (
                "independent_reader_confirmation_required"
            )
            (root / "summary.json").write_text(json.dumps(summary))
            with self.assertRaisesRegex(ValueError, "promotion"):
                audit(root, self._parent_archive(), generating_commit=COMMIT)


if __name__ == "__main__":
    unittest.main()
