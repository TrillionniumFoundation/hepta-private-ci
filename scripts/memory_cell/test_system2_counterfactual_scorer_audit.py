"""No model's unobserved answers may be imputed from deterministic controls."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from system2_counterfactual_scorer_audit import (
    answer_from_delivered,
    audit_sealed_model_run,
    diagnostics,
    run,
    write,
)
from system2_multihop_counterfactual import ARMS, cases, select, source_manifest
from system2_multihop_counterfactual_trial import evaluate, score
from system2_multihop_trial import ABSTAIN

COMMIT = "c" * 40


def saved_model_fixture(directory, *, fail=None):
    pairs = cases()[:2]
    directory.mkdir()
    plan = dict(
        schema="hepta.system2.counterfactual-reader.v1",
        source_commit=COMMIT,
        pair_count=len(pairs),
        planned_reader_calls=len(pairs) * 2 * len(ARMS),
        arms=list(ARMS),
        pairs=[
            dict(
                pair_index=j,
                questions=[c.question.identity for c in pair],
                source_manifests=[source_manifest(c) for c in pair],
                hops=pair[0].hops,
            )
            for j, pair in enumerate(pairs)
        ],
    )
    write(directory / "plan.json", plan)
    raw = []
    for j, pair in enumerate(pairs):
        for v, case in enumerate(pair):
            for arm in ARMS:
                selected = select(arm, case.question, case.documents)
                status = "failed" if fail == (j, v, arm) else "succeeded"
                item = dict(
                    qid=case.question.identity,
                    arm=arm,
                    status=status,
                    selected=[d.identity for d in selected],
                    source_manifest=source_manifest(case),
                )
                if status == "succeeded":
                    item.update(
                        answer=answer_from_delivered(case.question, selected),
                        reader=dict(
                            reader_identity="fixture",
                            reader_profile="fixed",
                            input_tokens=150,
                            generated_tokens=12,
                        ),
                    )
                else:
                    item["error_type"] = "RuntimeError"
                raw.append(item)
    data = "".join(json.dumps(x, sort_keys=True) + "\n" for x in raw).encode()
    (directory / "raw-answers.jsonl").write_bytes(data)
    write(
        directory / "raw-seal.json",
        dict(
            sha256=hashlib.sha256(data).hexdigest(),
            rows=len(raw),
            scoring_started=False,
        ),
    )
    scored, summary = evaluate(raw, pairs)
    write(directory / "scored.json", scored)
    write(
        directory / "summary.json",
        dict(arms=summary, source_commit=COMMIT, census=dict(planned=len(raw))),
    )
    return pairs, raw


class CounterfactualScorerAuditTests(unittest.TestCase):
    def test_positive_control_exposes_hidden_abstention_ranking(self):
        with tempfile.TemporaryDirectory() as tmp:
            method = run(Path(tmp) / "positive")
        by = {x["arm"]: x for x in method}
        self.assertEqual(by["bm25_top3"]["sufficient_evidence"], 10)
        self.assertEqual(by["bm25_top3"]["verified_answer_yield"], 10)
        self.assertEqual(by["bm25_top3"]["correct_refusals"], 22)
        self.assertEqual(by["joined_top3"]["verified_answer_yield"], 32)
        self.assertEqual(by["reversed_join_top3"]["verified_answer_yield"], 32)
        self.assertEqual(by["missing_start_top3"]["verified_answer_yield"], 0)
        self.assertEqual(by["terminal_only_top3"]["correct_refusals"], 32)
        self.assertTrue(all(x["strict_successes"] == 32 for x in method))
        self.assertEqual(by["bm25_top3"]["both_counterfactual_variants_answered"], 3)
        self.assertEqual(by["joined_top3"]["both_counterfactual_variants_answered"], 16)

    def test_shortcutting_missing_premise_is_detected(self):
        case = cases()[0][0]
        selected = select("missing_start_top3", case.question, case.documents)
        bad = score(case, selected, case.answer + " [E1] [E2] [E3]")
        self.assertTrue(bad["copied_target_without_path"])
        self.assertFalse(bad["strict_success"])
        self.assertFalse(bad["cites_required"])

    def test_fake_and_incomplete_citations_cannot_pass(self):
        case = cases()[0][0]
        selected = select("joined_top3", case.question, case.documents)
        for raw in (
            case.answer + " [E99]",
            case.answer + " [E1]",
            case.answer + " [E1] [E1]",
            ABSTAIN,
        ):
            self.assertFalse(score(case, selected, raw)["strict_success"])

    def test_counterfactual_flip_fails_if_answer_reused(self):
        before, after = cases()[1]
        selected = select("joined_top3", after.question, after.documents)
        self.assertNotEqual(before.answer, after.answer)
        self.assertFalse(
            score(after, selected, before.answer + " [E1] [E2] [E3]")["strict_success"]
        )

    def test_reverse_order_citations_bind_actual_source_positions(self):
        case = cases()[0][0]
        selected = select("reversed_join_top3", case.question, case.documents)
        answer = answer_from_delivered(case.question, selected)
        self.assertTrue(score(case, selected, answer)["strict_success"])

    def test_success_and_abstention_decomposition_violations_rejected(self):
        pairs = cases()[:1]
        rows = []
        for variant, case in enumerate(pairs[0]):
            for arm in ARMS:
                selected = select(arm, case.question, case.documents)
                rows.append(
                    dict(
                        pair_index=0,
                        variant=variant,
                        arm=arm,
                        **score(
                            case,
                            selected,
                            answer_from_delivered(case.question, selected),
                        ),
                    )
                )
        self.assertEqual(len(diagnostics(rows, pairs)), len(ARMS))
        rows[0]["strict_success"] = False
        with self.assertRaisesRegex(ValueError, "decomposition"):
            diagnostics(rows, pairs)

    def test_postseal_model_fixture_read_only_and_cost_accounted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "input"
            saved_model_fixture(source)
            before = (source / "raw-answers.jsonl").read_bytes()
            result = audit_sealed_model_run(source, root / "out", count=2)
            self.assertEqual(result["planned"], 20)
            self.assertEqual(result["completed"], 20)
            self.assertEqual(result["failures"], 0)
            self.assertEqual((source / "raw-answers.jsonl").read_bytes(), before)
            by = {x["arm"]: x for x in result["results"]}
            self.assertEqual(by["joined_top3"]["useful_verified_answers"], 4)
            self.assertEqual(by["missing_start_top3"]["correct_refusals"], 4)
            self.assertEqual(by["missing_start_top3"]["useful_verified_answers"], 0)
            self.assertEqual(by["joined_top3"]["actual_reader_input_tokens"], 600)
            self.assertFalse(result["independent_semantic_judgment"])

    def test_failed_reader_is_unknown_not_fake_negative_label(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "input"
            saved_model_fixture(source, fail=(0, 0, "joined_top3"))
            result = audit_sealed_model_run(source, root / "audit", count=2)
            by = {r["arm"]: r for r in result["results"]}
            joined = by["joined_top3"]
            self.assertEqual(joined["planned"], 4)
            self.assertEqual(joined["completed"], 3)
            self.assertEqual(joined["useful_verified_answers"], 3)
            self.assertEqual(joined["useful_answer_yield_bounds"], [3, 4])
            self.assertEqual(joined["paired_unknown"], 1)
            self.assertTrue(joined["unknown_failed_costs_not_free"])

    def test_corrupt_raw_hash_or_counts_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            saved_model_fixture(source)
            (source / "raw-answers.jsonl").write_bytes(
                (source / "raw-answers.jsonl").read_bytes() + b"\n"
            )
            with self.assertRaisesRegex(ValueError, "sealed"):
                audit_sealed_model_run(source, root / "output", count=2)

    def test_corrupt_scores_cannot_be_smuggled_in(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            saved_model_fixture(source)
            data = json.loads((source / "scored.json").read_text())
            data[0]["strict_success"] = not data[0]["strict_success"]
            write(root / "corrupt.json", data)
            (source / "scored.json").write_text((root / "corrupt.json").read_text())
            with self.assertRaisesRegex(ValueError, "scoring drift"):
                audit_sealed_model_run(source, root / "output", count=2)

    def test_mismatched_reader_identities_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            _, rows = saved_model_fixture(source)
            rows[0]["reader"]["reader_identity"] = "different-reader"
            data = "".join(json.dumps(x, sort_keys=True) + "\n" for x in rows).encode()
            (source / "raw-answers.jsonl").write_bytes(data)
            write(
                root / "seal.json",
                dict(
                    sha256=hashlib.sha256(data).hexdigest(),
                    rows=len(rows),
                    scoring_started=False,
                ),
            )
            (source / "raw-seal.json").write_bytes((root / "seal.json").read_bytes())
            with self.assertRaisesRegex(ValueError, "multiple Reader"):
                audit_sealed_model_run(source, root / "out", count=2)

    def test_incomplete_reader_receipt_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            _, rows = saved_model_fixture(source)
            rows[0]["reader"].pop("input_tokens")
            data = "".join(json.dumps(x, sort_keys=True) + "\n" for x in rows).encode()
            (source / "raw-answers.jsonl").write_bytes(data)
            write(
                root / "seal.json",
                dict(
                    sha256=hashlib.sha256(data).hexdigest(),
                    rows=len(rows),
                    scoring_started=False,
                ),
            )
            (source / "raw-seal.json").write_bytes((root / "seal.json").read_bytes())
            with self.assertRaisesRegex(ValueError, "cost/identity"):
                audit_sealed_model_run(source, root / "out", count=2)


if __name__ == "__main__":
    unittest.main()
