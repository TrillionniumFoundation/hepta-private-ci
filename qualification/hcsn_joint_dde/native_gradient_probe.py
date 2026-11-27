"""Real Torch CPU physical-backward and fresh-process Adam replay probe.

This is a small fixed-prior physics fit, not task efficacy or full network AD.
Every run uses a fresh directory, and every actor verifies source identities.
"""

import argparse
from dataclasses import asdict
import hashlib
import json
import math
import os
from pathlib import Path
import resource
import subprocess
import sys
import time

import numpy as np
import scipy
import torch

from qualification.hcsn_boundary_audit.spatial_generator import KilledSpatialGenerator
from qualification.hcsn_joint_dde.model import JointModel
from qualification.hcsn_joint_dde.torch_physical import (
    physical_flow,
    graded_physical_flow,
)


def sources():
    root = Path(__file__).parents[1]
    names = [
        "hcsn_joint_dde/model.py",
        "hcsn_joint_dde/sensitivities.py",
        "hcsn_joint_dde/torch_physical.py",
        "hcsn_joint_dde/native_gradient_probe.py",
        "hcsn_boundary_audit/spatial_generator.py",
        "hcsn_boundary_audit/refractory_transport.py",
        "hcsn_joint_dde/graded_sensitivities.py",
        "hcsn_graded/model.py",
        "hcsn_graded/spatial.py",
    ]
    return {
        name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in names
    }


def fixture(geometry):
    if geometry == "uniform":
        model = JointModel(KilledSpatialGenerator(8, 2.0, -0.12, 0.5), 0.53, 0.2, 0.15)
        nodes = np.arange(9) * model.spatial.spacing
        flow = physical_flow
    else:
        from qualification.hcsn_graded.model import GradedJointModel
        from qualification.hcsn_graded.spatial import GradedSpatialGenerator

        model = GradedJointModel(
            GradedSpatialGenerator(16, 2.0, -0.12, 0.5, 4), 0.53, 0.2, 0.15
        )
        nodes = model.spatial.nodes
        flow = graded_physical_flow
    point = np.zeros(len(nodes))
    point[np.argmin(abs(nodes - 0.5))] = 1
    return model, point, np.column_stack((2 * point,)), [0.0, 0.2, 0.6], flow


def runtime_signature():
    return dict(
        python=sys.version,
        torch=str(torch.__version__),
        torch_build=torch.version.git_version,
        numpy=np.__version__,
        scipy=scipy.__version__,
        threads=torch.get_num_threads(),
        default_dtype=str(torch.get_default_dtype()),
        byteorder=sys.byteorder,
    )


def train(args):
    args.output.mkdir(parents=True, exist_ok=False)
    before = sources()
    torch.set_num_threads(1)
    torch.manual_seed(77)
    model, point, marked, times, flow = fixture(args.geometry)
    binding = dict(
        geometry=args.geometry,
        spatial=asdict(model.spatial),
        delay=model.delay,
        reset=model.reset,
        active_reward=model.active_reward,
        hit_reward=model.hit_reward,
        fixed_initial_sha256=hashlib.sha256(
            point.tobytes() + marked.tobytes() + np.asarray(times).tobytes()
        ).hexdigest(),
    )
    theta = torch.nn.Parameter(
        torch.tensor([0.01, -0.12, 0.5, math.exp(0.54), 0.15], dtype=torch.float64)
    )
    optimizer = torch.optim.Adam([theta], lr=5e-5)
    records, start = [], 0
    if args.resume:
        checkpoint = torch.load(args.resume, map_location="cpu", weights_only=True)
        if checkpoint["sources"] != before:
            raise ValueError("checkpoint source identity differs")
        if (
            checkpoint["runtime"] != runtime_signature()
            or checkpoint["binding"] != binding
        ):
            raise ValueError("checkpoint runtime or fixed-input binding differs")
        theta.data.copy_(checkpoint["parameters"])
        optimizer.load_state_dict(checkpoint["optimizer"])
        torch.set_rng_state(checkpoint["rng"])
        start, records = checkpoint["step"], checkpoint["records"]
    for index in range(start, start + args.steps):
        optimizer.zero_grad(set_to_none=True)
        values = flow(
            theta, model, times, point, marked, rtol=2e-10, atol=2e-12, max_step=0.015
        )
        # Full-output layout: interior n*C, then upper/R/M/H/A/Z, C=2.
        channels = marked.shape[1] + 1
        offset = (len(point) - 2) * channels
        features = values[
            -1, [offset + 2 * channels, offset + 3 * channels, offset + 4 * channels]
        ]
        target = torch.tensor(
            [0.4, 0.35, 0.65], dtype=torch.float64
        ) + 0.01 * torch.randn(3, dtype=torch.float64)
        loss = (features - target).square().mean()
        loss.backward()
        if (
            theta.grad is None
            or not torch.isfinite(theta.grad).all()
            or (theta.grad == 0).any()
        ):
            raise ArithmeticError("missing/nonfinite physical gradient")
        gradient = theta.grad.detach().clone()
        optimizer.step()
        records.append(
            dict(
                step=index + 1,
                loss=float(loss.detach()),
                gradient=gradient.tolist(),
                parameters=theta.detach().tolist(),
                target=target.tolist(),
            )
        )
    if before != sources():
        raise ValueError("executing source changed")
    checkpoint = dict(
        schema="hcsn-fixed-prior-physical-adam-v1",
        sources=before,
        parameters=theta.detach().clone(),
        optimizer=optimizer.state_dict(),
        rng=torch.get_rng_state(),
        step=start + args.steps,
        records=records,
        runtime=runtime_signature(),
        binding=binding,
    )
    temporary, final = args.output / "state.pt.tmp", args.output / "state.pt"
    with temporary.open("xb") as stream:
        torch.save(checkpoint, stream)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, final)
    report = dict(
        step=checkpoint["step"],
        records=records,
        source_sha256=before,
        checkpoint_sha256=hashlib.sha256(final.read_bytes()).hexdigest(),
    )
    (args.output / "RESULT.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n"
    )
    print(json.dumps(report, sort_keys=True))


def probe(args):
    args.output.mkdir(parents=True, exist_ok=False)
    wall, cpu = time.perf_counter(), time.process_time()
    before = sources()
    torch.set_num_threads(1)
    model, point, marked, times, flow = fixture(args.geometry)
    theta = torch.tensor(
        [0.01, -0.12, 0.5, math.exp(0.54), 0.15],
        dtype=torch.float64,
        requires_grad=True,
    )
    passed = torch.autograd.gradcheck(
        lambda p: flow(
            p, model, times, point, marked, rtol=2e-11, atol=2e-13, max_step=0.015
        ),
        (theta,),
        eps=1e-4,
        atol=2e-6,
        rtol=3e-4,
        fast_mode=True,
    )
    if not passed:
        raise AssertionError("Torch physical gradcheck failed")
    refused_initial = False
    try:
        flow(theta, model, times, torch.tensor(point, requires_grad=True), marked)
    except ValueError:
        refused_initial = True
    if not refused_initial:
        raise AssertionError("trainable initial-state gradients were silently dropped")
    version_guard = False
    changing = theta.detach().clone().requires_grad_()
    stale = flow(changing, model, times, point, marked)
    with torch.no_grad():
        changing.add_(1e-5)
    try:
        stale.sum().backward()
    except RuntimeError:
        version_guard = True
    if not version_guard:
        raise AssertionError(
            "parameters mutated after forward accepted an old Jacobian"
        )
    unsafe_data_guard = False
    changing = theta.detach().clone().requires_grad_()
    stale = flow(changing, model, times, point, marked)
    changing.data.add_(1e-5)
    try:
        stale.sum().backward()
    except RuntimeError:
        unsafe_data_guard = True
    if not unsafe_data_guard:
        raise AssertionError("unsafe-data parameter mutation accepted an old Jacobian")
    commands = []

    def actor(name, steps, resume=None, expect_success=True):
        command = [
            sys.executable,
            "-B",
            "-m",
            "qualification.hcsn_joint_dde.native_gradient_probe",
            "train",
            "--output",
            str(args.output / name),
            "--steps",
            str(steps),
            "--geometry",
            args.geometry,
        ]
        if resume:
            command.extend(("--resume", str(resume)))
        with (
            (args.output / f"{name}.stdout").open("xb") as stdout,
            (args.output / f"{name}.stderr").open("xb") as stderr,
        ):
            child = subprocess.run(
                command, stdout=stdout, stderr=stderr, check=False, timeout=180
            )
        commands.append(dict(name=name, command=command, returncode=child.returncode))
        if (child.returncode == 0) != expect_success:
            raise AssertionError("actor outcome differs: " + name)

    actor("continuous", 2)
    actor("first", 1)
    actor("resumed", 1, args.output / "first/state.pt")
    whole = torch.load(args.output / "continuous/state.pt", weights_only=True)
    resumed = torch.load(args.output / "resumed/state.pt", weights_only=True)

    def equal(left, right):
        if isinstance(left, torch.Tensor):
            return (
                isinstance(right, torch.Tensor)
                and left.dtype == right.dtype
                and torch.equal(left, right)
            )
        if type(left) is not type(right):
            return False
        if isinstance(left, dict):
            return left.keys() == right.keys() and all(
                equal(left[k], right[k]) for k in left
            )
        if isinstance(left, (list, tuple)):
            return len(left) == len(right) and all(
                equal(a, b) for a, b in zip(left, right)
            )
        return left == right

    if not equal(whole, resumed):
        raise AssertionError(
            "fresh-process model/Adam/RNG/records do not exactly replay"
        )
    damaged = torch.load(args.output / "first/state.pt", weights_only=True)
    damaged["sources"]["hcsn_joint_dde/torch_physical.py"] = "0" * 64
    torch.save(damaged, args.output / "source-mismatch.pt")
    actor(
        "source-mismatch", 1, args.output / "source-mismatch.pt", expect_success=False
    )
    damaged_runtime = torch.load(args.output / "first/state.pt", weights_only=True)
    damaged_runtime["runtime"]["python"] = "different runtime"
    torch.save(damaged_runtime, args.output / "runtime-mismatch.pt")
    actor(
        "runtime-mismatch", 1, args.output / "runtime-mismatch.pt", expect_success=False
    )
    if before != sources():
        raise ValueError("probe sources changed")
    report = dict(
        schema="hcsn-native-physical-autograd-replay-v1",
        source_sha256=before,
        sources_unchanged=True,
        runtime=dict(
            python=sys.version,
            torch=torch.__version__,
            numpy=np.__version__,
            scipy=scipy.__version__,
        ),
        gradcheck=True,
        trainable_initial_state_refused=refused_initial,
        parameter_version_guard=version_guard,
        unsafe_data_mutation_guard=unsafe_data_guard,
        continuous_vs_fresh_process_full_state_exact=True,
        source_mismatch_refused=True,
        runtime_mismatch_refused=True,
        geometry=args.geometry,
        actual_adam_update_calls=4,
        commands=commands,
        records=whole["records"],
        wall_seconds=time.perf_counter() - wall,
        cpu_self_seconds=time.process_time() - cpu,
        cpu_children_seconds=resource.getrusage(resource.RUSAGE_CHILDREN).ru_utime
        + resource.getrusage(resource.RUSAGE_CHILDREN).ru_stime,
        scope="CPU FP64 first-order physical custom VJP with fixed initial probability/content; no network/prior AD",
        complete_hcsn_training_replay=False,
        task_efficacy=False,
        production_qualified=False,
    )
    (args.output / "RESULT.json").write_text(
        json.dumps(report, sort_keys=True, indent=2) + "\n"
    )
    print(json.dumps(report, sort_keys=True))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("probe", "train"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--steps", type=int, choices=(1, 2), default=2)
    parser.add_argument("--resume", type=Path)
    parser.add_argument("--geometry", choices=("uniform", "graded"), default="uniform")
    args = parser.parse_args()
    train(args) if args.mode == "train" else probe(args)


if __name__ == "__main__":
    main()
