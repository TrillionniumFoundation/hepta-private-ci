"""Scorer contract tests; no actor execution or scientific benefit is claimed."""

import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ndu_real_materials.common import binding, write_json
from .candidate_memory import CandidateScope
from .candidate_retention_report import unknown_episode
from .candidate_runtime import CandidateRuntime, PROFILE_SCHEMA, read_audit
from .candidate_selector import PROFILE, BINDINGS
from .objective import canonical_sha
from .selector_runtime import SelectorRuntime
from . import candidate_selection_report as report


def planned():
    memory = {
        "schema": PROFILE_SCHEMA,
        "mode": "bounded",
        "max_entries": 128,
        "max_serialized_bytes": 524288,
    }
    rows = []
    for mode in report.MODES:
        selector = {
            "schema": PROFILE["schema"],
            "mode": mode,
            "profile_sha256": canonical_sha(PROFILE),
        }
        rows.append(
            {
                "original_operation_id": "pair-" + mode,
                "pair_id": "pair",
                "case_id": "case",
                "source_group_id": "source",
                "episode_group": "episode",
                "split": "development",
                "source_width": 100,
                "source_height": 100,
                "selector_mode": mode,
                "task_family": "text_sufficient",
                "candidate_memory_profile": memory,
                "candidate_memory_profile_sha256": canonical_sha(memory),
                "candidate_selector_profile": selector,
                "candidate_selector_profile_sha256": canonical_sha(selector),
                **{
                    k: "b" * 64
                    for k in (
                        *report.PINS,
                        "source_sha256",
                        "public_case_sha256",
                        "control_plan_sha256",
                    )
                },
            }
        )
    return {
        "schema": "ndu.real.candidate-selection-plan.v1",
        "evaluation_role": "prospective_development_validation",
        "confirmation_evaluated": False,
        "selector_profile": PROFILE,
        "selector_profile_sha256": canonical_sha(PROFILE),
        "excluded_source_groups": [],
        "episodes": rows,
    }


def sidecars(root, *, no_write=False):
    expected = planned()["episodes"][0]
    operation = expected["original_operation_id"]
    directory = root / "episodes" / operation / "actor-output"
    directory.mkdir(parents=True)
    scope = CandidateScope(operation, "case", "b" * 64, 100, 100)
    pins = {k: expected[k] for k in BINDINGS}
    memory = CandidateRuntime(expected["candidate_memory_profile"], scope, pins)
    selector = SelectorRuntime(expected["candidate_selector_profile"], memory)
    candidates = [
        {"text": "noise", "bbox": [0, 0, 50, 10], "origin": "pixel_ocr"},
        {"text": "RM 12.50", "bbox": [0, 80, 50, 90], "origin": "pixel_ocr"},
    ]
    vector = [0.0] * 126
    vector[100], vector[104], vector[107], vector[119] = 0.9, 1.0, 1.0, 1.0
    offered, features = memory.offer(0, candidates, [list(vector), list(vector)])
    index = selector.select(0, "total", offered, features, [2.0, 1.0])
    state = {
        "step": 0,
        "observation": {
            "path": "overview.png",
            "sha256": "c" * 64,
            "bbox": [0, 0, 100, 100],
            "kind": "overview",
        },
    }
    action = {
        "schema": "ndu.real.actor-action.v1",
        "action": "PREPARE_ROI" if no_write else "WRITE_TEXT",
        "arguments": {"bbox": [0, 0, 50, 10]}
        if no_write
        else {"text": candidates[index]["text"]},
    }
    mem = memory.record(directory, state, action, index)
    sel = selector.record(directory, state, action, mem)
    audits = [
        {
            "value": read_audit(directory, mem, {"step": 0}),
            "sha256": mem["sha256"],
            "bytes": mem["bytes"],
        }
    ]
    trajectory = {"steps": [{"action": action, "selector_audit": sel}]}
    selectors = [
        {**sel, "path": (directory / sel["path"]).relative_to(root).as_posix()}
    ]
    if no_write:
        state = {**state, "step": 1}
        action = {
            "schema": "ndu.real.actor-action.v1",
            "action": "STOP",
            "arguments": {},
        }
        mem = memory.record(directory, state, action)
        sel = selector.record(directory, state, action, mem)
        audits.append(
            {
                "value": read_audit(directory, mem, {"step": 1}),
                "sha256": mem["sha256"],
                "bytes": mem["bytes"],
            }
        )
        trajectory["steps"].append({"action": action, "selector_audit": sel})
        selectors.append(
            {**sel, "path": (directory / sel["path"]).relative_to(root).as_posix()}
        )
    return (
        expected,
        {"field": "total", "expected_text": "12.50"},
        trajectory,
        audits,
        selectors,
    )


class SelectionReportTests(unittest.TestCase):
    def test_plan_rejects_changed_inputs_duplicate_pairs_and_sealed_sources(self):
        original = planned()
        self.assertEqual(len(report.validate_plan(original)), 2)
        for key, value in (
            ("weights_sha256", "a" * 64),
            ("split", "confirmation"),
            ("selector_mode", "public_rule"),
        ):
            bad = copy.deepcopy(original)
            bad["episodes"][0][key] = value
            with self.assertRaises(ValueError):
                report.validate_plan(bad)
        bad = copy.deepcopy(original)
        bad["excluded_source_groups"] = ["source"]
        with self.assertRaises(ValueError):
            report.validate_plan(bad)
        bad = copy.deepcopy(original)
        for row in copy.deepcopy(bad["episodes"]):
            row["pair_id"] = "duplicate"
            row["original_operation_id"] += "-again"
            bad["episodes"].append(row)
        with self.assertRaises(ValueError):
            report.validate_plan(bad)

    def test_missing_episode_stays_in_primary_denominator_and_not_shadow_delivery(self):
        full = planned()["episodes"]
        rows = []
        for expected in full:
            row = unknown_episode(expected, "retained no-op")
            row.update(
                evidence_status="VERIFIED",
                terminal_status="Completed",
                unconditional_success=True,
                no_op_success=True,
                initial_correct=True,
                candidate_mediated_delivered=False,
            )
            rows.append(row)
        result = report.summarize(full, rows[:1])
        self.assertEqual(
            (
                result["planned_episodes"],
                result["paired_terminal_contrast"]["unknown_pairs"],
            ),
            (2, 1),
        )
        self.assertIsNone(result["paired_terminal_contrast"]["value"])
        self.assertEqual(
            result["panels"]["frozen_neural"]["shadow_at_actual_anchor"][
                "observed_supports"
            ],
            0,
        )
        self.assertFalse(
            result["panels"]["frozen_neural"]["shadow_at_actual_anchor"][
                "counterfactual_delivery_estimated"
            ]
        )
        with self.assertRaises(ValueError):
            report.summarize(full, rows + rows)

    def test_real_shared_support_reader_reconstructs_two_choices_and_rejects_rehashed_forgery(
        self,
    ):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            expected, reference, trajectory, audits, pins = sidecars(root)
            self.assertEqual(
                report.shadow_choices(
                    root, expected, reference, trajectory, audits, pins
                ),
                {"available": True, "frozen_neural": False, "public_rule": True},
            )
            path = root / pins[0]["path"]
            value = json.loads(path.read_text())
            value["receipt"]["public_rule_index"] = 0
            raw = (
                json.dumps(
                    value,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                    allow_nan=False,
                )
                + "\n"
            ).encode()
            path.write_bytes(raw)
            pin = binding(path, root)
            pins[0] = pin
            trajectory["steps"][0]["selector_audit"] = {**pin, "path": path.name}
            with self.assertRaises(ValueError):
                report.shadow_choices(
                    root, expected, reference, trajectory, audits, pins
                )

    def test_unprocessed_final_stop_never_reuses_earlier_available_candidate(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            args = sidecars(root, no_write=True)
            self.assertEqual(
                report.shadow_choices(root, *args),
                dict.fromkeys(("available", *report.MODES)),
            )
            args[-1][1] = None
            with self.assertRaises(FileNotFoundError):
                report.shadow_choices(root, *args)

    def test_generate_keeps_all_absent_artifacts_and_rejects_wrong_original_plan_hash(
        self,
    ):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run, materials, source = (
                root / name for name in ("run", "materials", "source")
            )
            for path in (run, materials, source):
                path.mkdir()
            plan = planned()
            source_pins = []
            for relative in report.SOURCES:
                path = source / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("pinned test source\n")
                source_pins.append(binding(path, source))
            rubric = materials / "rubric.json"
            write_json(rubric, {"test_profile": True})
            plan.update(
                source_pins=source_pins,
                evaluator_sha256=next(
                    p["sha256"]
                    for p in source_pins
                    if p["path"].endswith("/evaluator.py")
                ),
                rubric_sha256=binding(rubric, materials)["sha256"],
            )
            reference = materials / "reference.json"
            write_json(reference, {"field": "total", "expected_text": "12.50"})
            index = materials / "private/reference-index.v2.json"
            write_json(
                index,
                {
                    "schema": "ndu.real.reference-index.v2",
                    "rubric": binding(rubric, materials),
                    "cases": {"case": binding(reference, materials)},
                    "case_roles": {"case": "development"},
                },
            )
            plan["reference_index_sha256"] = binding(index, materials)["sha256"]
            write_json(run / "PLAN.json", plan)
            psha = binding(run / "PLAN.json", run)["sha256"]
            evidence = {
                "schema": "ndu.real.candidate-selection-evidence.v1",
                "plan_sha256": psha,
                "episodes": [],
            }
            write_json(run / "EVIDENCE.json", evidence)
            esha = binding(run / "EVIDENCE.json", run)["sha256"]
            with patch.object(report, "REPOSITORY", source):
                result = report.generate(run, materials, psha, esha)
                self.assertEqual(
                    (result["planned_episodes"], len(result["episodes"])), (2, 2)
                )
                self.assertEqual(
                    result["panels"]["public_rule"]["evidence_status"], {"UNKNOWN": 1}
                )
                with self.assertRaises(ValueError):
                    report.generate(run, materials, "0" * 64, esha)
                target = run / "result-target.json"
                write_json(target, {})
                (run / "result.json").symlink_to(target.name)
                result_pin = {**binding(target, run), "path": "result.json"}
                (run / "EVIDENCE.json").unlink()
                evidence["episodes"] = [
                    {
                        "original_operation_id": plan["episodes"][0][
                            "original_operation_id"
                        ],
                        "result": result_pin,
                    }
                ]
                write_json(run / "EVIDENCE.json", evidence)
                changed = report.generate(
                    run, materials, psha, binding(run / "EVIDENCE.json", run)["sha256"]
                )
                self.assertEqual(
                    [row["evidence_status"] for row in changed["episodes"]],
                    ["REJECTED", "UNKNOWN"],
                )
                self.assertIn("symbolic links", changed["episodes"][0]["reason"])
