"""Small genuine Torch custom-adjoint gate; no optimizer and no forward basis."""

import argparse
from fractions import Fraction
import hashlib
import io
import json
import math
from pathlib import Path
import platform
import resource
import sys
import tarfile
import time
import traceback

import numpy as np
import scipy
import torch

from qualification.hcsn_boundary_audit.spatial_generator import KilledSpatialGenerator
from qualification.hcsn_graded.model import GradedJointModel
from qualification.hcsn_graded.spatial import GradedSpatialGenerator
from qualification.hcsn_joint_dde.model import JointModel
from .torch_flow import amplitude_flow, CallBudget


EPS = 2e-4


def fixture(geometry):
    model = (
        JointModel(KilledSpatialGenerator(7, 2.0, -0.12, 0.5), 0.53, 0.21, 0.15)
        if geometry == "uniform"
        else GradedJointModel(
            GradedSpatialGenerator(12, 2.0, -0.12, 0.5, 3.0), 0.53, 0.21, 0.15
        )
    )
    return (
        model,
        [0.0, 0.13, 0.29, 0.53],
        [
            [Fraction(35, 1000), Fraction(113, 1000)],
            [Fraction(71, 1000), Fraction(71, 1000)],
        ],
    )


def tensors(values):
    return tuple(
        torch.tensor(np.array(v, copy=True), dtype=torch.float64, requires_grad=True)
        for v in values
    )


def flat(values):
    return np.concatenate([np.asarray(value).ravel() for value in values])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-manifest", type=Path, required=True)
    parser.add_argument("--baseline-archive", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    source = json.loads(args.source_manifest.read_text())
    hashes = lambda: {
        name: hashlib.sha256(Path(name).read_bytes()).hexdigest()
        for name in source["source_sha256"]
    }
    before = hashes()
    frozen_path = Path("qualification/hcsn_adjoint_torch/TORCH-SOURCE.json")
    frozen = json.loads(frozen_path.read_text())
    if (
        hashlib.sha256(frozen_path.read_bytes()).hexdigest()
        != source["prefrozen_inventory_sha256"]
        or before != frozen["source_sha256"]
    ):
        raise ValueError("remote-prefrozen Torch source inventory differs")
    if before != source["source_sha256"]:
        raise ValueError("precommitted source manifest differs")
    raw = args.baseline_archive.read_bytes()
    if (
        hashlib.sha256(raw).hexdigest()
        != "85e543dc770257e5470af867415d6d1f55e859fac116f37204fc0e5a6bb2348e"
    ):
        raise ValueError("original independent baseline archive differs")
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as archive:
        members = [
            m for m in archive.getmembers() if m.name.endswith("numpy001/ARRAYS.npz")
        ]
        if len(members) != 1:
            raise ValueError("one pinned original array member required")
        old_bytes = archive.extractfile(members[0]).read()
    if (
        hashlib.sha256(old_bytes).hexdigest()
        != "2dcfe03f2911cb0b6c55b2c24f095d7688d150eb84177d1bb7e4970daa8fa305"
    ):
        raise ValueError("original independent arrays differ")
    old = np.load(io.BytesIO(old_bytes), allow_pickle=False)
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    budget = CallBudget()
    arrays, checks, guards = {}, [], []
    start, cpu = time.perf_counter(), time.process_time()
    error = None

    def check(name, actual, expected, absolute=3e-7, relative=3e-5):
        actual, expected = np.asarray(actual), np.asarray(expected)
        if (
            actual.shape != expected.shape
            or not np.all(np.isfinite(actual))
            or not np.all(np.isfinite(expected))
        ):
            raise ArithmeticError("matching finite raw comparison arrays required")
        arrays[name + "_actual"], arrays[name + "_expected"] = actual, expected
        ratio = abs(actual - expected) / (absolute + relative * abs(expected))
        row = dict(
            name=name,
            coordinates=actual.size,
            absolute_gate=absolute,
            relative_gate=relative,
            maximum_absolute_error=float(np.max(abs(actual - expected))),
            maximum_mixed_gate_ratio=float(np.max(ratio)),
            failures=int(np.count_nonzero(ratio > 1)),
        )
        checks.append(row)
        if row["failures"]:
            raise ArithmeticError("new custom-adjoint gate failed: " + name)

    try:
        for geometry in ("uniform", "graded"):
            values = tuple(old[geometry + "_input" + str(i)] for i in range(4))
            cotangent = old[geometry + "_cotangent"]
            cot = torch.tensor(cotangent, dtype=torch.float64)
            model, times, supports = fixture(geometry)
            budget.label = geometry + "_baseline"
            current = tensors(values)
            output, _ = amplitude_flow(
                model, times, *current, supports=supports, budget=budget
            )
            gradients = torch.autograd.grad((output * cot).sum(), current)
            actual = flat(tuple(g.detach().numpy() for g in gradients))
            reference = np.einsum("tsd,tsc->dc", old[geometry + "_operator"], cotangent)
            n = model.spatial.intervals
            expected = flat(
                (
                    reference[:n, 0],
                    reference[:n, 1:],
                    reference[n:, 0],
                    reference[n:, 1:],
                )
            )
            check(geometry + "_raw_vjp", actual, expected)
            check(
                geometry + "_primal",
                output.detach().numpy(),
                old[geometry + "_primal_direct"],
                absolute=1e-8,
                relative=2e-7,
            )
            arrays[geometry + "_cotangent"] = cotangent
            for i, value in enumerate(values):
                arrays[geometry + "_input" + str(i)] = value
            # Genuine Torch gradcheck perturbs every ambient input coordinate.
            budget.label = geometry + "_gradcheck"

            def objective(*inputs):
                result, _ = amplitude_flow(
                    model, times, *inputs, supports=supports, budget=budget
                )
                scalar = (result * cot).sum()
                budget.forward_records[-1]["objective"] = float(scalar.detach())
                return scalar

            passed = torch.autograd.gradcheck(
                objective,
                tensors(values),
                eps=EPS,
                atol=2e-6,
                rtol=2e-4,
                raise_exception=True,
                check_undefined_grad=True,
                fast_mode=False,
            )
            if not passed:
                raise ArithmeticError("actual Torch gradcheck returned false")
            baseline = flat(values)
            high = np.full(len(baseline), np.nan)
            low = high.copy()
            for record in budget.forward_records:
                if record["label"] != geometry + "_gradcheck":
                    continue
                delta = flat(record["inputs"]) - baseline
                selected = np.flatnonzero(abs(delta) > EPS / 10)
                if len(selected) != 1:
                    continue
                i = int(selected[0])
                if abs(abs(delta[i]) - EPS) > 1e-12:
                    raise ArithmeticError("gradcheck step identity differs")
                target = high if delta[i] > 0 else low
                value = record["objective"]
                if np.isfinite(target[i]) and target[i] != value:
                    raise ArithmeticError("repeated gradcheck scalar differs")
                target[i] = value
            if not np.isfinite(high).all() or not np.isfinite(low).all():
                raise ArithmeticError(
                    "raw all-coordinate gradcheck pairs were not retained"
                )
            (
                arrays[geometry + "_gradcheck_high"],
                arrays[geometry + "_gradcheck_low"],
            ) = high, low
            check(
                geometry + "_retained_coordinate_fd",
                (high - low) / (2 * EPS),
                actual,
                absolute=2e-6,
                relative=2e-4,
            )
            checks.append(
                dict(
                    name=geometry + "_actual_torch_gradcheck",
                    passed=bool(passed),
                    coordinates=len(baseline),
                    eps=EPS,
                    absolute_gate=2e-6,
                    relative_gate=2e-4,
                    fast_mode=False,
                )
            )
            # Explicit normalized client; retain all resulting gradient vectors.
            budget.label = geometry + "_normalized_client"
            model, times, supports = fixture(geometry)
            logits = torch.linspace(
                -0.4, 0.3, n + 2, dtype=torch.float64, requires_grad=True
            )
            marks = (
                (0.2 * torch.sin(torch.arange((n + 2) * 2, dtype=torch.float64)))
                .reshape(n + 2, 2)
                .requires_grad_()
            )
            probabilities = torch.softmax(logits, 0)
            content = probabilities[:, None] * marks
            out, _ = amplitude_flow(
                model,
                times,
                probabilities[:n],
                content[:n],
                probabilities[n:],
                content[n:],
                supports=supports,
                budget=budget,
            )
            gl, gm = torch.autograd.grad((out * cot).sum(), (logits, marks))
            p = probabilities.detach().numpy()
            m = marks.detach().numpy()
            probability_gradient = reference[:, 0] + np.sum(
                reference[:, 1:] * m, axis=1
            )
            expected_logits = p * (
                probability_gradient - np.sum(p * probability_gradient)
            )
            check(geometry + "_normalized_logits", gl.detach().numpy(), expected_logits)
            check(
                geometry + "_normalized_marks",
                gm.detach().numpy(),
                p[:, None] * reference[:, 1:],
            )
            (
                arrays[geometry + "_normalized_probabilities"],
                arrays[geometry + "_normalized_conditional_marks"],
            ) = p, m
        # Normal Torch versions and unsafe .data modifications of all four inputs.
        geometry = "uniform"
        values = tuple(old[geometry + "_input" + str(i)] for i in range(4))
        for kind in ("normal", "unsafe_data", "unsafe_storage_replace"):
            for selected in range(4):
                model, times, supports = fixture(geometry)
                inputs = tensors(values)
                budget.label = f"guard_tensor_{kind}_{selected}"
                output, _ = amplitude_flow(
                    model, times, *inputs, supports=supports, budget=budget
                )
                old_adjoint = budget.adjoint_calls
                if kind == "normal":
                    with torch.no_grad():
                        inputs[selected].view(-1)[0].add_(0.01)
                elif kind == "unsafe_data":
                    inputs[selected].data.view(-1)[0].add_(0.01)
                else:
                    inputs[selected].data = inputs[selected].detach().clone()
                try:
                    output.sum().backward()
                except RuntimeError as exc:
                    guards.append(
                        dict(
                            kind=kind,
                            input=selected,
                            rejected=True,
                            message=str(exc),
                            adjoint_calls=budget.adjoint_calls - old_adjoint,
                        )
                    )
                else:
                    raise ArithmeticError("mutated amplitude input was accepted")
                if budget.adjoint_calls != old_adjoint:
                    raise ArithmeticError("input guard ran an adjoint before rejecting")
        # Caller metadata changes are rejected while the actual VJP snapshot stays fixed.
        for field in (
            "times",
            "supports",
            "reset",
            "delay",
            "discount",
            "mu",
            "sigma",
            "endpoint",
        ):
            model, times, supports = fixture("uniform")
            inputs = tensors(values)
            budget.label = "guard_metadata_" + field
            output, _ = amplitude_flow(
                model, times, *inputs, supports=supports, budget=budget
            )
            old_adjoint = budget.adjoint_calls
            if field == "times":
                times[1] = 0.14
            elif field == "supports":
                supports[0][0] = Fraction(4, 100)
            elif field in ("reset", "delay", "discount"):
                object.__setattr__(
                    model, field, dict(reset=0.54, delay=0.22, discount=0.2)[field]
                )
            else:
                object.__setattr__(
                    model.spatial, field, dict(mu=0.1, sigma=0.6, endpoint=2.1)[field]
                )
            try:
                output.sum().backward()
            except RuntimeError as exc:
                guards.append(
                    dict(
                        kind="metadata",
                        field=field,
                        rejected=True,
                        message=str(exc),
                        adjoint_calls=budget.adjoint_calls - old_adjoint,
                    )
                )
            else:
                raise ArithmeticError("mutated fixed metadata was accepted")
            if budget.adjoint_calls != old_adjoint:
                raise ArithmeticError("metadata guard ran an adjoint before rejecting")
        if len(guards) != 20 or budget.guard_rejections != 20:
            raise ArithmeticError("actual guard denominator differs")
    except Exception as exc:
        error = dict(
            type=type(exc).__name__, message=str(exc), traceback=traceback.format_exc()
        )
    forwards = []
    for i, record in enumerate(budget.forward_records):
        prefix = "forward_" + str(i)
        for j, v in enumerate(record["inputs"]):
            arrays[prefix + "_input" + str(j)] = v
        arrays[prefix + "_output"] = record["output"]
        forwards.append(
            {k: v for k, v in record.items() if k not in ("inputs", "output")}
        )
    backwards = []
    for i, record in enumerate(budget.backward_records):
        arrays["backward_" + str(i) + "_cotangent"] = record["cotangent"]
        arrays["backward_" + str(i) + "_vjp"] = record["vjp"]
        backwards.append(
            {k: v for k, v in record.items() if k not in ("cotangent", "vjp")}
        )
    after = hashes()
    np.savez_compressed(args.output / "ARRAYS.npz", **arrays)
    result = dict(
        status="PASS" if error is None and before == after else "HOLD",
        source_commit=source["source_commit"],
        error=error,
        source_before=before,
        source_after=after,
        source_unchanged=before == after,
        checks=checks,
        guards=guards,
        calls=dict(
            model_forward_calls=budget.forward_calls,
            adjoint_calls=budget.adjoint_calls,
            backward_attempts=budget.backward_attempts,
            guard_rejections=budget.guard_rejections,
            metadata_checks=budget.metadata_checks,
            forward_basis_calls=0,
            optimizer_updates=0,
        ),
        forward_journal=forwards,
        backward_journal=backwards,
        recorded_array_scalars=budget.recorded_scalars,
        arrays_sha256=hashlib.sha256(
            (args.output / "ARRAYS.npz").read_bytes()
        ).hexdigest(),
        gradcheck_eps=EPS,
        validation_wall_seconds=time.perf_counter() - start,
        validation_cpu_seconds=time.process_time() - cpu,
        process_peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        runtime=dict(
            python=sys.version,
            executable=sys.executable,
            platform=platform.platform(),
            torch=torch.__version__,
            torch_git=torch.version.git_version,
            numpy=np.__version__,
            scipy=scipy.__version__,
            torch_threads=torch.get_num_threads(),
            torch_interop_threads=torch.get_num_interop_threads(),
            device="cpu",
        ),
        first_order_only=True,
        fixed_physics_support_only=True,
        discrete_bdf_program_reverse=False,
        n512_qualified=False,
        full_network_qualified=False,
        adam_or_restore_qualified=False,
        rare_tail_relative_qualified=False,
    )
    (args.output / "RESULT.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n"
    )
    print(
        json.dumps(
            dict(
                status=result["status"],
                calls=result["calls"],
                validation_wall_seconds=result["validation_wall_seconds"],
                arrays_sha256=result["arrays_sha256"],
                error=error,
            ),
            sort_keys=True,
        )
    )
    if result["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
