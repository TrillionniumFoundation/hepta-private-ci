"""Original-artifact analysis integration; all sources here are manufactured."""

from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

import ctrl_macro_analysis as analysis
from ndu_real_materials import common
from ndu_real_runtime import macro_training_pairs
from ndu_real_runtime.metacontrol_macro_contract import digest, sha
from ndu_real_runtime.test_macro_realization import save, sync_steps
from ndu_real_runtime.test_macro_training_fixtures import collection, read, refresh


def evidence(root, *, capture_initial=True):
    output, context = collection(root)
    for macro in ("STOP", "READ"):
        directory = output / ("p1-" + macro)
        steps = read(directory / "trajectory.json")["steps"]
        for index, step in enumerate(steps):
            step["selected_candidate_index"] = (
                0 if macro == "READ" and index >= 2 else 1
            )
        sync_steps(directory, steps)
        if capture_initial:
            initial = read(directory / "public-input.json")
            initial.update(step=0, forced_action=steps[0]["action"]["action"])
            raw = (
                (directory / "public-input.json").read_bytes()
                if macro == "STOP"
                else common.json_bytes(initial)
            )
            (directory / "initial-public-input.json").write_bytes(raw)
            launch = read(directory / "launch.json")
            launch["host_exchanges"][0].update(
                reply_sha256=sha(raw), reply_bytes=len(raw)
            )
            save(directory / "launch.json", launch)
    refresh(output)
    report = macro_training_pairs.export(
        output,
        expected_plan_sha256=sha((output / "PLAN.json").read_bytes()),
        context=context,
        expected_source_sha256=macro_training_pairs.source_sha256(),
        allow_fixtures=True,
    )
    return output, context, report


class MacroCollectionAnalysisTests(unittest.TestCase):
    def run_analysis(self, output, context, report):
        return analysis.analyze(
            report,
            collection_root=output,
            context=context,
            expected_export_sha256=digest(report),
            allow_fixtures=True,
        )

    def test_complete_originals_report_choice_and_terminal_effect_without_replay(self):
        with tempfile.TemporaryDirectory() as temporary:
            output, context, report = evidence(Path(temporary))
            before = {str(p): p.read_bytes() for p in output.rglob("*") if p.is_file()}
            result = self.run_analysis(output, context, report)
            self.assertEqual(result["planned_pairs"], 1)
            self.assertEqual(result["matched_pairs"], 1)
            self.assertEqual(result["evidence_kinds"], ["fixture"])
            metrics = result["metrics"]
            self.assertEqual(
                metrics["new_reference_matching_candidate"]["source_equal_mean"], 0.0
            )
            self.assertEqual(metrics["selected_text_changed"]["source_equal_mean"], 1.0)
            self.assertEqual(
                metrics["read_minus_stop_quality"]["source_equal_mean"], 1.0
            )
            self.assertAlmostEqual(
                metrics["read_minus_stop_observed_latency_net"]["source_equal_mean"],
                0.99,
            )
            self.assertFalse(result["full_physical_cost_observed"])
            self.assertFalse(result["new_source_qualification"])
            self.assertEqual(
                before,
                {str(p): p.read_bytes() for p in output.rglob("*") if p.is_file()},
            )

    def test_missing_original_initial_packet_does_not_become_known_matched_effect(self):
        with tempfile.TemporaryDirectory() as temporary:
            output, context, report = evidence(Path(temporary), capture_initial=False)
            result = self.run_analysis(output, context, report)
            self.assertEqual(result["exported_pairs"], 1)
            self.assertEqual(result["matched_pairs"], 0)
            self.assertEqual(result["paired_rows"][0]["paired_status"], "UNKNOWN")
            self.assertIsNone(
                result["metrics"]["read_minus_stop_quality"]["source_equal_mean"]
            )

    def test_one_unknown_preserves_plan_and_prevents_subset_analysis(self):
        with tempfile.TemporaryDirectory() as temporary:
            output, context, report = evidence(Path(temporary))
            report = deepcopy(report)
            report["planned"].append(
                {
                    "pair_id": "missing",
                    "source_id": "missing-source",
                    "split": "calibration",
                    "status": "UNKNOWN",
                    "reason": "missing original terminal",
                }
            )
            report.update(planned_pairs=2, unknown_pairs=1)
            result = self.run_analysis(output, context, report)
            self.assertEqual(
                result["analysis_status"], "BLOCKED_INCOMPLETE_PLANNED_COLLECTION"
            )
            self.assertEqual(result["planned_pairs"], 2)
            self.assertEqual(result["original_dispositions"], report["planned"])
            self.assertIsNone(result["metrics"])
            self.assertEqual(result["paired_rows"], [])

    def test_rehashed_export_cannot_replace_missing_or_changed_native_originals(self):
        for change in ("export", "original", "fixture_scope"):
            with (
                self.subTest(change=change),
                tempfile.TemporaryDirectory() as temporary,
            ):
                output, context, report = evidence(Path(temporary))
                if change == "export":
                    report["rows"][0]["branches"]["STOP"]["quality"] = 0.5
                elif change == "original":
                    path = output / "p1-READ/result.json"
                    path.write_bytes(path.read_bytes() + b" ")
                with self.assertRaises(ValueError):
                    analysis.analyze(
                        report,
                        collection_root=output,
                        context=context,
                        expected_export_sha256=digest(report),
                        allow_fixtures=change != "fixture_scope",
                    )

    def test_source_equal_arithmetic_does_not_weight_repeated_source_rows_as_independent(
        self,
    ):
        rows = [
            {"source_id": "a", "gain": 1.0},
            {"source_id": "a", "gain": 1.0},
            {"source_id": "b", "gain": -1.0},
        ]
        self.assertEqual(analysis.source_mean(rows, "gain"), 0.0)


if __name__ == "__main__":
    unittest.main()
