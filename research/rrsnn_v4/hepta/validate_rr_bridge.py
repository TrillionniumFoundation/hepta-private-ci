"""Actual process-crash proof for a bounded RR feature/backend host composition."""
import argparse
import copy
import json
import os
from pathlib import Path
import select
import shutil
import signal
import subprocess
import time

from rr_bridge_backend import HERE, Q, read, sha, write

PYTHON = Path("/tmp/rrsnn-venv/bin/python")
NATIVE = HERE / "rr_bridge_build/bin/rrsnn-rr-feature-broker"
BACKEND = HERE / "rr_bridge_backend.py"
WORKER = HERE / "rr_bridge_worker.py"
SEED = 441901


def invoke(command):
    result = subprocess.run(list(map(str, command)), text=True, capture_output=True, timeout=120)
    if result.returncode:
        raise RuntimeError(result.stderr)
    return json.loads(result.stdout)


def admission(root, manifest, frontier_pin, sequence):
    frontier = read(root / "frontier.json")
    neural_us = (sequence - 1) * 500_000
    t = neural_us / 1e6
    values = [.3, .7, .4, .6] if sequence == 1 else [0.] * 4
    features = values + [max(0., 1-(sequence-1)/6), 1., .5] + [max(0., x-t)/4 for x in (1., 3., 1., 3.)] + [1.] * 4
    features += ([1/3, 1.5/4, .5, 2.5/4] if sequence == 1 else [0.] * 4)
    features += [t/4, float(sequence == 1), 1/6]
    assert len(features) == 22
    value = {"sequence": sequence, "time_micros": 1_000_000 + neural_us,
        "neural_time_micros": neural_us, "dt_micros": 0 if sequence == 1 else 500_000,
        "event_mask": True, "features_q24": [round(v * Q) for v in features],
        "previous_native_checkpoint": frontier["native_checkpoint"], "manifest_sha256": sha(manifest),
        "expected_frontier_sha256": frontier_pin, "task_scope": "synthetic feature probe; no heldout labels or utility"}
    path = root / "admissions" / f"sequence-{sequence:04}.json"
    write(path, value)
    return path


class Controller:
    def __init__(self, directory, frontier_pin):
        self.directory = directory
        self.frontier_pin = frontier_pin
        self.pending = {}
        self.events = []
        self.record({"stage": "initial_trusted_frontier", "frontier_sha256": frontier_pin})

    def record(self, value):
        value = {**value, "previous_record_sha256": self.events[-1]["sha256"] if self.events else None}
        path = self.directory / f"event-{len(self.events):04}.json"
        write(path, value)
        self.events.append({"path": str(path), "sha256": sha(path), "stage": value["stage"]})

    def command(self, root, manifest, admitted, fault="none", include_pending=True):
        command = [PYTHON, "-u", WORKER, "--root", root, "--manifest", manifest, "--manifest-pin", sha(manifest),
            "--admission", admitted, "--frontier-pin", self.frontier_pin, "--native", NATIVE,
            "--backend", BACKEND, "--python", PYTHON, "--fault", fault]
        sequence = read(admitted)["sequence"]
        if include_pending and sequence in self.pending:
            command += ["--pending-pin", self.pending[sequence]]
        return list(map(str, command))

    def run(self, root, manifest, admitted, fault="none"):
        process = subprocess.Popen(self.command(root, manifest, admitted, fault), stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
        sequence = read(admitted)["sequence"]
        observed = []
        while True:
            ready, _, _ = select.select([process.stdout], [], [], 90)
            if not ready:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
                raise RuntimeError("BoundedFeatureTransactionTimedOut")
            line = process.stdout.readline()
            if not line:
                code = process.wait(timeout=30)
                raise RuntimeError(f"FeatureWorkerFailed[{code}]: " + process.stderr.read())
            value = json.loads(line)
            observed.append(value)
            stage = value["stage"]
            if stage == "prepared":
                pending_path = root / "pending" / f"sequence-{sequence:04}.json"
                if sha(pending_path) != value["pending_sha256"]:
                    raise ValueError("ExternalPendingPinMismatch")
                self.pending[sequence] = value["pending_sha256"]
            elif stage == "joint_published":
                pending = read(root / "pending" / f"sequence-{sequence:04}.json")
                if value["frontier_sha256"] != pending["next_frontier_sha256"] or sha(root / "frontier.json") != value["frontier_sha256"]:
                    raise ValueError("ExternalFrontierPublicationMismatch")
                self.frontier_pin = value["frontier_sha256"]
            self.record(value)
            if stage == fault:
                os.killpg(process.pid, signal.SIGKILL)
                code = process.wait(timeout=30)
                assert code == -9
                return {"crash_stage": stage, "actual_sigkill_returncode": code, "events": observed}
            if stage == "done":
                assert process.wait(timeout=30) == 0
                return {"result": value, "events": observed}
            process.stdin.write("go\n"); process.stdin.flush()


def executions(root):
    return [json.loads(line) for line in (root / "executions.ndjson").read_text().splitlines()]


def validate(args):
    if shutil.disk_usage(HERE).free < 80_000_000:
        raise RuntimeError("80 MB fixed free-space cushion required")
    directory = HERE / "rr_bridge_results" / (("development-" if args.development else "selected-trained-") + str(time.time_ns()))
    directory.mkdir(parents=True)
    manifest = directory / "manifest.json"
    command = [PYTHON, HERE / "rr_bridge_artifact.py", "--output", manifest, "--native", NATIVE]
    if args.development:
        command += ["--development"]
    else:
        command += ["--artifact", args.artifact, "--training-receipt", args.training_receipt,
                    "--selection", args.selection, "--selection-pin", args.selection_pin]
    artifact = invoke(command)
    base = directory / "uninterrupted"
    initialized = invoke([PYTHON, BACKEND, "initialize", "--root", base, "--manifest", manifest, "--seed", SEED])
    controller = Controller(directory / "controller-uninterrupted", initialized["frontier_sha256"])
    first_admission = admission(base, manifest, controller.frontier_pin, 1)
    first = controller.run(base, manifest, first_admission)
    snapshot = directory / "published-first-joint-snapshot"
    shutil.copytree(base, snapshot)
    first_pin = controller.frontier_pin
    reference_rows = [first["result"]]
    for sequence in (2, 3):
        admitted = admission(base, manifest, controller.frontier_pin, sequence)
        reference_rows.append(controller.run(base, manifest, admitted)["result"])
    assert len(executions(base)) == 3
    admitted_paths = directory / "uninterrupted-admissions.json"
    write(admitted_paths, [str(base / "admissions" / f"sequence-{s:04}.json") for s in (1, 2, 3)])
    direct = invoke([PYTHON, BACKEND, "reference", "--manifest", manifest, "--admissions", admitted_paths, "--seed", SEED])
    for actual, expected in zip(reference_rows, direct["rows"]):
        for key in ["state_sha256", "drive_q24", "actual_internal_spikes"]:
            assert actual[key] == expected[key], (key, actual, expected)
    crashes = []
    for phase in ("unconfirmed_prepared", "prepared", "before_witness", "after_witness", "joint_file_written", "joint_published"):
        root = directory / ("fault-" + phase)
        shutil.copytree(snapshot, root)
        control = Controller(directory / ("controller-" + phase), first_pin)
        admitted = admission(root, manifest, first_pin, 2)
        crashed = control.run(root, manifest, admitted, phase)
        assert len(executions(root)) == 2
        recovered = control.run(root, manifest, admitted)
        recomputed_unconfirmed = phase == "unconfirmed_prepared"
        assert len(executions(root)) == (3 if recomputed_unconfirmed else 2)
        assert recovered["result"]["backend_executed_this_attempt"] is recomputed_unconfirmed
        for key in ["state_sha256", "drive_q24", "actual_internal_spikes"]:
            assert recovered["result"][key] == reference_rows[1][key]
        third = admission(root, manifest, control.frontier_pin, 3)
        continued = control.run(root, manifest, third)
        assert len(executions(root)) == (4 if recomputed_unconfirmed else 3)
        for key in ["state_sha256", "drive_q24", "actual_internal_spikes"]:
            assert continued["result"][key] == reference_rows[2][key]
        crashes.append({"phase": phase, "crash": crashed, "recovered": recovered["result"],
                        "continuation": continued["result"],
                        "actual_model_executions_including_prefix": len(executions(root)),
                        "unconfirmed_prepare_recomputed_from_trusted_prior_state": recomputed_unconfirmed,
                        "unbound_orphan_artifacts_retained": len(list((root / "prepared").glob('*.json'))) - 3})
    negatives = []
    root = directory / "negative"
    shutil.copytree(snapshot, root)
    control = Controller(directory / "controller-negative", first_pin)
    admitted = admission(root, manifest, first_pin, 2)
    # Bind an actual pending request, then retain independent pins for mutations.
    control.run(root, manifest, admitted, "before_witness")
    pending_file = root / "pending/sequence-0002.json"
    pending = read(pending_file)
    def reject(name, command, expected):
        count = len(executions(root))
        result = subprocess.run(command, text=True, capture_output=True, timeout=45)
        assert result.returncode == 2, (name, result.returncode, result.stdout, result.stderr)
        error = json.loads(result.stderr)["error"]
        assert expected in error, (name, expected, error)
        assert len(executions(root)) == count
        negatives.append({"name": name, "error": error, "no_new_model_execution": True})
    reject("missing-independent-pending-pin", control.command(root, manifest, admitted, include_pending=False), "IndependentPendingIntentPinRequired")
    command = control.command(root, manifest, admitted)
    command[command.index("--manifest-pin") + 1] = "f" * 64
    reject("wrong-manifest-pin", command, "IndependentManifestPinMismatch")
    command = control.command(root, manifest, admitted)
    command[command.index("--frontier-pin") + 1] = "f" * 64
    reject("wrong-current-frontier", command, "UnrelatedTrustedFrontier")
    for option, expected in [("--native", "ActualNativeBinaryIdentityMismatch"),
                             ("--backend", "ActualBackendScriptIdentityMismatch"),
                             ("--python", "ActualPythonExecutableIdentityMismatch")]:
        altered = directory / (option[2:] + "-wrong-identity.bin")
        altered.write_bytes(b"different execution identity; never executed")
        command = control.command(root, manifest, admitted)
        command[command.index(option) + 1] = str(altered)
        reject(option[2:] + "-actual-identity", command, expected)
    prepared_path = root / pending["prepared_path"]
    original = prepared_path.read_bytes()
    tampered = read(prepared_path);tampered["drive_q24"][0] += 1
    write(prepared_path, tampered, immutable=False)
    reject("altered-valid-json-prepared-result", control.command(root, manifest, admitted), "PendingArtifactPinMismatch")
    prepared_path.write_bytes(original)
    state_path = root / pending["next_frontier"]["state_path"]
    original = state_path.read_bytes();tampered = read(state_path)
    tampered["pcg64"]["state"]["state"] = str(int(tampered["pcg64"]["state"]["state"]) ^ 1)
    write(state_path, tampered, immutable=False)
    reject("altered-PCG64-state", control.command(root, manifest, admitted), "PendingArtifactPinMismatch")
    state_path.write_bytes(original)
    original = pending_file.read_bytes();tampered = read(pending_file);tampered["sequence"] = 3
    write(pending_file, tampered, immutable=False)
    reject("altered-pending-frontier", control.command(root, manifest, admitted), "IndependentPendingIntentPinRequired")
    pending_file.write_bytes(original)
    original_frontier = (root / "frontier.json").read_bytes()
    changed = read(root / "frontier.json");changed["state_sha256"] = "f" * 64
    write(root / "frontier.json", changed, immutable=False)
    native_before = {name: sha(root / "native" / name) for name in ("journal.bin", "witness.bin")}
    reject("tampered-current-frontier-before-native-recovery", control.command(root, manifest, admitted), "JointFrontierOutsideTrustedIntent")
    assert native_before == {name: sha(root / "native" / name) for name in native_before}
    (root / "frontier.json").write_bytes(original_frontier)
    descriptor = invoke([NATIVE, "describe", manifest, admitted])
    backend_command = [str(PYTHON), str(BACKEND), "prepare", "--root", str(root), "--manifest", str(manifest), "--admission", str(admitted)]
    def reject_backend(name, request, command, expected):
        before = len(executions(root))
        result = subprocess.run(list(map(str, command)), input=json.dumps(request), capture_output=True, text=True, timeout=60)
        assert result.returncode == 2, (name, result.stdout, result.stderr)
        error = json.loads(result.stderr)["error"]
        assert expected in error, (name, expected, error)
        assert len(executions(root)) == before
        negatives.append({"name": name, "error": error, "no_new_model_execution": True})
    for field in ("request_id", "generation", "encoder_digest", "head_digest", "input_digest"):
        changed = copy.deepcopy(descriptor)
        changed["request"][field] = 2 if field == "generation" else ("wrong.request" if field == "request_id" else "f" * 64)
        reject_backend("wrong-official-" + field, changed, backend_command, "OfficialRequestDescriptorMismatch")
    changed = copy.deepcopy(descriptor);changed["request_digest"] = "f" * 64
    reject_backend("wrong-official-request-digest", changed, backend_command, "OfficialRequestDescriptorMismatch")
    bad_dt = read(admitted);bad_dt["dt_micros"] += 1
    bad_dt_path = root / "admissions/bad-dt.json";write(bad_dt_path, bad_dt)
    bad_dt_request = invoke([NATIVE, "describe", manifest, bad_dt_path])
    command = list(backend_command);command[-1] = str(bad_dt_path)
    reject_backend("host-dt-clock-inconsistency", bad_dt_request, command, "HostElapsedTimeBindingMismatch")
    bad_source = read(manifest);bad_source["source_sha256"]["rrsnn_v4/hepta/rr_bridge_backend.py"] = "f" * 64
    bad_source_path = directory / "bad-source-manifest.json";write(bad_source_path, bad_source)
    command = list(backend_command);command[command.index("--manifest") + 1] = str(bad_source_path)
    reject_backend("current-source-identity", descriptor, command, "FrozenSourceIdentityMismatch")
    wrong_weight_file = directory / "wrong-weight-copy.bin";wrong_weight_file.write_bytes(b"wrong frozen weights; original checkpoint preserved")
    bad_weight = read(manifest);bad_weight["artifact_path"] = str(wrong_weight_file)
    bad_weight_path = directory / "bad-weight-manifest.json";write(bad_weight_path, bad_weight)
    command = list(backend_command);command[command.index("--manifest") + 1] = str(bad_weight_path)
    reject_backend("current-frozen-weight-identity", descriptor, command, "FrozenWeightArtifactMismatch")
    report = {"schema": "rrsnn.v4.feature-bridge-proof.v1", "all_passed": True,
        "artifact": artifact, "manifest": str(manifest), "native_binary_sha256": sha(NATIVE),
        "direct_uninterrupted_reference": direct, "native_uninterrupted": reference_rows,
        "actual_sigkill_cases": crashes, "negative_cases": negatives,
        "full_rr_state_and_pcg64_replayed_exactly": True, "confirmed_retries_reexecute_model": False,
        "unconfirmed_prepare_retry_recomputes_from_independently_pinned_prior_state": True,
        "committed_rr_state_and_rng_advance_once": True,
        "initial_scope": "first joint checkpoint established successfully; crash proofs start at transition2",
        "native_v1_state_contains_rr_state": False, "native_model_port_unmodified": True,
        "sidecar_current_frontier_requires_independent_trusted_supervisor": True,
        "head81_action_policy_routed": False, "production_qualified": False, "production_cell": False,
        "dot_verified": False, "independent_future_utility": False, "authority_granted": False,
        "all_native_ticks_abstained": True, "frozen_r4_sources_modified": False,
        "memory_note": "backend entire-process VmHWM is conservative resident upper bound; not isolated transient allocation"}
    write(directory / "proof.json", report)
    write(HERE / "rr_bridge_results" / ("development_latest.json" if args.development else "trained_latest.json"), report, immutable=False)
    print(json.dumps({"all_passed": True, "development_only": args.development,
                      "actual_sigkill_cases": len(crashes), "negative_cases": len(negatives), "proof": str(directory / "proof.json")}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--development", action="store_true")
    for name in ("artifact", "training-receipt", "selection"):
        parser.add_argument("--" + name, type=Path)
    parser.add_argument("--selection-pin")
    args = parser.parse_args()
    os.sched_setaffinity(0, {8})
    os.environ.update(OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1")
    validate(args)
