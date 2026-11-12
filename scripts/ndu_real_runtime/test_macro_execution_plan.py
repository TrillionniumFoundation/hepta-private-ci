"""Frozen-input regressions using manufactured deployments, never efficacy data."""

from copy import deepcopy
from dataclasses import asdict, replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ndu_real_materials import common, evaluator
from . import macro_actor, macro_realization
from .controllers import ControlPlan
from .critic_context import context_digest
from .macro_execution_plan import (
    check_inputs,
    shared_context,
    source_inventory,
    validate_plan,
)
from .metacontrol_macro_contract import digest, sha
from .objective import utility_profile
from .test_macro_actor import fixture_deployment
from .test_macro_policy import CONTEXT


def plan_fixture(root):
    inputs = root / "inputs"
    inputs.mkdir()
    runtime = Path(__file__).resolve().parent
    config = {
        "scripts_root": str(runtime.parent),
        "repository_root": str(runtime.parents[1]),
        "runtime_roots": [str(runtime.parents[1])],
        "material_root": str(inputs),
        "episode_wall_seconds": 60.0,
        "latency_weight": 0.01,
        "isolator_sha256": "9" * 64,
        "rubric_sha256": "f" * 64,
        "evaluator_sha256": sha(Path(evaluator.__file__).read_bytes()),
    }
    weights, control = inputs / "weights", inputs / "control.json"
    weights.write_bytes(b"fixture")
    objective = ControlPlan()
    common.write_json(
        control,
        {
            "control": asdict(objective),
            "episode_wall_seconds": 60.0,
            "fixed_schedule": [],
            "seed": 7,
        },
    )
    content = sha(weights.read_bytes())
    context = replace(
        CONTEXT,
        encoder_sha256=content,
        answer_sha256=content,
        generator_sha256=sha((runtime / "ocr.py").read_bytes()),
        public_state_sha256=macro_actor.codec_sha256(),
        **macro_actor.host_context(config, digest(utility_profile(objective))),
    )
    profiles, arms, partitions = {}, [], None
    for name in ("STOP", "tuned-fixed"):
        path = inputs / f"{name}.json"
        deployment = fixture_deployment(
            name, weights=content, control=digest(asdict(objective)), context=context
        )
        common.write_json(path, deployment)
        checkpoint = common.strict_json(deployment["checkpoint_utf8"])
        partitions = {
            "fit": checkpoint["fit_sources"],
            "calibration": checkpoint["calibration_sources"],
            "evaluation": ["s", "t"],
        }
        profiles[name] = {
            "core": "ordinary",
            "controller": "light",
            "memory_mode": "reset",
            "weights": str(weights),
            "model_sha256": content,
            "control_plan": str(control),
            "control_plan_sha256": sha(control.read_bytes()),
            "macro_policy": {"path": str(path), "sha256": sha(path.read_bytes())},
        }
        arms.append(
            {
                "arm_id": name,
                "content_mode": "off",
                "control_mode": "off",
                "policy": name,
                "content_sha256": content,
                "critic_context_sha256": context_digest(context),
            }
        )
    contexts, registered = [], []
    for source, case_id in (("s", "c"), ("t", "d")):
        record = {"source_id": source, "case_id": case_id, "seed": 7}
        reference = inputs / f"reference-{source}.json"
        common.write_json(
            reference,
            {
                "case_id": case_id,
                "source_group": source,
                "role": "train",
                "field": "company",
                "expected_text": "ACME LTD",
            },
        )
        contexts.append(record)
        registered.append(
            {
                **record,
                "read_condition": "repeat",
                "case": {
                    "id": case_id,
                    "source_id": source,
                    "role": "train",
                    "source_sha256": digest(source),
                    "reference": common.binding(reference, inputs),
                },
            }
        )
    cohort = {
        "schema": "ndu.real.macro-cohort.v1",
        "contexts": contexts,
        "arms": arms,
        "partitions": partitions,
        "shared": shared_context(config, objective),
        "factorial": None,
        "one_off_costs": {
            name: {k: None for k in ("fit", "calibration", "tuning")}
            for name in profiles
        },
    }
    return {
        "schema": "ndu.real.macro-execution-plan.v1",
        "cohort": cohort,
        "cohort_sha256": digest(cohort),
        "config": config,
        "registered_cases": registered,
        "profiles": profiles,
        "action_budget_seconds": 10.0,
        "source_pins": source_inventory(config),
        "observer_sha256": digest(macro_realization.source_manifest()),
    }


class MacroExecutionPlanTests(unittest.TestCase):
    def test_source_control_observer_and_output_roots_are_frozen(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = plan_fixture(root)
            validate_plan(plan, digest(plan))
            check_inputs(plan, root / "run")
            deployment = common.strict_json(
                Path(plan["profiles"]["STOP"]["macro_policy"]["path"]).read_bytes()
            )
            fitted_hash = next(
                iter(
                    common.strict_json(deployment["checkpoint_utf8"])[
                        "source_bindings"
                    ].values()
                )
            )
            changes = [
                lambda p: p.update(observer_sha256="0" * 64),
                lambda p: p["source_pins"].pop(),
                lambda p: p["config"].update(scripts_root=str(root)),
                lambda p: p["profiles"]["STOP"]["macro_policy"].update(sha256="0" * 64),
                lambda p: p["config"].update(runtime_roots=[str(root)]),
                lambda p: p["cohort"]["shared"].update(legal_actions_sha256="0" * 64),
                lambda p: p["registered_cases"][0]["case"].update(
                    source_sha256=fitted_hash
                ),
            ]
            for index, change in enumerate(changes):
                changed = deepcopy(plan)
                change(changed)
                with self.subTest(index=index), self.assertRaises(ValueError):
                    check_inputs(changed, root / "run")

    def test_missing_duplicate_sealed_or_aliased_registered_sources_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan = plan_fixture(Path(tmp))
            for change in (
                lambda p: p["registered_cases"].pop(),
                lambda p: p["registered_cases"].append(p["registered_cases"][0]),
                lambda p: p["registered_cases"][0]["case"].update(role="confirmation"),
                lambda p: p["registered_cases"][0]["case"].update(
                    source_sha256=digest("t")
                ),
                lambda p: p["registered_cases"][0].update(seed=True),
            ):
                changed = deepcopy(plan)
                change(changed)
                with self.assertRaises(ValueError):
                    validate_plan(changed, digest(changed))
            changed = deepcopy(plan)
            changed["action_budget_seconds"] = 20
            with self.assertRaises(ValueError):
                validate_plan(changed, digest(plan))

    def test_private_reference_read_root_is_rejected_without_reading_its_body(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = plan_fixture(root)
            reference = (
                root
                / "inputs"
                / plan["registered_cases"][0]["case"]["reference"]["path"]
            )
            for exposed in (str(root / "inputs"), str(reference)):
                changed = deepcopy(plan)
                changed["config"]["runtime_roots"].append(exposed)
                with patch(
                    "ndu_real_runtime.macro_execution_plan.read_pin",
                    side_effect=AssertionError(
                        "no input read before boundary rejection"
                    ),
                ):
                    with self.assertRaisesRegex(ValueError, "private reference"):
                        check_inputs(changed, root / "run")
            check_inputs(plan, root / "run")


if __name__ == "__main__":
    unittest.main()
