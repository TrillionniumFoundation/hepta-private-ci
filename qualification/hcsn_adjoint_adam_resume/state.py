"""Primitive/tensor-only complete checkpoint schema and atomic publication."""

import hashlib
import io
import os
import platform
import random
import sys
import tarfile
from fractions import Fraction
from pathlib import Path

import numpy as np
import scipy
import torch

from qualification.hcsn_boundary_audit.spatial_generator import KilledSpatialGenerator
from qualification.hcsn_graded.model import GradedJointModel
from qualification.hcsn_graded.spatial import GradedSpatialGenerator
from qualification.hcsn_initial_adjoint.solver import freeze_problem
from qualification.hcsn_joint_dde.model import JointModel

NAMES = ("active", "content", "phase_mass", "phase_content")
PROTOCOL = "hcsn-adjoint-four-amplitudes-adam-resume-20261112-c06d-stage1"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def fixture(geometry, archive):
    raw = Path(archive).read_bytes()
    if (
        hashlib.sha256(raw).hexdigest()
        != "85e543dc770257e5470af867415d6d1f55e859fac116f37204fc0e5a6bb2348e"
    ):
        raise ValueError("original baseline archive differs")
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as tar:
        member = next(
            m for m in tar.getmembers() if m.name.endswith("numpy001/ARRAYS.npz")
        )
        data = tar.extractfile(member).read()
    if (
        hashlib.sha256(data).hexdigest()
        != "2dcfe03f2911cb0b6c55b2c24f095d7688d150eb84177d1bb7e4970daa8fa305"
    ):
        raise ValueError("baseline array identity differs")
    with np.load(io.BytesIO(data), allow_pickle=False) as arrays:
        inputs = [
            torch.tensor(
                arrays[geometry + "_input" + str(i)].copy(), dtype=torch.float64
            )
            for i in range(4)
        ]
        target = torch.tensor(
            arrays[geometry + "_primal_direct"].copy(), dtype=torch.float64
        )
    model = (
        JointModel(KilledSpatialGenerator(7, 2.0, -0.12, 0.5), 0.53, 0.21, 0.15)
        if geometry == "uniform"
        else GradedJointModel(
            GradedSpatialGenerator(12, 2.0, -0.12, 0.5, 3.0), 0.53, 0.21, 0.15
        )
    )
    times = [0.0, 0.13, 0.29, 0.53]
    supports = [
        [Fraction(35, 1000), Fraction(113, 1000)],
        [Fraction(71, 1000), Fraction(71, 1000)],
    ]
    problem = freeze_problem(model, times, supports)
    original = dict(
        identity=problem.identity,
        model_repr=repr(model),
        times=list(map(str, problem.times)),
        supports=[list(map(str, p)) for p in problem.supports],
        delay=str(problem.delay),
        discount=problem.discount,
    )
    for name in ("transient", "lower", "upper", "reset", "nodes"):
        original[name] = torch.tensor(
            np.array(getattr(problem, name), copy=True), dtype=torch.float64
        )
    return model, times, supports, inputs, target, original


def runtime():
    return dict(
        python=sys.version,
        executable=sys.executable,
        platform=platform.platform(),
        torch=str(torch.__version__),
        torch_git=str(torch.version.git_version),
        numpy=str(np.__version__),
        scipy=str(scipy.__version__),
        torch_threads=torch.get_num_threads(),
        torch_interop_threads=torch.get_num_interop_threads(),
        device="cpu",
    )


def capture_rng():
    name, keys, position, gaussian, cached = np.random.get_state()
    return dict(
        torch_cpu=torch.get_rng_state().clone(),
        python=random.getstate(),
        numpy=dict(
            name=str(name),
            keys=keys.tolist(),
            position=int(position),
            has_gaussian=int(gaussian),
            cached_gaussian=float(cached),
        ),
    )


def restore_rng(state):
    torch.set_rng_state(state["torch_cpu"])
    random.setstate(state["python"])
    r = state["numpy"]
    np.random.set_state(
        (
            r["name"],
            np.array(r["keys"], dtype=np.uint32),
            r["position"],
            r["has_gaussian"],
            r["cached_gaussian"],
        )
    )


def clones(parameters):
    return {name: value.detach().clone() for name, value in zip(NAMES, parameters)}


def gradients(parameters):
    if any(value.grad is None for value in parameters):
        raise ValueError("complete gradient buffers required")
    return {name: value.grad.detach().clone() for name, value in zip(NAMES, parameters)}


def validate_values(values, original):
    if set(values) != set(NAMES):
        raise ValueError("four named tensors required")
    for name in NAMES:
        value = values[name]
        if (
            not isinstance(value, torch.Tensor)
            or value.dtype != torch.float64
            or value.device.type != "cpu"
            or value.shape != original[name].shape
            or not bool(torch.isfinite(value).all())
        ):
            raise ValueError("finite CPU FP64 four-tensor shapes differ")
    if bool((values["active"] < 0).any()) or bool((values["phase_mass"] < 0).any()):
        raise ValueError("probability domain violated")


def fingerprint(value):
    if isinstance(value, torch.Tensor):
        raw = (
            value.detach()
            .cpu()
            .contiguous()
            .reshape(-1)
            .view(torch.uint8)
            .numpy()
            .tobytes()
        )
        return dict(
            kind="tensor",
            device=str(value.device),
            layout=str(value.layout),
            dtype=str(value.dtype),
            shape=list(value.shape),
            stride=list(value.stride()),
            offset=value.storage_offset(),
            sha256=hashlib.sha256(raw).hexdigest(),
        )
    if isinstance(value, dict):
        return dict(
            kind="dict",
            items=[
                (fingerprint(k), fingerprint(v))
                for k, v in sorted(
                    value.items(),
                    key=lambda pair: (type(pair[0]).__name__, str(pair[0])),
                )
            ],
        )
    if isinstance(value, (tuple, list)):
        return dict(kind=type(value).__name__, items=[fingerprint(v) for v in value])
    if type(value) not in (str, int, float, bool, type(None)):
        raise ValueError("unsupported checkpoint metadata type")
    return (
        dict(kind="float", hex=value.hex())
        if type(value) is float
        else dict(kind=type(value).__name__, value=value)
    )


def same(left, right):
    return fingerprint(left) == fingerprint(right)


def validate_checkpoint(payload, source, current_runtime, snapshot, initial):
    required = {
        "protocol",
        "source",
        "runtime",
        "original_snapshot",
        "original_inputs",
        "parameters",
        "gradients",
        "adam",
        "step",
        "cursor",
        "rng",
    }
    if not isinstance(payload, dict) or set(payload) != required:
        raise ValueError("complete checkpoint required, including Adam")
    if (
        payload["protocol"] != PROTOCOL
        or not same(payload["source"], source)
        or payload["runtime"] != current_runtime
    ):
        raise ValueError("checkpoint source/runtime binding differs")
    if not same(payload["original_snapshot"], snapshot) or not same(
        payload["original_inputs"], initial
    ):
        raise ValueError("original fixed snapshot differs")
    step = payload["step"]
    if (
        type(step) is not int
        or not 1 <= step <= 2
        or type(payload["cursor"]) is not int
        or payload["cursor"] != step
    ):
        raise ValueError("step/cursor differs")
    validate_values(payload["parameters"], initial)
    if set(payload["gradients"]) != set(NAMES):
        raise ValueError("four saved gradient buffers required")
    for name in NAMES:
        value = payload["gradients"][name]
        if (
            value.dtype != torch.float64
            or value.shape != initial[name].shape
            or not bool(torch.isfinite(value).all())
        ):
            raise ValueError("saved gradient buffers invalid")
    adam = payload["adam"]
    if (
        set(adam) != {"state", "param_groups"}
        or set(adam["state"]) != set(range(4))
        or len(adam["param_groups"]) != 1
        or adam["param_groups"][0]["params"] != list(range(4))
    ):
        raise ValueError("complete four-parameter Adam state required")
    group = adam["param_groups"][0]
    expected_group = dict(
        lr=1e-4,
        betas=(0.9, 0.999),
        eps=1e-8,
        weight_decay=0,
        foreach=False,
        fused=False,
        amsgrad=False,
        maximize=False,
        capturable=False,
        differentiable=False,
    )
    if any(group.get(k) != v for k, v in expected_group.items()):
        raise ValueError("Adam hyperparameter binding differs")
    for i, name in enumerate(NAMES):
        state = adam["state"][i]
        if (
            set(state) != {"step", "exp_avg", "exp_avg_sq"}
            or not isinstance(state["step"], torch.Tensor)
            or state["step"].numel() != 1
            or float(state["step"]) != step
        ):
            raise ValueError("Adam step/moments missing or inconsistent")
        for key in ("exp_avg", "exp_avg_sq"):
            if (
                state[key].dtype != torch.float64
                or state[key].shape != initial[name].shape
                or not bool(torch.isfinite(state[key]).all())
            ):
                raise ValueError("Adam moment shape/dtype differs")
        if bool((state["exp_avg_sq"] < 0).any()):
            raise ValueError("negative second moment")
    if (
        set(payload["rng"]) != {"torch_cpu", "python", "numpy"}
        or payload["rng"]["torch_cpu"].dtype != torch.uint8
        or payload["rng"]["torch_cpu"].shape != torch.get_rng_state().shape
    ):
        raise ValueError("complete CPU RNG state required")


def load(path):
    if not 0 < Path(path).stat().st_size <= 1048576:
        raise ValueError("checkpoint byte budget exceeded")
    return torch.load(path, map_location="cpu", weights_only=True)


def publish(payload, path, crash_hook=None):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_name(path.name + ".pending")
    with pending.open("xb") as stream:
        torch.save(payload, stream)
        stream.flush()
        os.fsync(stream.fileno())
    if pending.stat().st_size > 1048576:
        raise ValueError("checkpoint byte budget exceeded")
    if crash_hook is not None:
        crash_hook(pending)
    os.replace(pending, path)
    descriptor = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
