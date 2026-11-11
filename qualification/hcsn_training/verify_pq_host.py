"""Actual schema-3 Agentd host and CPU worker cancellation with local ML-DSA test trust.

This is an explicit acceptance attempt, not an Agentd daemon deployment or AuthBus
ingress test. Preserve failed attempts; never redispatch an uncertain original job.
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


TEST = ("automation_effect_host::hcsn_pq::tests::real_worker::"
        "pq_host_real_worker_cancel_cold_recovery")


def deployment_sources():
    """Match the signed native policy: all Python sources, including test helpers."""
    paths = []
    for relative in ("qualification/hcsn", "qualification/hcsn_training"):
        root = REPO/relative
        if not root.is_dir() or root.is_symlink() or root.resolve() != root:
            raise ValueError("canonical complete Python source roots required")
        for path in root.rglob("*"):
            if path.is_symlink():
                raise ValueError("signed source tree cannot contain aliases")
            if path.suffix == ".py":
                if not path.is_file():
                    raise ValueError("Python source must be a regular file")
                paths.append(path)
    initializer = REPO/"qualification/__init__.py"
    if initializer.is_symlink():
        raise ValueError("qualification package initializer cannot be an alias")
    if initializer.exists():
        paths.append(initializer)
    if not 1 <= len(paths) <= 512 or sum(path.stat().st_size for path in paths) > 16*1024*1024:
        raise ValueError("signed source inventory exceeds the native deployment bound")
    return {path.relative_to(REPO).as_posix(): sha(path) for path in sorted(paths)}


def execute(root, executable, expected_sha256, backend):
    started = time.monotonic()
    if sys.platform != "linux":
        raise ValueError("real PQ host acceptance requires Linux")
    if len(os.fsencode(root/"pq-services/frontier.sock")) > 107:
        raise ValueError("choose a shorter fresh output path for Linux Unix trust sockets")
    executable = executable.resolve(strict=True)
    binary = dict(path=str(executable), expected_sha256=sha256(expected_sha256), sha256=sha(executable))
    write_new(root/"agentd-test-executable.json", binary)
    if binary["sha256"] != expected_sha256 or not os.access(executable, os.X_OK):
        raise ValueError("Agentd test executable identity or permission mismatch")
    before = dict(**source_manifest(), deployment_sources=deployment_sources())
    write_new(root/"sources-before.json", before)
    write_new(root/"deployment-sources.json", before["deployment_sources"])
    model, request, inputs, _, _, workload = prepare_cancellation_fixture(root, backend)
    write_new(root/"cancellation-workload.json", workload)
    preflight = preflight_cancellation_fixture(root, model, request)
    write_new(root/"request.json", request)
    script, store = Path(__file__).with_name("supervisor.py").resolve(), root/"supervisor-store"
    config = dict(python_executable=sys.executable, python_sha256=sha(sys.executable),
                  repository_root=str(REPO), supervisor_sha256=sha(script), durable_root=str(store))
    write_new(root/"supervisor-config.json", config)
    pinned = {name: sha(root/name) for name in ("base.pt", "request.json", "supervisor-config.json", "deployment-sources.json")}
    write_new(root/"dispatch.json", dict(backend=backend, pinned_files=pinned, executable=binary,
        runtime_tuple=runtime_tuple(str(inputs.dtype)), maximum_optimizer_steps=64, workload=workload, preflight=preflight,
        local_fixture_trust=True, optimizer_entry_proven=False, production=False))
    run(root, "supervisor-initialize", [sys.executable, "-I", "-B", script, "--root", store, "--initialize"])
    environment = {**os.environ, "HEPTA_HCSN_PQ_WORKER_ROOT": str(root)}
    environment.pop("HEPTA_HCSN_PQ_WORKER_PHASE", None)
    native = run(root, "pq-host-real-worker", [executable, "--ignored", "--exact", TEST, "--nocapture"], env=environment)
    after = dict(**source_manifest(), deployment_sources=deployment_sources())
    write_new(root/"sources-after.json", after)
    if (after != before or any(sha(root/name) != value for name, value in pinned.items())
            or sha(executable) != expected_sha256 or sha(sys.executable) != config["python_sha256"]):
        raise ValueError("source, interpreter, native executable or immutable input changed")
    signed = read(root/"pq-host.json")
    required = dict(status="passed", authority_profile="production_ml_dsa65_v2", consumed_nonces=2,
        retained_job_count=1, retained_cancellation_count=1, invalid_signature_rejected_before_contact=True,
        changed_payload_rejected_before_contact=True, start_grant_cannot_cancel=True,
        independent_worker_exit_verified=True, historical_observations_preserved=True,
        cold_owner_recovery=True, terminal_step_readback_exact=True,
        expired_and_missing_feed_terminal_readback_exact=True, lost_replies_injected=False,
        optimizer_entry_proven=False, host_registration_exercised=True, agentd_daemon_booted=False,
        authbus_ingress_exercised=False, local_fixture_trust=True, independent_custody_proven=False,
        production_trust=False, production_deployment=False, production_adoption=False)
    if (any(type(signed.get(key)) is not type(value) or signed[key] != value for key, value in required.items())
            or signed["parent_pid"] != native["pid"] or signed["cold_native_pid"] == native["pid"]
            or signed["request_file_sha256"] != pinned["request.json"]
            or signed["supervisor_config_sha256"] != pinned["supervisor-config.json"]
            or signed["cancel_request_sha256"] != sha(root/"cancel-request.json")
            or signed["host_config_sha256"] != sha(root/"pq-host-config.json")):
        raise ValueError("native PQ host evidence differs from this exact acceptance attempt")
    host_config = read(root/"pq-host-config.json")
    deployment = host_config["deployment"]
    if (host_config["schema_version"] != 3 or host_config["authority_profile"] != "production_ml_dsa65_v2"
            or any(deployment[key] != config[key] for key in config)
            or deployment["source_manifest"] != before["deployment_sources"]):
        raise ValueError("signed deployment does not bind the actual worker source and runtime")
    running, observations = signed["running"], signed["observations"]
    if len(observations) != 2:
        raise ValueError("both original Start and Cancel observations are required")
    observation = observations[0]
    target, worker = observation["target"], observation["process"]
    if target != identity(target["key"], pinned["request.json"]) or read(root/"cancel-request.json") != target:
        raise ValueError("original worker identity or cancellation target changed")
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
            or sha(job/"worker.json") != running["worker_sha256"] or sha(job/"runner.json") != running["runner_sha256"]):
        raise ValueError("terminal bytes do not bind the actual observed live worker")
    boot = Path("/proc/sys/kernel/random/boot_id").read_text()
    tail = running["proc_stat"].rsplit(")", 1)[1].split()
    if (boot != running["boot_id"] or tail[0] in ("Z", "X")
            or int(running["proc_stat"].split(" ", 1)[0]) != worker["process_id"]
            or hashlib.sha256(boot.encode()+b"\0"+tail[19].encode()).hexdigest() != worker["incarnation"]):
        raise ValueError("pre-cancel kernel evidence does not identify a live worker")
    try:
        still_live = process_identity(worker["process_id"], host) == worker
    except (FileNotFoundError, ProcessLookupError):
        still_live = False
    if still_live:
        raise ValueError("original worker remains live after claimed termination")
    for namespace in ("jobs", "cancellations"):
        if len(list((store/namespace).iterdir())) != 1:
            raise ValueError("unexpected additional original jobs or cancellations")
    cancellation = read(next((store/"cancellations").iterdir()))
    if (cancellation != read(job/"cancel.json") or cancellation["target"] != target
            or observations[1] != dict(observation, dispatch=cancellation["dispatch"])):
        raise ValueError("distinct cancellation dispatch does not bind the original terminal job")
    initial, receipts = signed["initial_step_receipts"], signed["taskflow_step_receipts"]
    if (len(initial) != 2 or len(receipts) != 2
            or [item["final_outcome"] or item["observation"] for item in receipts] != ["failed", "succeeded"]
            or any(old["observation"] != final["observation"] for old, final in zip(initial, receipts))
            or initial[0]["observation"] != "indeterminate"
            or initial[1]["observation"] not in ("indeterminate", "succeeded")):
        raise ValueError("actual initial responses or distinct terminal outcomes were not preserved")
    if any(os.path.lexists(job/target["output_id"]/name) for name in
           ("candidate.pt", "receipt.json", "handoff.bin", "failed.json")):
        raise ValueError("possible model outputs remain; inspect this cancellation attempt")
    contacts = read(root/"pq-service-requests.json")
    if any(type(contacts.get(role)) is not int or contacts[role] <= 0 for role in ("clock", "frontier")):
        raise ValueError("signed external fixture services were not exercised")
    if (root/"pq-feed.json").exists() or not (root/"pq-feed-before-terminal-readback.json").is_file():
        raise ValueError("terminal readback did not exercise the missing-feed boundary")
    write_new(root/"retained-files.json", {str(path.relative_to(root)): sha(path)
        for path in sorted(root.rglob("*")) if path.is_file()})
    result = dict(schema_version=1, status="passed", backend=backend, worker=worker,
        cancellation_workload=workload, admission_preflight=preflight,
        retained_job=str(job.relative_to(root)), agentd_executable_sha256=expected_sha256,
        retained_files_sha256=sha(root/"retained-files.json"), terminal_sha256=sha(job/"terminal.json"),
        signed_start_and_cancel_real_worker=True, host_registration_exercised=True,
        independent_worker_exit_verified=True, cold_owner_recovery=True, terminal_step_readback_exact=True,
        source_manifest_unchanged=True, signed_deployment_sources_verified=True,
        actual_initial_observations=[item["observation"] for item in initial], lost_replies_injected=False,
        optimizer_entry_proven=False, agentd_daemon_booted=False, authbus_ingress_exercised=False,
        local_fixture_trust=True, independent_custody_proven=False, production=False,
        production_trust=False, production_deployment=False, production_adoption=False,
        native_build_linkage_verified_here=False, cuda_campaign_started=False,
        authority_profile="production_ml_dsa65_v2", wall_seconds=time.monotonic()-started)
    write_new(root/"result.json", result)
    print(json.dumps(result, allow_nan=False))


def main():
    torch.set_num_threads(1)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agentd-executable", type=Path, required=True)
    parser.add_argument("--agentd-sha256", required=True)
    parser.add_argument("--backend", choices=("value_kernel", "population_grid", "population_age"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.output.resolve()
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    try:
        execute(root, args.agentd_executable, args.agentd_sha256, args.backend)
    except BaseException as error:
        write_new(root/"failure.json", dict(error=type(error).__name__, message=str(error),
            production=False, production_deployment=False, cuda_campaign_started=False, no_retry=True,
            scope="retained PQ host cancellation attempt; reconcile the existing job without redispatch"))
        raise


if __name__ == "__main__":
    main()
