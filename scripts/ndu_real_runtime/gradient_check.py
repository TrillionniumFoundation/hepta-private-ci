"""Tiny CPU FP64 gradient and real-entry checks, using numerical fixtures only.

No fixture, fitted weight or result from this command is scientific task evidence.
Run: PYTHONPATH=scripts:. python -m ndu_real_runtime.gradient_check --output DIR
"""

import argparse
import contextlib
import copy
from dataclasses import asdict
import io
import json
from pathlib import Path
import sys
import time
import traceback
from unittest.mock import patch

import numpy as np
from PIL import Image
import torch

from .controllers import ControlPlan, Controller, PublicState
from .metering import atomic_json, file_sha
from .neural import FittedPredictor, ReceiptPortfolioModel
from .recursive_objective import (
    DifferentiablePlanner,
    exact_policy_objective,
    recursive_terms,
)
from .test_recursive_contract import numerical_records
from .training import _source_pins, parameter_sha


def frozen(model):
    result = copy.deepcopy(model).eval()
    for value in result.parameters():
        value.requires_grad_(False)
    return result


def memory_checks():
    reports = {}
    for core in ("ordinary", "hepta"):
        torch.manual_seed(1729)
        model = ReceiptPortfolioModel(core).double()
        first = torch.randn(2, 126, dtype=torch.float64, requires_grad=True) * 0.05
        following = torch.randn(3, 126, dtype=torch.float64) * 0.05
        metadata = [
            1.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            1.0,
            1.0,
            1.0,
            0.0,
            0.0,
            0.0,
            0.1,
            0.125,
            0.9,
            0.0,
        ]
        initial_hash = parameter_sha(model)
        initial = model.public_state_step(first, metadata)
        continued = model.public_state_step(following, metadata, memory=initial[3])
        reset = model.public_state_step(following, metadata, memory_mode="reset")
        difference = float((continued[0] - reset[0]).detach().abs().max())
        prior_gradient = torch.autograd.grad(continued[0][:24].square().sum(), first)[0]
        assert difference > 1e-10 and float(prior_gradient.norm()) > 0
        replay = model.public_state_step(first, metadata)
        assert (
            torch.equal(initial[0], replay[0]) and parameter_sha(model) == initial_hash
        )
        assert reset[3] is None and all(
            value.shape == (1, 24) for layer in continued[3] for value in layer.values()
        )
        reports[core] = {
            "persistent_reset_max_difference": difference,
            "prior_input_gradient_norm": float(prior_gradient.norm()),
            "episode_reinitialization_exact": True,
            "parameter_bytes_unchanged": True,
        }
    return reports


def gradient_checks():
    torch.manual_seed(23)
    model = ReceiptPortfolioModel("hepta").double()
    reference = frozen(model)
    features = torch.randn(2, 126, dtype=torch.float64) * 0.04
    metadata = [
        1.0,
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        1.0,
        1.0,
        1.0,
        0.0,
        0.0,
        0.0,
        0.1,
        0.125,
        0.9,
        0.0,
    ]
    row = {
        "episode_step": 1,
        "remaining_seconds": 9.0,
        "legal_actions": (
            "PREPARE_ROI",
            "READ_ROI",
            "WRITE_TEXT",
            "RENDER_IMAGE",
            "STOP",
        ),
    }
    parameter = model.project.weight
    direction = torch.sin(
        torch.arange(parameter.numel(), dtype=parameter.dtype).reshape(parameter.shape)
        + 1
    )
    direction = direction / direction.norm()
    reports = []
    for risk in (0.0, 1e-20, 0.25):
        plan = ControlPlan(
            risk=risk,
            horizon=2,
            particles=2,
            max_forecasts=12,
            memory_mode="persistent",
        )

        def current_state():
            before = model.public_state_step(features, metadata)
            return model.public_state_step(features * 0.8, metadata, memory=before[3])[
                0
            ]

        with torch.no_grad():
            fixed_scores = DifferentiablePlanner(reference, plan, 17).action_values(
                current_state(),
                step=row["episode_step"],
                remaining_seconds=row["remaining_seconds"],
                legal_actions=row["legal_actions"],
            )
            fixed_values = torch.stack(list(fixed_scores.values())).detach()
            from .controllers import ACTIONS

            fixed_indices = [ACTIONS.index(name) for name in fixed_scores]

        def objective(name):
            state = current_state()
            if name == "policy":
                # The actual optimizer's surrogate stops dQ/dtheta. Its finite
                # difference must hold the same Q reference fixed on both sides.
                return -exact_policy_objective(
                    model.light_head(state)[fixed_indices], fixed_values
                )
            return recursive_terms(model, reference, state, row, plan, 17)[0]

        for index, name in enumerate(("recursive", "policy")):
            base = objective(name)
            analytical = float(
                (torch.autograd.grad(base, parameter)[0] * direction).sum()
            )
            saved = parameter.detach().clone()
            epsilon = 1e-5
            with torch.no_grad():
                parameter.copy_(saved + epsilon * direction)
                plus = float(objective(name))
                parameter.copy_(saved - epsilon * direction)
                minus = float(objective(name))
                parameter.copy_(saved)
            numerical = (plus - minus) / (2 * epsilon)
            error = abs(analytical - numerical)
            assert error <= 2e-6 + 5e-4 * abs(numerical), (name, analytical, numerical)
            assert abs(analytical) > 1e-12, (name, "zero directional gradient")
            reports.append(
                {
                    "objective": name,
                    "risk": risk,
                    "autograd": analytical,
                    "central_difference": numerical,
                    "absolute_error": error,
                    "epsilon": epsilon,
                }
            )
        state = model.public_state_step(features, metadata)[0]
        public = PublicState(
            tuple(state.detach().tolist()), 9.0, 1, row["legal_actions"]
        )
        _, deployed = Controller(
            "ndu", FittedPredictor(reference, memory_mode="persistent"), plan, seed=17
        ).choose(public)
        planner = DifferentiablePlanner(reference, plan, 17)
        differentiable = planner.action_values(
            state, step=1, remaining_seconds=9.0, legal_actions=row["legal_actions"]
        )
        assert set(differentiable) == set(deployed["predicted_values"])
        parity = max(
            abs(float(value.detach()) - deployed["predicted_values"][name])
            for name, value in differentiable.items()
        )
        assert parity < 1e-10 and planner.calls == deployed["forecast_calls"], parity
        reports.append(
            {
                "risk": risk,
                "deployment_training_value_max_error": parity,
                "same_counted_forecasts": planner.calls,
            }
        )
    z = torch.tensor(0.3, dtype=torch.float64, requires_grad=True)
    values = torch.tensor([0.2, 0.8], dtype=torch.float64)
    objective = exact_policy_objective(torch.stack((z * 0, z)), values)
    derivative = float(torch.autograd.grad(objective, z)[0])
    p = float(z.sigmoid().detach())
    assert abs(derivative - 0.6 * p * (1 - p)) < 1e-14
    assert all(value.grad is None for value in reference.parameters())
    return {
        "directional_checks": reports,
        "binary_exact_policy_derivative": derivative,
        "policy_finite_difference_holds_Q_fixed": True,
        "frozen_reference_has_no_parameter_gradients": True,
    }


def training_and_actor_checks(root):
    from . import actor, training
    from .trajectory import V2_FIELDS

    plan = ControlPlan(
        horizon=2, particles=2, max_forecasts=12, memory_mode="persistent"
    )
    collection_plan = ControlPlan(**{**asdict(plan), "memory_mode": "reset"})
    records = numerical_records(collection_plan)
    path = root / "numerical-fixture-v2.jsonl"
    path.write_text("".join(json.dumps(row) + "\n" for row in records))
    control_path = root / "control.json"
    atomic_json(
        control_path,
        {
            "control": asdict(plan),
            "episode_wall_seconds": 10,
            "fixed_schedule": ["WRITE_TEXT"],
            "seed": 17,
        },
    )
    destination = root / "numeric-fit"
    with contextlib.redirect_stdout(io.StringIO()):
        status = training.main(
            [
                "--records",
                str(path),
                "--output",
                str(destination),
                "--seed",
                "23",
                "--core",
                "hepta",
                "--regime",
                "joint",
                "--controller",
                "ndu",
                "--control-plan",
                str(control_path),
                "--content-epochs",
                "1",
                "--fit-epochs",
                "2",
                "--batch-size",
                "3",
                "--max-wall-seconds",
                "60",
            ]
        )
    receipt = json.loads((destination / "receipt.json").read_text())
    assert status == 0, receipt.get("error")
    fit = receipt["fit_training"]
    assert fit["recursive_objective_applied"] and fit["frozen_reference_unchanged"]
    assert (
        fit["recursive_gradient_into_content"] > 0
        and fit["policy_gradient_into_content"] > 0
    )
    assert receipt["records"]["complete_v2_chains"] == 1
    assert (
        receipt["replayed_from_memory_modes"] == ["reset"]
        and receipt["memory_mode_changed_during_replay"]
    )
    assert not receipt["on_policy_or_counterfactual_return_claimed"]
    legacy = [{k: v for k, v in row.items() if k not in V2_FIELDS} for row in records]
    for row in legacy:
        row["schema"] = "ndu.real.training-transition.v1"
    legacy_path = root / "numerical-fixture-v1.jsonl"
    legacy_path.write_text("".join(json.dumps(row) + "\n" for row in legacy))
    with contextlib.redirect_stdout(io.StringIO()):
        legacy_status = training.main(
            [
                "--records",
                str(legacy_path),
                "--output",
                str(root / "legacy-fit"),
                "--seed",
                "23",
                "--core",
                "hepta",
                "--regime",
                "joint",
                "--controller",
                "ndu",
                "--content-epochs",
                "1",
                "--fit-epochs",
                "1",
                "--batch-size",
                "3",
                "--max-wall-seconds",
                "60",
            ]
        )
    legacy_receipt = json.loads((root / "legacy-fit/receipt.json").read_text())
    assert (
        legacy_status == 0
        and not legacy_receipt["fit_training"]["recursive_objective_applied"]
    ), legacy_receipt.get("error")

    public = root / "actor-public"
    public.mkdir()
    Image.new("RGB", (100, 100), "white").save(public / "overview.png")
    packet = {
        "schema": "ndu.real.public-case.v1",
        "case_id": "numerical-fixture",
        "prompt": "Read company",
        "public_text": "ACME",
        "overview": {},
        "source_size": {"width": 100, "height": 100},
        "initial_delivery": {"text": None, "image": None},
        "requirements": {"text": True, "image": True},
        "action_contract": {},
    }
    atomic_json(public / "case.json", packet)
    states = [
        {
            "schema": "ndu.real.actor-step.v1",
            "case_id": "numerical-fixture",
            "step": step,
            "remaining_seconds": float(10 - step),
            "prepared_roi": None,
            "observation": {
                "path": "overview.png",
                "sha256": file_sha(public / "overview.png"),
                "bbox": [0, 0, 100, 100],
                "kind": "overview",
            },
            "delivery": {"text": None if not step else "ACME", "image": None},
            "text_committed": False,
            "forced_action": "WRITE_TEXT" if not step else "STOP",
        }
        for step in range(2)
    ]
    arguments = [
        "actor",
        "--public-dir",
        str(public),
        "--weights",
        str(destination / "weights.pt"),
        "--expected-weights-sha256",
        receipt["weights_sha256"],
        "--core",
        "hepta",
        "--controller",
        "tuned_fixed",
        "--control-plan",
        str(control_path),
        "--deployment-profile",
        str(destination / "deployment-profile.json"),
        "--operation-id",
        "numeric-actor",
        "--max-decisions",
        "2",
        "--training-exploration",
    ]
    output = io.StringIO()
    # Real actor.run parses public packets, loads pinned weights, carries state,
    # emits decisions and writes meters. Only the external OCR boundary is mocked.
    actor_directory = root / "actor-working"
    actor_directory.mkdir()
    import os

    previous = Path.cwd()
    try:
        os.chdir(actor_directory)
        with (
            patch.object(sys, "argv", arguments),
            patch.object(
                sys, "stdin", io.StringIO("".join(json.dumps(x) + "\n" for x in states))
            ),
            patch.object(
                actor,
                "extract_ocr",
                return_value=([{}, {}], {"numerical_fixture": True}),
            ),
            patch.object(
                actor,
                "candidate_features",
                return_value=(
                    records[0]["candidate_metadata"],
                    np.asarray(records[0]["candidate_features"], dtype=np.float32),
                ),
            ),
            contextlib.redirect_stdout(output),
        ):
            assert actor.run() == 0
    finally:
        os.chdir(previous)
    messages = [json.loads(line) for line in output.getvalue().splitlines()]
    assert len(messages) == 3 and all(
        value["parameters_unchanged"] for value in messages[1:]
    )
    assert (
        messages[1]["memory_sha256"]
        and messages[1]["memory_sha256"] != messages[2]["memory_sha256"]
    )
    wrong_control = json.loads(control_path.read_text())
    wrong_control["control"]["horizon"] = 1
    wrong_path = root / "different-horizon.json"
    atomic_json(wrong_path, wrong_control)
    changed_arguments = list(arguments)
    changed_arguments[changed_arguments.index("--control-plan") + 1] = str(wrong_path)
    with (
        patch.object(sys, "argv", changed_arguments),
        contextlib.redirect_stdout(io.StringIO()),
    ):
        try:
            actor.run()
        except ValueError as error:
            assert "profile differs" in str(error)
        else:
            raise AssertionError(
                "Actor accepted a planner horizon different from its training contract"
            )
    return {
        "training_status": receipt["status"],
        "recursive_gradient_norm": fit["recursive_gradient_into_content"],
        "policy_gradient_norm": fit["policy_gradient_into_content"],
        "reference_unchanged": True,
        "legacy_reset_status": legacy_receipt["status"],
        "actor_decisions": len(messages) - 1,
        "actor_memory_changed_across_actions": True,
        "different_planner_profile_rejected": True,
        "reset_collection_reencoded_with_persistent_training_memory": True,
        "fixture_is_real_task_evidence": False,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=False)
    torch.set_num_threads(1)
    if torch.get_num_interop_threads() != 1:
        torch.set_num_interop_threads(1)
    torch.use_deterministic_algorithms(True)
    started = time.perf_counter()
    report = {
        "schema": "ndu.real.recursive-numerical-check.v1",
        "status": "STARTED",
        "device": "cpu",
        "torch_version": torch.__version__,
        "source_pins": _source_pins(),
        "check_source_sha256": file_sha(__file__),
        "scientific_task_evidence": False,
        "adoption_authorized": False,
    }
    try:
        report["memory"] = memory_checks()
        report["gradients"] = gradient_checks()
        report["entrypoints"] = training_and_actor_checks(root)
        report["status"] = "PASS"
    except Exception as error:
        report.update(
            status="FAILED", error={"type": type(error).__name__, "message": str(error)}
        )
        (root / "traceback.txt").write_text(traceback.format_exc())
    report["wall_seconds"] = time.perf_counter() - started
    atomic_json(root / "receipt.json", report)
    print(json.dumps(report, sort_keys=True, allow_nan=False))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
