"""Manufactured retained-byte tests only; no native execution or efficacy claim."""

from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ndu_real_materials import common
from . import macro_training_pairs as exporter
from .macro_policy import _pairs
from .metacontrol_macro_contract import digest, sha
from .test_macro_realization import save, sync_steps
from .test_macro_training_fixtures import collection, read, refresh


def run_export(output, context, **options):
    return exporter.export(
        output,
        context=context,
        expected_plan_sha256=sha((output / "PLAN.json").read_bytes()),
        expected_source_sha256=exporter.source_sha256(),
        **{"allow_fixtures": True, **options},
    )


class MacroTrainingPairTests(unittest.TestCase):
    def test_completed_rows_preserve_macro_gain_and_resolvable_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            output, context = collection(Path(tmp))
            report = run_export(output, context)
            self.assertEqual(
                (report["planned_pairs"], report["exported_pairs"]),
                (1, 1),
                report["planned"],
            )
            row = _pairs(report["rows"], context)[0]
            self.assertEqual(row["state"]["remaining_seconds"], 10.0)
            self.assertEqual(
                row["labels"],
                {"acquired": True, "selected_used": True, "effect_occurred": None},
            )
            self.assertAlmostEqual(row["branches"]["READ"]["cost"], 0.012)
            for branch in row["branches"].values():
                self.assertFalse(branch["full_cost_observed"])
                self.assertIn(branch["evidence_sha256"], report["receipts"])
            self.assertFalse(report["policy_efficacy_evaluated"])
            (output / "p1-READ/public-input.json").unlink()
            self.assertIsNone(
                run_export(output, context)["rows"][0]["labels"]["acquired"]
            )

    def test_legacy_labels_and_missing_planned_pairs_remain_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            output, context = collection(Path(tmp), modern=False)
            self.assertIsNone(
                run_export(output, context)["rows"][0]["labels"]["selected_used"]
            )
            plan = read(output / "PLAN.json")
            plan["pairs"].append({**plan["pairs"][0], "pair_id": "p2"})
            save(output / "PLAN.json", plan)
            refresh(output, update_plan=True)
            report = run_export(output, context)
            self.assertEqual(
                (
                    report["planned_pairs"],
                    report["exported_pairs"],
                    report["unknown_pairs"],
                ),
                (2, 1, 1),
            )
            self.assertEqual(report["planned"][1]["status"], "UNKNOWN")

    def test_failed_bad_cost_nonoriginal_and_native_spoof_are_not_rows(self):
        for mutation in ("failed", "cost", "boolean", "native", "repeat", "noise"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as tmp:
                output, context = collection(Path(tmp))
                summary = read(output / "p1.json")
                if mutation == "failed":
                    summary["branches"]["READ"]["status"] = "failed_or_unresolved"
                elif mutation in ("cost", "boolean"):
                    summary["branches"]["READ"]["latency_cost"] = (
                        True if mutation == "boolean" else 99.0
                    )
                elif mutation == "native":
                    summary["evidence_kind"] = "native_module_execution"
                else:
                    plan = read(output / "PLAN.json")
                    plan["pairs"][0]["read_condition"] = mutation
                    save(output / "PLAN.json", plan)
                    summary.update(read_condition=mutation, plan_sha256=digest(plan))
                save(output / "p1.json", summary)
                report = run_export(output, context)
                self.assertEqual(report["rows"], [])
                self.assertEqual(report["unknown_pairs"], 1)

    def test_wire_source_state_budget_and_context_drift_reject(self):
        for mutation in (
            "wire",
            "source",
            "state",
            "budget",
            "context",
            "features",
            "gross_bool",
            "event",
            "stdout_none",
        ):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as tmp:
                output, context = collection(Path(tmp))
                directory = output / "p1-READ"
                if mutation == "context":
                    context = replace(context, generator_sha256="0" * 64)
                elif mutation in ("source", "gross_bool"):
                    result = read(directory / "result.json")
                    result[
                        "source_sha256" if mutation == "source" else "gross_score"
                    ] = "0" * 64 if mutation == "source" else True
                    save(directory / "result.json", result)
                elif mutation in ("event", "stdout_none"):
                    launch = read(directory / "launch.json")
                    launch["stdout"] = (
                        None
                        if mutation == "stdout_none"
                        else "[]\n" + "\n".join(launch["stdout"].splitlines()[1:])
                    )
                    save(directory / "launch.json", launch)
                else:
                    steps = read(directory / "trajectory.json")["steps"]
                    if mutation == "wire":
                        steps[2]["action"]["arguments"]["text"] = "forged"
                        save(directory / "trajectory.json", {"steps": steps})
                    else:
                        if mutation == "state":
                            steps[0]["controller"] = {
                                "macro_public_state_sha256": "0" * 64
                            }
                        elif mutation == "budget":
                            steps[0]["remaining_seconds"] = 9.0
                        else:
                            del steps[0]["public_features"]
                        sync_steps(directory, steps)
                refresh(output)
                self.assertEqual(run_export(output, context)["rows"], [])

    def test_fitting_gate_keeps_the_complete_planned_denominator(self):
        with tempfile.TemporaryDirectory() as tmp:
            output, context = collection(Path(tmp))
            report = run_export(output, context)

            def admit(value, pin=None):
                return exporter.fit_rows(
                    value,
                    "train",
                    context=context,
                    expected_export_sha256=pin or digest(value),
                )

            self.assertEqual(admit(report), report["rows"])
            with self.assertRaises(ValueError):
                admit(report, "0" * 64)
            plan = read(output / "PLAN.json")
            plan["pairs"].append({**plan["pairs"][0], "pair_id": "p2"})
            save(output / "PLAN.json", plan)
            refresh(output, update_plan=True)
            with self.assertRaisesRegex(ValueError, "Incomplete"):
                admit(run_export(output, context))
            report["unknown_pairs"] = True
            with self.assertRaises(ValueError):
                admit(report)

    def test_roles_are_checked_before_reference_and_fixture_scope_is_explicit(self):
        with tempfile.TemporaryDirectory() as tmp:
            output, context = collection(Path(tmp))
            self.assertEqual(
                run_export(output, context, allow_fixtures=False)["rows"], []
            )
            plan = read(output / "PLAN.json")
            root = Path(plan["config"]["material_root"])
            index = read(root / "private/reference-index.v2.json")
            index["case_roles"]["c"] = "confirmation"
            save(root / "private/reference-index.v2.json", index)
            plan["config"]["reference_index_sha256"] = sha(
                (root / "private/reference-index.v2.json").read_bytes()
            )
            save(output / "PLAN.json", plan)
            refresh(output, update_plan=True)
            original, references = common.read_bound, []

            def record(root, pin, **options):
                if pin["path"] == "private/reference.json":
                    references.append(pin)
                return original(root, pin, **options)

            with patch.object(common, "read_bound", side_effect=record):
                self.assertEqual(run_export(output, context)["rows"], [])
            self.assertEqual(references, [])


if __name__ == "__main__":
    unittest.main()
