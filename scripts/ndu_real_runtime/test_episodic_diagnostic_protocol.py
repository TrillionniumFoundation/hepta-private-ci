"""MEM14 controls reuse synthetic provider receipts, never run a real model."""

import copy
import hashlib
import math
from pathlib import Path
import unittest
from unittest import mock

from . import run_episodic_diagnostic as experiment
from . import test_run_episodic_diagnostic as fixtures
from .episodic_diagnostic_protocol import FOLLOWUP_SCHEMA, LEGACY_SCHEMA, SELECTORS
from .episodic_memory import canonical_bytes


class FollowupProtocolTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.DiagnosticTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def followup(self):
        fixture = self.fixture
        fixture.root = Path(fixture.temporary.name) / "new-followup"
        fixture.plan = experiment.prepare(
            fixture.root,
            fixture.profile,
            "fresh-mem14-cohort",
            source_count=32,
            retrieval_records=1,
            selector_version="v2",
        )
        fixture.plan_sha = experiment.pin((fixture.root / "PLAN.json").read_bytes())[
            "sha256"
        ]

    def sentence_provider(self, root, request, **options):
        result = self.fixture.fake_provider(root, request, **options)
        color = result["result"]["text"]
        if color in experiment.COLORS:
            result["result"]["text"] = f"The courier must use a {color} badge."
        directory = root / hashlib.sha256(options["request_id"].encode()).hexdigest()
        lines = (directory / "combined.log").read_bytes().splitlines()
        log = (
            b"\n".join(
                b"MEM11_RESULT " + canonical_bytes(result["result"])
                if line.startswith(b"MEM11_RESULT ")
                else line
                for line in lines
            )
            + b"\n"
        )
        result["combined_log"] = experiment.pin(log)
        (directory / "combined.log").write_bytes(log)
        (directory / "RECEIPT.json").write_bytes(canonical_bytes(result))
        return result

    def test_public_parser_versions_have_strict_independent_grammars(self):
        self.assertEqual(experiment.selected_text(" Answer: Blue. "), "blue")
        self.assertIsNone(
            experiment.selected_text("The courier must use a blue badge.")
        )
        for raw, selected in (
            (" blue ", "blue"),
            ("\nUnKnOwN\t", "unknown"),
            (" The courier must use a BLUE badge.\n", "blue"),
        ):
            self.assertEqual(experiment.selected_text(raw, version="v2"), selected)
        for raw in (
            "Answer: blue",
            "blue.",
            "blue or red",
            "blue\nred",
            "The courier must use the blue badge.",
            "The courier must use a blue badge",
            "The courier must use a blue badge. Then use red.",
            "The courier must use a unknown badge.",
            "The courier must use a  blue badge.",
            ["blue"],
            {"answer": "blue"},
            None,
        ):
            with self.subTest(raw=raw):
                self.assertIsNone(experiment.selected_text(raw, version="v2"))
        with self.assertRaises(ValueError):
            experiment.selected_text("blue", version="future")

    def test_legacy_and_followup_loaders_reject_relabelled_counts_limits_and_rosters(
        self,
    ):
        fixture = self.fixture
        self.assertEqual(fixture.plan["schema"], LEGACY_SCHEMA)
        original_keys = {
            fact["key"] for case in fixture.plan["cases"] for fact in case["facts"]
        }

        def reject(change):
            changed = copy.deepcopy(fixture.plan)
            change(changed)
            raw = canonical_bytes(changed)
            (fixture.root / "PLAN.json").write_bytes(raw)
            (fixture.root / "PLAN_PIN.json").write_bytes(
                canonical_bytes(experiment.pin(raw))
            )
            with self.assertRaises(ValueError):
                experiment.load_plan(fixture.root)

        for change in (
            lambda plan: plan.update(selector_version="v2"),
            lambda plan: plan.update(selector=SELECTORS["v2"]),
            lambda plan: plan.update(source_count=32),
            lambda plan: plan["limits"].update(retrieval_records=1),
            lambda plan: plan["limits"].update(output_tokens=64),
        ):
            reject(change)
        self.followup()
        self.assertEqual(fixture.plan["schema"], FOLLOWUP_SCHEMA)
        self.assertFalse(
            original_keys
            & {fact["key"] for case in fixture.plan["cases"] for fact in case["facts"]}
        )
        result = experiment.report(fixture.root)
        self.assertEqual(
            (result["planned_rows"], len(result["rows"]), result["generated_sources"]),
            (320, 320, 32),
        )
        self.assertEqual(result["contrasts"]["off"]["primary_hoeffding_lower_95"], -1.0)
        self.assertIsNone(result["contrasts"]["off"]["paired_mean_difference"])
        for change in (
            lambda plan: plan.update(source_count=8),
            lambda plan: plan.update(source_count=True),
            lambda plan: plan["limits"].update(retrieval_records=True),
            lambda plan: plan["limits"].update(input_tokens=2048),
            lambda plan: plan["cases"].pop(),
            lambda plan: plan["cases"][0].update(case_id="source-02"),
            lambda plan: plan["cases"][0].update(arm_order=["off"] * 10),
            lambda plan: plan["analysis"].update(alpha=0.1),
        ):
            reject(change)

    def test_old_scores_stay_zero_and_new_320_rows_share_one_record_cap(self):
        fixture = self.fixture
        with (
            mock.patch.object(
                experiment, "run_isolated_actor", side_effect=fixture.fake_actor
            ),
            mock.patch.object(
                experiment, "run_local_provider", side_effect=self.sentence_provider
            ),
        ):
            original = experiment.run(fixture.root)
            self.assertEqual(original["known_returned_generations"], 80)
            self.assertTrue(
                all(
                    panel["successes"] == 0 and panel["scored"] == 8
                    for panel in original["panels"].values()
                )
            )
            self.followup()
            result = experiment.run(fixture.root)
            self.assertEqual(experiment.run(fixture.root), result)
        self.assertEqual(len(fixture.calls), 400)
        self.assertEqual(
            (
                result["planned_rows"],
                len(result["rows"]),
                result["known_returned_generations"],
            ),
            (320, 320, 320),
        )
        self.assertTrue(
            all(
                panel["planned"] == 32 and panel["scored"] == 32
                for panel in result["panels"].values()
            )
        )
        self.assertEqual(result["panels"]["on_bm25"]["successes"], 32)
        self.assertEqual(result["panels"]["exact_kv"]["successes"], 32)
        self.assertEqual(result["panels"]["off"]["successes"], 0)
        self.assertTrue(
            all(
                panel["v1_descriptive"]["successes"] == 0
                for panel in result["panels"].values()
            )
        )
        self.assertEqual(
            result["panels"]["on_bm25"]["v1_descriptive"]["format_accepted"], 0
        )
        for row in result["rows"]:
            receipt = row["memory_receipt"]
            self.assertEqual(receipt["limit"], 1)
            for field in ("retrieved_ids", "selected_ids", "delivered_ids"):
                self.assertLessEqual(len(receipt[field]), 1)
            if row["arm"] in {"on_bm25", "exact_kv"}:
                self.assertFalse(row["v1_format_accepted"])
        self.assertEqual(len(result["contrasts"]), 9)
        main = result["contrasts"]["off"]
        self.assertAlmostEqual(
            main["primary_hoeffding_lower_95"], 1 - math.sqrt(2 * math.log(20) / 32)
        )
        self.assertAlmostEqual(
            main["bonferroni_hoeffding_lower_95"],
            1 - math.sqrt(2 * math.log(9 / 0.05) / 32),
        )
        for contrast in result["contrasts"].values():
            self.assertEqual(contrast["planned_pairs"], 32)
            expected = max(
                -1,
                contrast["paired_mean_difference"]
                - math.sqrt(2 * math.log(9 / 0.05) / 32),
            )
            self.assertAlmostEqual(contrast["bonferroni_hoeffding_lower_95"], expected)
        row = next(row for row in result["rows"] if row["arm"] == "on_bm25")
        (fixture.root / row["case_id"] / "on_bm25" / "ROW.json").unlink()
        missing = experiment.report(fixture.root)
        self.assertEqual(len(missing["rows"]), 320)
        self.assertEqual(
            missing["contrasts"]["off"]["missing_label_difference_bounds"],
            [31 / 32, 1.0],
        )
        self.assertAlmostEqual(
            missing["contrasts"]["off"]["primary_hoeffding_lower_95"],
            31 / 32 - math.sqrt(2 * math.log(20) / 32),
        )
        self.assertEqual(missing["scientific_acceptance"], "HOLD")
        self.assertFalse(missing["native_owner_used"])


if __name__ == "__main__":
    unittest.main()
