"""Real Rust planner -> task BP worker -> fenced candidate owner -> cold continuation.

This small CPU fixture qualifies an engineering boundary, not scientific gain,
production trust, activation or a CUDA campaign. Output directories are once-only.
"""

import argparse
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

import torch
from .handoff import dataset_digest, execution_sources, runtime_tuple
from .joint_graph import (GraphSpec, JointCellGraph, digest, interval_seconds,
                          load_training_checkpoint, model_bytes, strict_json, tensor_digest)

REPO = Path(__file__).resolve().parents[2]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_new(path, value):
    raw = value if isinstance(value, bytes) else json.dumps(value, indent=2, allow_nan=False).encode()+b"\n"
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def read(path):
    return strict_json(path.read_bytes())


def state_digest(state):
    return tensor_digest({f"cell_{i}_slot_{j}": v for i, cell in enumerate(state) for j, v in enumerate(cell)})


def run(root, label, command):
    start = time.perf_counter()
    child = subprocess.Popen([str(v) for v in command], cwd=REPO, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        stdout, stderr = child.communicate(timeout=180)
    except BaseException:
        child.kill()
        child.communicate()
        raise
    write_new(root/f"{label}.stdout", stdout)
    write_new(root/f"{label}.stderr", stderr)
    record = dict(label=label, pid=child.pid, returncode=child.returncode,
                  wall_seconds=time.perf_counter()-start, argv=[str(v) for v in command])
    with (root/"processes.jsonl").open("a") as stream:
        stream.write(json.dumps(record)+"\n")
        stream.flush()
        os.fsync(stream.fileno())
    if child.returncode:
        raise RuntimeError(f"{label} failed: {stderr.decode(errors='replace')[-2000:]}")
    return record


def build_native(root, workspace, rustc):
    packages = ("hepta-neuron", "hepta-learning-artifacts", "hepta-types", "hepta-infer-core")
    sources = {}
    for package in packages:
        original = REPO/"codex-rs"/package
        copied = workspace/package
        for path in sorted(original.rglob("*.rs")):
            relative = path.relative_to(original)
            if sha(path) != sha(copied/relative):
                raise ValueError(f"linked workspace source differs: {package}/{relative}")
            sources[f"{package}/{relative}"] = sha(path)
    deps = Path(os.environ.get("CARGO_TARGET_DIR", workspace/"target")).resolve()/"debug/deps"
    names = ("codex_hepta_neuron", "codex_hepta_learning_artifacts", "codex_hepta_types", "serde_json", "ed25519_dalek")
    command = [rustc, "--edition=2024", "--crate-name", "hcsn_native_fixture", str(Path(__file__).with_name("native_fixture.rs")),
               "-L", f"dependency={deps}", "-o", str(root/"native-fixture")]
    libraries = {}
    for name in names:
        matches = list(deps.glob(f"lib{name}-*.rlib"))
        if len(matches) != 1:
            raise ValueError(f"expected one exact {name} rlib after cargo build, found {len(matches)}")
        command += ["--extern", f"{name}={matches[0]}"]
        libraries[name] = dict(filename=matches[0].name, sha256=sha(matches[0]))
    run(root, "rustc-version", [rustc, "--version", "--verbose"])
    run(root, "native-build", command)
    write_new(root/"native-build.json", dict(rust_sources=sources, libraries=libraries,
        rustc_sha256=sha(rustc), source_sha256=sha(Path(__file__).with_name("native_fixture.rs")),
        executable_sha256=sha(root/"native-fixture")))
    return root/"native-fixture"


def resume(root):
    start, cpu = time.perf_counter(), time.process_time()
    admitted, request, plan = (read(root/name) for name in ("admitted.json", "request.json", "continuation-plan.json"))
    candidate = plan["candidate_digest"]
    model, state, metadata = load_training_checkpoint(root/"readback.pt", candidate)
    if (metadata["binding"] != request["binding"] or digest(asdict(model.spec)) != admitted["graph_digest"]
            or state_digest(state) != plan["initial_state_digest"]
            or metadata["last_end_micros"] != plan["intervals"][0]["start_micros"]
            or digest(execution_sources()) != admitted["training_code_digest"]
            or digest(runtime_tuple(metadata["dtype"])) != admitted["runtime_tuple_digest"]):
        raise ValueError("cold candidate context differs from retained dispatch/source/runtime")
    # Saved binding records training provenance; current model identity is candidate, never the old base SHA.
    inputs = torch.tensor(read(root/"continuation-input.json"), dtype=next(model.parameters()).dtype)
    with torch.no_grad():
        prediction, final = model(inputs, interval_seconds(plan["intervals"], plan["profile"]), state=state)
    if digest(execution_sources()) != admitted["training_code_digest"]:
        raise ValueError("source changed while resuming")
    write_new(root/"resumed.json", dict(candidate_digest=candidate, prediction=prediction.tolist(),
        state_digest=state_digest(final), saved_training_binding=metadata["binding"],
        current_model_identity=candidate, pid=os.getpid(), wall_seconds=time.perf_counter()-start,
        cpu_seconds=time.process_time()-cpu, cpu_threads=torch.get_num_threads(), production_adoption=False))


def execute(root, workspace, rustc):
    start, cpu = time.perf_counter(), time.process_time()
    native = build_native(root, workspace, rustc)
    torch.manual_seed(31)
    model = JointCellGraph(GraphSpec(("memory", "association"), 2, 3, 1)).double()
    inputs = torch.tensor([[[.25, -.35], [.45, .15], [-.3, .5], [.6, -.2]],
                           [[-.15, .3], [.2, -.4], [.35, -.1], [.25, .7]]], dtype=torch.float64)
    write_new(root/"base.pt", model_bytes(model))
    base = sha(root/"base.pt")
    profile = dict(maximum_gap_micros=1_000_000, forecast_horizon_micros=500_000, integration=dict(kind="value_kernel"))
    binding = dict(scope_digest=digest("scope"), generation=1, writer_epoch=1, clock_epoch=digest("clock"), model_digest=base)
    initial = tuple(cell.initial_state(2, like=inputs) for cell in model.cells)
    write_new(root/"clock-input.json", dict(profile=profile, binding=binding, start_micros=17,
        ends=[100017, 300017, 450017, 750017], initial_state_digest=state_digest(initial)))
    run(root, "native-plan", [native, "plan", root])
    plan = read(root/"training-plan.json")
    binding["profile_digest"] = plan["intervals"][0]["profile_digest"]
    request = dict(schema_version=1, mechanism="task_mse_bp_v1", operation_id="hcsn:bridge-fixture",
        binding=binding, intervals=plan["intervals"], time_profile=profile, inputs=inputs.tolist(),
        targets=[[.4], [-.2]], target_time_micros=1_250_017, learning_rate=.02, optimizer_steps=1,
        limits=dict(max_optimizer_steps=1, max_batch=2, max_intervals=4, max_elements=1000),
        base_checkpoint=dict(path=str(root/"base.pt"), sha256=base))
    admitted = dict(operation_id=request["operation_id"], request_digest=digest(request),
        training_code_digest=digest(execution_sources()), runtime_tuple_digest=digest(runtime_tuple("torch.float64")),
        graph_digest=digest(asdict(model.spec)), time_profile_digest=binding["profile_digest"],
        base_checkpoint_digest=base, dataset_digest=dataset_digest(request), target_generation=binding["generation"],
        optimizer_steps=1, logical_cells=2, trainable_parameters=sum(p.numel() for p in model.parameters()))
    write_new(root/"request.json", request)
    write_new(root/"admitted.json", admitted)  # Immutable independent expected facts exist before dispatch.
    dispatch = dict(request_file_sha256=sha(root/"request.json"), admitted_file_sha256=sha(root/"admitted.json"),
                    execution_sources=execution_sources(), caller_pid=os.getpid(), admitted_before_dispatch=True)
    write_new(root/"dispatch.json", dispatch)
    worker_process = run(root, "python-worker", [sys.executable, "-m", "qualification.hcsn_training.worker",
        "--request", root/"request.json", "--output", root/"worker"])
    if sha(root/"request.json") != dispatch["request_file_sha256"] or sha(root/"admitted.json") != dispatch["admitted_file_sha256"]:
        raise RuntimeError("dispatch input changed")
    receipt = read(root/"worker/receipt.json")
    candidate_sha = sha(root/"worker/candidate.pt")
    candidate, state, metadata = load_training_checkpoint(root/"worker/candidate.pt", candidate_sha)
    continuation = inputs[:, :2]
    intervals = interval_seconds(request["intervals"], profile)
    with torch.no_grad():
        whole, final = candidate(torch.cat((inputs, continuation), 1), (*intervals, .2, .1))
    write_new(root/"reference.json", dict(prediction=whole[:, -2:].tolist(), state_digest=state_digest(final),
        candidate_digest=candidate_sha, method="uninterrupted six-step unfold from initial state using candidate weights"))
    write_new(root/"candidate-state.json", dict(checkpoint_sha256=candidate_sha,
        state_digest=state_digest(state), last_end_micros=metadata["last_end_micros"]))
    write_new(root/"continuation-input.json", continuation.tolist())
    run(root, "native-publication", [native, "publish", root])
    run(root, "native-cold-owner", [native, "reopen", root])
    cold_process = run(root, "python-cold-continuation", [sys.executable, "-m",
        "qualification.hcsn_training.verify_bridge", "--resume", root])
    reference, resumed = read(root/"reference.json"), read(root/"resumed.json")
    if reference["prediction"] != resumed["prediction"] or reference["state_digest"] != resumed["state_digest"]:
        raise AssertionError("cold continuation differs from uninterrupted candidate computation")
    if sha(root/"base.pt") != base or sha(root/"readback.pt") != candidate_sha:
        raise AssertionError("original or published bytes changed")
    run(root, "native-clock-commit", [native, "finish", root])
    result = dict(schema_version=1, status="passed", scope="CPU engineering fixture; no scientific campaign",
        operation_id=request["operation_id"], caller_pid=os.getpid(), worker_pid=worker_process["pid"],
        cold_python_pid=cold_process["pid"], optimizer_steps=1, logical_cells=2,
        completed_optimizer_steps=receipt["completed_optimizer_steps"], gradient_cells=receipt["gradient_cells"],
        trainable_parameters=admitted["trainable_parameters"], gradient_parameters=receipt["gradient_parameters"],
        initial_state_digest=state_digest(initial), base_checkpoint_digest=base, candidate_digest=candidate_sha,
        source_digest=admitted["training_code_digest"], runtime_tuple=receipt["runtime_tuple"],
        resumed_output_exact=True, resumed_all_state_exact=True, base_bytes_unchanged=True,
        signed_owner=read(root/"publication.json"), cold_owner=read(root/"cold-owner.json"),
        clock_commit=read(root/"clock-commit.json"), synthetic_test_key_only=True, production_trust=False,
        production_adoption=False, task_gain_qualified=False, cuda_campaign_started=False,
        physical_energy_joules=None, wall_seconds=time.perf_counter()-start, caller_cpu_seconds=time.process_time()-cpu,
        cost_scope="compile and all recorded child invocations included in wall; child diagnostics retain their scopes")
    write_new(root/"result.json", result)
    print(json.dumps(result, allow_nan=False))


def main():
    torch.set_num_threads(1)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rust-workspace", type=Path, default=REPO/"codex-rs")
    parser.add_argument("--rustc", default=shutil.which("rustc"))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--resume", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.resume is not None:
        resume(args.resume.resolve())
        return
    if args.output is None or args.rustc is None:
        parser.error("--output and an available rustc are required")
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=False)
    try:
        execute(root, args.rust_workspace.resolve(), str(Path(args.rustc).resolve()))
    except BaseException as error:
        write_new(root/"failure.json", dict(error=type(error).__name__, message=str(error),
            scope="engineering fixture; preserve this attempt; no automatic retry"))
        raise


if __name__ == "__main__":
    main()
