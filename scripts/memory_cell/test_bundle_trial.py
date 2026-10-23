"""End-to-end protocol tests with a clearly named non-pretrained reader double."""

from dataclasses import asdict, replace
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from bundle_census import summarize
from bundle_reader import PromptBudgetError, compile_prompt
from bundle_trial import (
    annotated_condition,
    bundle_condition,
    canaries,
    decode_bundle,
    normal_conditions,
    read,
    run_reader,
    write,
)
from evidence_bundle import EvidenceBundle, build_windows
from native import Target, digest
from test_evidence_bundle import Tokenizer, fixture


class TestReaderDouble:
    identity = "fixture-not-pretrained"

    def __init__(self):
        self.calls = []
        self.verified = False

    def answer(self, query, bundle, originals, **kwargs):
        self.calls.append(bundle.mode)
        ids, rec = compile_prompt(Tokenizer(), query, bundle, originals, **kwargs)
        return "March [E1]" if bundle.selected else "unsupported guess", rec | dict(
            reader_identity=self.identity,
            reader_profile="fixture",
            generated_tokens=3,
            answer_postprocessed=False,
            generated_ids_digest=digest([7, 8, 9]),
        )

    def verify_frozen(self):
        self.verified = True


class TrialTests(unittest.TestCase):
    def fixture_plan(self):
        q, originals, spans = fixture()
        frontier = digest([asdict(d) for d in originals.values()])
        conditions = normal_conditions(
            q, originals, lambda q, k: (list(spans), {}), frontier
        )
        target = Target("March", "fixture", ("d0", "d1"), False)
        conditions["annotated_sources"] = annotated_condition(
            q, originals, target, frontier
        )
        plan = dict(
            schema="hepta.bundle-diagnostic.plan.v1",
            source_commit="a" * 40,
            cases=[
                dict(
                    question=asdict(q),
                    originals=[asdict(d) for d in originals.values()],
                    phase="fixture",
                    family=q.family,
                    frontier=frontier,
                    conditions=conditions,
                )
            ],
        )
        return plan, {q.identity: asdict(target)}

    def test_annotation_drift_cannot_change_normal_selection(self):
        q, originals, spans = fixture()
        retrieve = lambda q, k: (list(spans), {})
        before = normal_conditions(q, originals, retrieve, "f")
        a = annotated_condition(
            q, originals, Target("answer", "a", ("d0",), False), "f"
        )
        b = annotated_condition(
            q, originals, Target("different", "b", ("d1",), False), "f"
        )
        self.assertNotEqual(a, b)
        self.assertEqual(before, normal_conditions(q, originals, retrieve, "f"))
        self.assertFalse(a["sufficient_context_certified"])

    def test_full_source_oracle_does_not_trim_to_reference_answer(self):
        q, originals, _ = fixture()
        target = Target("May", "fixture", ("d0", "d1"), False)
        c = annotated_condition(q, originals, target, "f")
        self.assertEqual(
            [s["excerpt"] for s in c["delivered_evidence"]],
            [originals["d0"].content, originals["d1"].content],
        )
        self.assertEqual(
            annotated_condition(
                q, originals, replace(target, evidence=("missing",)), "f"
            )["status"],
            "unavailable",
        )

    def test_all_raw_answers_exist_before_target_file_read(self):
        plan, labels = self.fixture_plan()
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            p, l, out = root / "p.json", root / "l.json", root / "out"
            write(p, plan)
            write(l, labels)
            model = TestReaderDouble()
            psha, lsha = (
                hashlib.sha256(p.read_bytes()).hexdigest(),
                hashlib.sha256(l.read_bytes()).hexdigest(),
            )
            original_read = read

            def watched(path, expected=None):
                if path == l:
                    raw = (out / "raw-answers.jsonl").read_text().splitlines()
                    self.assertEqual(len(raw), len(plan["cases"][0]["conditions"]))
                    self.assertTrue(all("f1" not in json.loads(r) for r in raw))
                return original_read(path, expected)

            with patch("bundle_trial.read", side_effect=watched):
                result = run_reader(p, l, model, out, plan_sha=psha, labels_sha=lsha)
            self.assertEqual(len(model.calls), len(plan["cases"][0]["conditions"]))
            self.assertIn("empty", model.calls)
            self.assertTrue(model.verified)
            self.assertFalse(result["production_accepted"])
            rows = json.loads((out / "scored-answers.json").read_text())
            self.assertEqual(summarize(rows, plan), result)

    def test_budget_block_is_retained_not_a_fabricated_answer(self):
        plan, labels = self.fixture_plan()

        class BudgetReader(TestReaderDouble):
            def answer(self, q, b, originals, **kw):
                if b.mode == "annotated_sources":
                    raise PromptBudgetError(6000, 4096)
                return super().answer(q, b, originals, **kw)

        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            p, l, out = root / "p", root / "l", root / "o"
            write(p, plan)
            write(l, labels)
            result = run_reader(
                p,
                l,
                BudgetReader(),
                out,
                plan_sha=hashlib.sha256(p.read_bytes()).hexdigest(),
                labels_sha=hashlib.sha256(l.read_bytes()).hexdigest(),
            )
            stats = result["summaries"]["fixture/annotated_sources"]
            self.assertEqual(
                (stats["planned"], stats["unavailable"], stats["succeeded"]), (1, 1, 0)
            )
            self.assertIsNone(stats["f1"])

    def test_drift_duplicate_failure_and_mixed_models_reject(self):
        plan, _ = self.fixture_plan()
        rows = []
        for arm, c in plan["cases"][0]["conditions"].items():
            rows.append(
                dict(
                    question_id="q",
                    arm=arm,
                    phase="fixture",
                    family="family",
                    status="succeeded",
                    answer="test",
                    f1=0.5,
                    exact_match=0.0,
                    target_unanswerable=False,
                    receipt=dict(
                        reader_identity="model",
                        reader_profile="same",
                        bundle_digest=c["bundle_digest"],
                        token_limit=c["token_limit"],
                        input_tokens=1,
                        generated_tokens=1,
                        delivered_evidence=c["delivered_evidence"],
                    ),
                )
            )
        summarize(rows, plan)
        for change in (
            lambda x: x.pop(),
            lambda x: x.append(x[0]),
            lambda x: x[0].update(f1=float("nan")),
            lambda x: x[0]["receipt"].update(reader_identity="other"),
            lambda x: x[0]["receipt"].update(delivered_evidence=[]),
            lambda x: x[0].update(status="failed"),
        ):
            bad = copy.deepcopy(rows)
            change(bad)
            with self.assertRaises(ValueError):
                summarize(bad, plan)

    def test_bundle_content_corruption_rejects_before_reader(self):
        plan, _ = self.fixture_plan()
        condition = plan["cases"][0]["conditions"]["single"]
        bad = copy.deepcopy(condition)
        bad["bundle"]["selected"][0]["excerpt"] = "new"
        with self.assertRaises(ValueError):
            decode_bundle(bad)

    def test_actual_execution_failure_keeps_report_and_fails_command(self):
        plan, labels = self.fixture_plan()

        class Failing(TestReaderDouble):
            def answer(self, q, b, originals, **kw):
                if b.mode == "empty":
                    raise RuntimeError("reader failed")
                return super().answer(q, b, originals, **kw)

        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            p, l, out = root / "p", root / "l", root / "o"
            write(p, plan)
            write(l, labels)
            with self.assertRaisesRegex(ValueError, "failed cases retained"):
                run_reader(
                    p,
                    l,
                    Failing(),
                    out,
                    plan_sha=hashlib.sha256(p.read_bytes()).hexdigest(),
                    labels_sha=hashlib.sha256(l.read_bytes()).hexdigest(),
                )
            result = read(out / "report.json")
            self.assertEqual(result["summaries"]["fixture/empty"]["failed"], 1)

    def test_controls_have_two_distinct_sources_and_are_not_real_observations(self):
        for q, docs, target, family, phase in canaries():
            self.assertEqual(phase, "authored_control")
            self.assertEqual(len(set(target.evidence)), 2)
            self.assertTrue(target.category.startswith("authored"))
            self.assertNotIn(target.answer, q.content)


if __name__ == "__main__":
    unittest.main()
