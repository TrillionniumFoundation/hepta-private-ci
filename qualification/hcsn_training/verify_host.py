"""Bounded Linux CPU acceptance with a separately pinned binary and synthetic test trust."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time

import torch
from .handoff import encode_handoff, execution_sources, runtime_tuple
from .joint_graph import digest, graph_spec_dict, load_training_checkpoint, sha256
from .supervisor_store import identity, process_identity, validate_outputs
from .test_joint_graph import fixture as value_fixture
from .test_population_graph import fixture as grid_fixture
from .test_population_age_graph import fixture as age_fixture
from .test_training_state import bind_initialization
from .training_state import state_digest
from .verify_bridge import REPO, read, sha, write_new


def source_manifest():
    fixtures = ("test_joint_graph.py", "test_population_graph.py", "test_population_age_graph.py",
                "test_training_state.py")
    return dict(execution=execution_sources(), fixtures={name: sha(Path(__file__).with_name(name))
                                                        for name in fixtures})


def run(root, label, command, *, env=None):
    """Retain output and process records on ordinary failure and timeout alike."""
    argv, start, child, error = [str(value) for value in command], time.monotonic(), None, None
    incarnation, cleanup_error, logs = None, None, {}
    try:
        with (root/f"{label}.stdout").open("xb") as stdout, (root/f"{label}.stderr").open("xb") as stderr:
            child = subprocess.Popen(argv, cwd=REPO, env=env, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr)
            try:
                incarnation = process_identity(child.pid, sha("/etc/machine-id"))
            except (FileNotFoundError, ProcessLookupError):
                pass
            child.wait(timeout=180)
    except BaseException as caught:
        error = caught
        try:
            if child is not None and child.poll() is None:
                child.kill()
                child.wait(timeout=5)
        except BaseException as cleanup:
            cleanup_error = type(cleanup).__name__
    for suffix in ("stdout", "stderr"):
        try:
            logs[suffix+"_sha256"] = sha(root/f"{label}.{suffix}")
        except OSError:
            logs[suffix+"_sha256"] = None
    record = dict(argv=argv, pid=child.pid if child else None, process=incarnation,
        returncode=child.returncode if child else None, wall_seconds=time.monotonic()-start,
        error=type(error).__name__ if error else None, cleanup_error=cleanup_error, **logs)
    try:
        write_new(root/f"{label}.process.json", record)
    except OSError:
        if error is None:
            raise
    if error is not None:
        raise error
    if child.returncode:
        raise RuntimeError(f"{label} failed; retained stdout/stderr and process receipt")
    return record


def execute(root, executable, expected_sha256, backend):
    started = time.monotonic()
    if sys.platform != "linux":
        raise ValueError("configured host acceptance requires Linux")
    executable = executable.resolve(strict=True)
    binary = dict(path=str(executable), expected_sha256=sha256(expected_sha256), sha256=sha(executable))
    write_new(root/"signed-worker-executable.json", binary)
    if binary["sha256"] != expected_sha256 or not os.access(executable, os.X_OK):
        raise ValueError("signed-worker executable identity/permission mismatch")
    before = source_manifest()
    write_new(root/"sources-before.json", before)
    model, request, inputs, _, intervals = {"value_kernel": value_fixture, "population_grid": grid_fixture,
                                   "population_age": age_fixture}[backend](root)
    initial = model.initial_state(inputs)
    bind_initialization(request, initial, "fresh")
    write_new(root/"request.json", request)
    script, store = Path(__file__).with_name("supervisor.py").resolve(), root/"supervisor-store"
    config = dict(python_executable=sys.executable, python_sha256=sha(sys.executable),
                  repository_root=str(REPO), supervisor_sha256=sha(script), durable_root=str(store))
    write_new(root/"supervisor-config.json", config)
    pinned = {name: sha(root/name) for name in ("base.pt", "request.json", "supervisor-config.json")}
    runtime = runtime_tuple(str(inputs.dtype))
    write_new(root/"dispatch.json", dict(backend=backend, pinned_files=pinned, executable=binary,
        request_digest=digest(request), graph_digest=digest(graph_spec_dict(model.spec)), runtime_tuple=runtime,
        execution_source_digest=digest(before["execution"]), initial_state_digest=state_digest(initial),
        expected_facts_retained_before_dispatch=True, synthetic_test_key_only=True))
    run(root, "supervisor-initialize", [sys.executable, "-I", "-B", script, "--root", store, "--initialize"])
    caller = process_identity(os.getpid(), read(store/"store.json")["host_id"])
    write_new(root/"caller.json", dict(process=caller, platform=platform.platform(),
        hostname=platform.node(), machine=platform.machine(), runtime_tuple=runtime))
    environment = {**os.environ, "HEPTA_HCSN_SIGNED_WORKER_ROOT": str(root)}
    environment.pop("HEPTA_HCSN_SIGNED_WORKER_PHASE", None)
    native = run(root, "signed-taskflow-real-worker", [executable, "--ignored", "--exact",
        "signed_authority_real_worker_cold_recovery", "--nocapture"], env=environment)
    after = source_manifest()
    write_new(root/"sources-after.json", after)
    if (after != before or any(sha(root/name) != value for name, value in pinned.items())
            or sha(executable) != expected_sha256 or sha(sys.executable) != config["python_sha256"]):
        raise ValueError("source, executable or dispatch input changed during acceptance")
    signed = read(root/"signed-taskflow.json")
    observation = signed["observation"]
    if (signed["status"] != "passed" or observation["state"] != "succeeded"
            or signed["request_file_sha256"] != pinned["request.json"]
            or signed["supervisor_config_sha256"] != pinned["supervisor-config.json"]
            or signed["parent_pid"] != native["pid"] or signed["cold_native_pid"] == native["pid"]
            or signed["retained_job_count"] != 1 or signed["replay_contacts"] != 0
            or signed["host_registration_exercised"] is not False
            or signed["synthetic_test_key_only"] is not True or signed["production_trust"] is not False
            or signed["authority_profile"] != "synthetic_ed25519_v1"
            or signed["production_adoption"] is not False or signed["candidate_only"] is not True):
        raise ValueError("signed recovery evidence does not match this bounded test dispatch")
    target = observation["target"]
    if target != identity(target["key"], pinned["request.json"]):
        raise ValueError("terminal job identity differs from this exact request")
    job = store/"jobs"/hashlib.sha256(target["key"].encode()).hexdigest()
    reservation, runner, worker, terminal = (read(job/name) for name in
        ("reservation.json", "runner.json", "worker.json", "terminal.json"))
    if (reservation["identity"] != target or reservation["sources"] != before["execution"]
            or reservation["python_sha256"] != config["python_sha256"]
            or worker != observation["process"] or worker["host_id"] != caller["host_id"]
            or terminal["state"] != "succeeded" or terminal["identity"] != target or terminal["process"] != worker
            or terminal["termination_confirmed"] is not True
            or sha(job/"runner.json") != signed["runner_sha256"]
            or sha(job/"worker.json") != signed["worker_sha256"]):
        raise ValueError("retained supervisor source/process records differ")
    evidence = validate_outputs(job, reservation)
    if evidence != observation["evidence"] or evidence != terminal["evidence"]:
        raise ValueError("terminal evidence differs from actual worker bytes")
    output = job/target["output_id"]
    write_new(root/"worker-output.json", dict(path=str(output.relative_to(root)), **evidence))
    receipt = read(output/"receipt.json")
    candidate, state, metadata = load_training_checkpoint(output/"candidate.pt", evidence["candidate_sha256"])
    if (candidate.spec != model.spec or state is None or metadata["binding"] != request["binding"]
            or metadata["last_end_micros"] != request["intervals"][-1]["end_micros"]
            or metadata["optimizer"] != receipt["optimizer"] or receipt["runtime_tuple"] != runtime):
        raise ValueError("complete candidate model/state/runtime context mismatch")
    count = sum(parameter.numel() for parameter in model.parameters())
    expected = dict(logical_cells=len(model.cells), trainable_parameters=count, gradient_parameters=count,
        gradient_cells=len(model.cells), completed_optimizer_steps=request["optimizer_steps"],
        initial_state_digest=state_digest(initial))
    if any(receipt.get(key) != value for key, value in expected.items()):
        raise ValueError("receipt model/optimizer/initial-state facts differ from dispatch")
    with torch.no_grad():
        prediction, replayed = candidate(inputs, intervals, initial)
    if state_digest(state) != state_digest(replayed) or receipt["final_prediction"] != prediction[:, -1].tolist():
        raise ValueError("candidate replay differs from complete saved state or prediction")
    if encode_handoff(request, receipt, (output/"receipt.json").read_bytes(),
                      (output/"candidate.pt").read_bytes()) != (output/"handoff.bin").read_bytes():
        raise ValueError("handoff bytes differ from the full candidate and runtime")
    write_new(root/"retained-files.json", {str(path.relative_to(root)): sha(path)
        for path in sorted(root.rglob("*")) if path.is_file()})
    result = dict(schema_version=1, status="passed", backend=backend, runtime_tuple=runtime,
        caller=caller, runner=runner, worker=worker, cold_native_pid=signed["cold_native_pid"],
        evidence=evidence, retained_job=str(job.relative_to(root)), final_state_digest=state_digest(state),
        execution_source_digest=digest(before["execution"]), signed_worker_sha256=expected_sha256,
        retained_files_sha256=sha(root/"retained-files.json"), completed_optimizer_steps=receipt["completed_optimizer_steps"],
        complete_candidate_state_validated=True, candidate_replay_exact=True, source_manifest_unchanged=True, candidate_only=True,
        authority_profile=signed["authority_profile"], synthetic_test_key_only=True,
        host_registration_exercised=False, production=False, production_trust=False, production_adoption=False,
        native_build_linkage_verified_here=False, cuda_campaign_started=False, wall_seconds=time.monotonic()-started,
        scope="configured Linux CPU signed TaskFlow/supervisor/worker acceptance; synthetic test trust")
    write_new(root/"result.json", result)
    print(json.dumps(result, allow_nan=False))


def main():
    torch.set_num_threads(1)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--signed-worker-executable", type=Path, required=True)
    parser.add_argument("--signed-worker-sha256", required=True)
    parser.add_argument("--backend", choices=("value_kernel", "population_grid", "population_age"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.output.resolve()
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    try:
        execute(root, args.signed_worker_executable, args.signed_worker_sha256, args.backend)
    except BaseException as error:
        try:
            write_new(root/"failure.json", dict(error=type(error).__name__, message=str(error),
                production=False, cuda_campaign_started=False, no_retry=True,
                scope="retained host engineering attempt; inspect the existing job before any further action"))
            if not (root/"sources-after.json").exists():
                write_new(root/"sources-after.json", source_manifest())
        except Exception:
            pass
        raise


if __name__ == "__main__":
    main()
