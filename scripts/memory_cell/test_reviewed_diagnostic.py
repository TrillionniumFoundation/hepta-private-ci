"""Reviewed execution contracts; fixtures are not semantic or model evidence."""

import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from native import digest
from reviewed_diagnostic import DiagnosticInputs, capability_plan, execute, outcome
from test_bundle_trial import TestReaderDouble
from test_reviewed_bundle import fixture


class ReviewedDiagnosticTests(unittest.TestCase):
    def inputs(self, root):
        plan, package = fixture()
        plan["cases"][0]["phase"] = "capability"
        plan["frozen_counts"] = {"capability": 1}
        package["base_plan_digest"] = digest(plan)
        files = dict(
            plan=plan,
            reviews=package,
            withdrawals=[],
            labels={"q": {"answer": "March", "unanswerable": False}},
            inventory={"inventory_digest": "fixture-not-pretrained"},
        )
        paths, pins = {}, {}
        for key, value in files.items():
            p = root / (key + ".json")
            p.write_text(json.dumps(value, ensure_ascii=False))
            paths[key], pins[key] = p, hashlib.sha256(p.read_bytes()).hexdigest()
        return DiagnosticInputs(paths, pins), plan, package

    def test_same_reader_raw_answers_precede_label_parsing(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            inputs, plan, package = self.inputs(root)
            reader = TestReaderDouble()
            import bundle_trial

            original_read = bundle_trial.read

            def read(path, expected=None):
                if path == inputs.paths["labels"]:
                    raw = root / "out/execution/raw-answers.jsonl"
                    self.assertEqual(len(raw.read_text().splitlines()), 5)
                return original_read(path, expected)

            with patch("bundle_trial.read", side_effect=read):
                result = execute(
                    inputs,
                    Path("unused"),
                    root / "out",
                    reader_factory=lambda *a, **k: reader,
                )
            self.assertTrue(reader.verified)
            self.assertEqual(len(reader.calls), 5)
            self.assertFalse(result["training_permitted"])
            self.assertFalse(result["independent_sufficiency_certified"])
            projected = json.loads((root / "out/reviewed-plan.json").read_text())
            self.assertEqual(
                digest(projected["cases"][0]["conditions"]["empty"]),
                digest(plan["cases"][0]["conditions"]["empty"]),
            )
            self.assertEqual(
                projected["cases"][0]["conditions"]["reviewed_minimal"]["token_limit"],
                2048,
            )
            with self.assertRaises(FileExistsError):
                execute(
                    inputs,
                    Path("unused"),
                    root / "out",
                    reader_factory=lambda *a, **k: reader,
                )

    def test_model_assistance_cannot_be_upgraded_to_independent_review(self):
        plan, package = fixture()
        plan["cases"][0]["phase"] = "capability"
        package["base_plan_digest"] = digest(plan)
        package["reviews"]["q"]["review_basis"] = "model_assisted_review"
        output = capability_plan(plan, package, set())
        full = output["cases"][0]["conditions"]["reviewed_minimal"]
        self.assertEqual(
            full["oracle_kind"], "model_assisted_claim_not_independent_review"
        )
        self.assertFalse(full["independent_review"])
        self.assertFalse(full["sufficient_context_certified"])
        self.assertEqual(len(full["bundle"]["selected"]), 2)

    def test_unknown_missing_and_published_claims_do_not_create_minimality(self):
        plan, package = fixture()
        plan["cases"][0]["phase"] = "capability"
        package["base_plan_digest"] = digest(plan)
        package["reviews"] = {}
        out = capability_plan(plan, package, set())
        self.assertEqual(len(out["cases"]), 1)
        self.assertEqual(
            out["cases"][0]["conditions"]["reviewed_minimal"]["status"], "unavailable"
        )
        self.assertEqual(
            out["cases"][0]["conditions"]["reviewed_reversed"]["status"], "unavailable"
        )

    def test_bad_inventory_and_label_pins_reject_before_model_load(self):
        for field in ("inventory", "labels", "plan", "reviews", "withdrawals"):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as d:
                inputs, _, _ = self.inputs(Path(d))
                inputs.pins[field] = "0" * 64
                calls = []
                with self.assertRaises(ValueError):
                    execute(
                        inputs,
                        Path("unused"),
                        Path(d) / "out",
                        reader_factory=lambda *a, **k: calls.append(1),
                    )
                self.assertEqual(calls, [])
                self.assertFalse((Path(d) / "out").exists())

    def test_changed_withdrawals_after_model_call_never_deliver_success(self):
        with tempfile.TemporaryDirectory() as d:
            inputs, _, _ = self.inputs(Path(d))

            class MutatingReader(TestReaderDouble):
                def answer(self, *a, **k):
                    value = super().answer(*a, **k)
                    inputs.paths["withdrawals"].write_text('["r1"]')
                    return value

            with self.assertRaises(ValueError):
                execute(
                    inputs,
                    Path("unused"),
                    Path(d) / "out",
                    reader_factory=lambda *a, **k: MutatingReader(),
                )
            records = [
                json.loads(line)
                for line in (Path(d) / "out/execution/raw-answers.jsonl")
                .read_text()
                .splitlines()
            ]
            self.assertEqual(len(records), 5)
            self.assertTrue(all(r["status"] == "failed" for r in records))
            self.assertFalse((Path(d) / "out/reviewed-diagnostic.json").exists())

    def test_withdrawn_ordinary_evidence_is_checked_even_without_reviews(self):
        plan, package = fixture()
        plan["cases"][0]["phase"] = "capability"
        package["base_plan_digest"] = digest(plan)
        package["reviews"] = {}
        with self.assertRaises(ValueError):
            capability_plan(plan, package, {"r1"})

    def test_unknown_success_scores_and_mixed_readers_reject(self):
        with tempfile.TemporaryDirectory() as d:
            inputs, plan, package = self.inputs(Path(d))
            execute(
                inputs,
                Path("unused"),
                Path(d) / "out",
                reader_factory=lambda *a, **k: TestReaderDouble(),
            )
            projected = json.loads((Path(d) / "out/reviewed-plan.json").read_text())
            rows = json.loads(
                (Path(d) / "out/execution/scored-answers.json").read_text()
            )
            for value in (None, float("nan"), True, float("inf")):
                changed = copy.deepcopy(rows)
                changed[0]["f1"] = value
                with self.assertRaises(ValueError):
                    outcome(projected, package, changed)
            changed = copy.deepcopy(rows)
            changed[0]["receipt"]["reader_identity"] = "different"
            with self.assertRaises(ValueError):
                outcome(projected, package, changed)
            with self.assertRaises(ValueError):
                outcome(projected, package, rows[:-1])

    def test_frozen_census_not_reduced_and_no_training_cases_promoted(self):
        plan, package = fixture()
        plan["cases"][0]["phase"] = "capability"
        plan["frozen_counts"] = {"capability": 8}
        package["base_plan_digest"] = digest(plan)
        with self.assertRaises(ValueError):
            capability_plan(plan, package, set())
        plan["cases"][0]["phase"] = "train"
        package["base_plan_digest"] = digest(plan)
        with self.assertRaises(ValueError):
            capability_plan(plan, package, set())


if __name__ == "__main__":
    unittest.main()
