"""Signed CPU worker cancellation and cold recovery; no production or CUDA dispatch.

A fresh bounded fixture must reach a real Running process before cancellation.
Worker process activity does not establish that an optimizer iteration started.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time

import torch
from .handoff import runtime_tuple
from .joint_graph import sha256
from .cancellation_fixture import prepare_cancellation_fixture, preflight_cancellation_fixture
from .supervisor_store import identity, process_identity
from .verify_bridge import REPO, read, sha, write_new
from .verify_host import run, source_manifest


def execute(root, executable, expected_sha256, backend):
    started = time.monotonic()
    if sys.platform != "linux":
        raise ValueError("signed worker cancellation qualification requires Linux")
    executable = executable.resolve(strict=True)
    binary = dict(path=str(executable), expected_sha256=sha256(expected_sha256), sha256=sha(executable))
    write_new(root/"signed-worker-executable.json", binary)
    if binary["sha256"] != expected_sha256 or not os.access(executable, os.X_OK):
        raise ValueError("native executable identity or permission mismatch")
    before = dict(**source_manifest(), cancellation_verifier=sha(Path(__file__)))
    write_new(root/"sources-before.json", before)
    model, request, inputs, _, _, workload = prepare_cancellation_fixture(root, backend)
    write_new(root/"cancellation-workload.json", workload)
    preflight = preflight_cancellation_fixture(root, model, request)
    write_new(root/"request.json", request)
    script, store = Path(__file__).with_name("supervisor.py").resolve(), root/"supervisor-store"
    config = dict(python_executable=sys.executable, python_sha256=sha(sys.executable),
                  repository_root=str(REPO), supervisor_sha256=sha(script), durable_root=str(store))
    write_new(root/"supervisor-config.json", config)
    pinned = {name: sha(root/name) for name in ("base.pt", "request.json", "supervisor-config.json")}
    write_new(root/"dispatch.json", dict(backend=backend, pinned_files=pinned, executable=binary,
        maximum_optimizer_steps=64, workload=workload, preflight=preflight, runtime_tuple=runtime_tuple(str(inputs.dtype)),
        numerical_progress_unobserved=True, synthetic_test_key_only=True, production=False))
    run(root, "supervisor-initialize", [sys.executable, "-I", "-B", script, "--root", store, "--initialize"])
    environment = {**os.environ, "HEPTA_HCSN_SIGNED_WORKER_ROOT": str(root)}
    environment.pop("HEPTA_HCSN_SIGNED_WORKER_PHASE", None)
    native = run(root, "signed-cancel-real-worker", [executable, "--ignored", "--exact",
        "signed_authority_real_worker_cancel_cold_recovery", "--nocapture"], env=environment)
    after = dict(**source_manifest(), cancellation_verifier=sha(Path(__file__)))
    write_new(root/"sources-after.json", after)
    if (after != before or any(sha(root/name) != value for name, value in pinned.items())
            or sha(executable) != expected_sha256 or sha(sys.executable) != config["python_sha256"]):
        raise ValueError("source, executable or input changed during cancellation acceptance")
    signed = read(root/"signed-cancel.json")
    required = dict(status="passed", authority_profile="synthetic_ed25519_v1", consumed_nonces=2,
        replay_contacts=0, retained_job_count=1, retained_cancellation_count=1,
        invalid_signature_rejected_before_contact=True, changed_payload_rejected_before_contact=True,
        start_grant_cannot_cancel=True, independent_worker_exit_verified=True,
        historical_observations_preserved=True, terminal_step_readback_exact=True,
        lost_start_and_cancel_replies_injected=True, optimizer_entry_proven=False,
        host_registration_exercised=False, production_trust=False, production_adoption=False)
    if (any(type(signed.get(key)) is not type(value) or signed[key] != value for key, value in required.items())
            or signed["request_file_sha256"] != pinned["request.json"]
            or signed["cancel_request_sha256"] != sha(root/"cancel-request.json")
            or signed["supervisor_config_sha256"] != pinned["supervisor-config.json"]
            or signed["parent_pid"] != native["pid"] or signed["cold_native_pid"] == native["pid"]):
        raise ValueError("native cancellation evidence differs from the exact dispatch")
    running, observation = signed["running"], signed["observation"]
    target, worker = observation["target"], observation["process"]
    if target != identity(target["key"], pinned["request.json"]) or read(root/"cancel-request.json") != target:
        raise ValueError("original worker target changed")
    host = read(store/"store.json")["host_id"]
    job = store/"jobs"/hashlib.sha256(target["key"].encode()).hexdigest()
    reservation, terminal = read(job/"reservation.json"), read(job/"terminal.json")
    if (reservation["identity"] != target or reservation["sources"] != before["execution"]
            or reservation["python_sha256"] != config["python_sha256"]
            or worker != read(job/"worker.json") or worker["host_id"] != host or host != sha("/etc/machine-id")
            or terminal["identity"] != target or terminal["process"] != worker
            or terminal["state"] != "cancelled" or terminal["reason"] != "cancelled_worker_stopped"
            or terminal["termination_confirmed"] is not True
            or observation != dict(running["observation"], state="cancelled", evidence=dict(
                receipt_sha256=sha(job/"terminal.json"), candidate_sha256=None, handoff_sha256=None))
            or running["observation"]["state"] != "running"
            or sha(job/"worker.json") != running["worker_sha256"]
            or sha(job/"runner.json") != running["runner_sha256"]):
        raise ValueError("real worker or terminal receipt differs from the retained live process")
    boot = Path("/proc/sys/kernel/random/boot_id").read_text()
    tail = running["proc_stat"].rsplit(")", 1)[1].split()
    if (boot != running["boot_id"] or tail[0] in ("Z", "X")
            or int(running["proc_stat"].split(" ", 1)[0]) != worker["process_id"]
            or hashlib.sha256(boot.encode()+b"\0"+tail[19].encode()).hexdigest() != worker["incarnation"]):
        raise ValueError("independent pre-cancel kernel identity does not bind the live worker")
    try:
        still_live = process_identity(worker["process_id"], host) == worker
    except (FileNotFoundError, ProcessLookupError):
        still_live = False
    if still_live:
        raise ValueError("original worker remains live after claimed termination")
    for namespace in ("jobs", "cancellations"):
        if len(list((store/namespace).iterdir())) != 1:
            raise ValueError("more than the one original job and cancellation were retained")
    cancellation = read(next((store/"cancellations").iterdir()))
    if cancellation != read(job/"cancel.json") or cancellation["target"] != target:
        raise ValueError("cancellation record does not target the original job")
    receipts = signed["taskflow_step_receipts"]
    if (len(receipts) != 2 or [item["final_outcome"] for item in receipts] != ["failed", "succeeded"]
            or any(item["state"] != "reconciled" or item["observation"] != "indeterminate" for item in receipts)):
        raise ValueError("training and cancellation did not settle their distinct logical effects")
    if any(os.path.lexists(job/target["output_id"]/name) for name in
           ("candidate.pt", "receipt.json", "handoff.bin", "failed.json")):
        raise ValueError("cancel fixture retained possible model outputs; inspect this attempt")
    write_new(root/"retained-files.json", {str(path.relative_to(root)): sha(path)
        for path in sorted(root.rglob("*")) if path.is_file()})
    result = dict(schema_version=1, status="passed", backend=backend, worker=worker,
        cancellation_workload=workload, admission_preflight=preflight,
        retained_job=str(job.relative_to(root)), signed_worker_sha256=expected_sha256,
        retained_files_sha256=sha(root/"retained-files.json"), terminal_sha256=sha(job/"terminal.json"),
        signed_start_and_cancel_real_worker=True, independent_worker_exit_verified=True,
        cold_owner_recovery=True, terminal_step_readback_exact=True, optimizer_entry_proven=False,
        host_registration_exercised=False, production=False, production_trust=False, production_adoption=False,
        native_build_linkage_verified_here=False, cuda_campaign_started=False,
        authority_profile="synthetic_ed25519_v1", wall_seconds=time.monotonic()-started)
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
        write_new(root/"failure.json", dict(error=type(error).__name__, message=str(error),
            production=False, cuda_campaign_started=False, no_retry=True,
            scope="retained cancellation attempt; inspect the existing job without redispatch"))
        raise


if __name__ == "__main__":
    main()
