"""Linux/GitHub-runner experiment; artifact relay, one trusted release authority.

No fallback training fixtures: producer requires the committed V12 content model.
Each workflow job is a fresh hosted runner VM. Machine identifiers are environment
evidence, not hardware attestation. SIGKILL tests controller-process failure only.
"""

import argparse
import copy
import hashlib
import os
from pathlib import Path
import platform
import secrets
import select
import shutil
import signal
import subprocess
import sys
import time

from federation import Authority, Denied, digest, file_digest, infer, read_json, seal_bundle, verify_bundle, write_json


NODES = ("replica-a", "replica-b")
LIMITS = dict(trusted_github_workflow=True, trusted_single_controller=True,
              artifact_relay_not_live_peer_network=True, replicas_release_answers=False,
              native_rust_owner_authority_integration=False, artifact_retention_days=30,
              end_to_end_network_latency_measured=False,
              hardware_attestation=False, physical_host_failure_tested=False,
              partition_availability_tested=False, distributed_consensus=False,
              optimizer_migration=False, mathematical_unlearning=False,
              new_memory_quality_claimed=False, production_activation_allowed=False)


def task_binding(nonce):
    names = ("GITHUB_REPOSITORY", "GITHUB_SHA", "GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT", "GITHUB_WORKFLOW_REF")
    if os.environ.get("GITHUB_ACTIONS") != "true" or any(not os.environ.get(k) for k in names):
        raise Denied("this experiment requires actual GitHub Actions jobs; use federation_tests.py for local tests")
    if subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip() != os.environ["GITHUB_SHA"]:
        raise Denied("checkout differs from workflow source SHA")
    return dict(schema="hepta.memory.federation.task.v1", nonce=nonce,
                **{k.lower(): os.environ[k] for k in names})


def identity(role):
    machine = Path("/etc/machine-id").read_text().strip()
    boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    if not machine or not boot:
        raise Denied("runner identity evidence unavailable")
    return dict(role=role, machine_id_sha256=hashlib.sha256(machine.encode()).hexdigest(),
                boot_id_sha256=hashlib.sha256(boot.encode()).hexdigest(),
                instance_sha256=digest([machine, boot, platform.node()]),
                github_job=os.environ.get("GITHUB_JOB"), runner_name=os.environ.get("RUNNER_NAME"),
                platform=platform.platform(), pid=os.getpid())


def distinct(identities):
    if len({x["instance_sha256"] for x in identities}) != len(identities):
        raise Denied("claimed cross-runner participants share an instance identity")
    if len({x["boot_id_sha256"] for x in identities}) != len(identities):
        raise Denied("claimed cross-runner participants share a kernel boot")


def rejected(checks, name, operation):
    try:
        operation()
    except Denied as error:
        checks.append(dict(name=name, passed=True, reason=str(error)))
    else:
        raise AssertionError(name + " was accepted")


def candidate(node, ticket, output):
    return dict(node=node, ticket=ticket, output=output, serving_authorized=False)


def publish_stage(out, receipt):
    receipt["limits"] = LIMITS
    receipt["executed_source"] = {n: file_digest(Path(__file__).with_name(n))
                                  for n in ("federation.py", "federation_experiment.py", "federation_tests.py")}
    if (out / "authority.sqlite").exists():
        receipt["authority_sha256"] = file_digest(out / "authority.sqlite")
    write_json(out / "stage.json", receipt)
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as stream:
            for key in ("checkpoint", "authority_sha256"):
                if key in receipt:
                    stream.write(key + "=" + receipt[key] + "\n")
            stream.write("nonce=" + receipt["binding"]["nonce"] + "\n")


def source_stage(source, out):
    binding = task_binding(secrets.token_hex(16))
    checkpoint = seal_bundle(source, out / "bundle", binding)
    output = infer(out / "bundle", binding, checkpoint)
    model, probes = (read_json(out / "bundle" / n) for n in ("model.json", "probes.json"))
    training = model["receipt"]
    if (training["initial_parameter_sha256"] == training["final_parameter_sha256"] or
            training["final_parameter_sha256"] != model["parameter_sha256"] or training["steps"] <= 0 or
            any(training["parameter_change_norm"][n] <= 0 for n in ("hidden.weight", "head.weight"))):
        raise Denied("a real learned, changed hidden/head checkpoint is required")
    control = Authority(out / "authority.sqlite", binding, initial=dict(checkpoint=checkpoint, probes=probes))
    tickets = {node: {kind: control.issue(node) for kind in ("normal", "pending")} for node in ("source", *NODES)}
    baseline = control.release(candidate("source", tickets["source"]["normal"], output))
    control.close()
    publish_stage(out, dict(phase="source", binding=binding, checkpoint=checkpoint,
                           identities=[identity("source")], tickets=tickets, baseline=baseline,
                           pending_source=candidate("source", tickets["source"]["pending"], output),
                           training_receipt=training, bundle_bytes=sum(p.stat().st_size for p in (out / "bundle").iterdir())))


def load_stage(path, binding, checkpoint):
    stage = read_json(path / "stage.json")
    if stage["binding"] != binding or stage["checkpoint"] != checkpoint:
        raise Denied("artifact was produced for another run, attempt, commit, or checkpoint")
    return stage


def reader_stage(source, out, node, phase, binding, checkpoint, authority_anchor=None):
    stage = load_stage(source, binding, checkpoint)
    if phase == "readback" and file_digest(source / "authority.sqlite") != authority_anchor:
        raise Denied("reader received a rolled-back controller snapshot")
    verify_bundle(source / "bundle", binding, checkpoint)
    shutil.copytree(source / "bundle", out / "bundle")
    for path in (out / "bundle").iterdir():
        path.chmod(0o444)
    output = infer(out / "bundle", binding, checkpoint)
    tickets = stage["tickets"][node]
    prepared = dict(binding=binding, node=node, epoch=tickets["normal"]["epoch"],
                    checkpoint=checkpoint, read_grant=tickets["normal"]["grant"], verified_checkpoint=True)
    publish_stage(out, dict(phase=phase, binding=binding, checkpoint=checkpoint, node=node,
                           identities=[identity(phase + ":" + node)], prepared=prepared,
                           candidates={k: candidate(node, ticket, output) for k, ticket in tickets.items()},
                           file_modes={p.name: oct(p.stat().st_mode & 0o777) for p in (out / "bundle").iterdir()},
                           cold_checkpoint_load=True, mutation_authorized=False,
                           query_count=len(output["logits"]), max_abs_error=output["max_abs_error"]))


def crash_stage(path, mode):
    request = read_json(path / "crash-request.json")
    control = Authority(path / "authority.sqlite", request["binding"])
    if mode == "before_commit":
        control.db.execute("BEGIN IMMEDIATE")
        control.db.execute("UPDATE state SET epoch=999 WHERE id=1")
    else:
        control.migrate("replica-a", expected_epoch=1, expected_owner="source", prepared=request["prepared"])
    print("ready", flush=True)
    signal.pause()


def kill_at_boundary(out, mode):
    child = subprocess.Popen([sys.executable, __file__, "crash", "--input", str(out), "--mode", mode],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        if not select.select([child.stdout], [], [], 15)[0] or child.stdout.readline().strip() != "ready":
            raise RuntimeError("crash worker did not reach the requested transaction boundary")
        child.kill()
        stdout, stderr = child.communicate(timeout=10)
        if child.returncode != -signal.SIGKILL:
            raise AssertionError("fault injection did not actually kill the child")
        return dict(boundary=mode, child_pid=child.pid, exit_code=child.returncode,
                    signal="SIGKILL", stdout=stdout, stderr=stderr)
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=10)


def migrate_stage(source, out, binding, checkpoint, anchor):
    original = load_stage(source / "source", binding, checkpoint)
    readers = {node: load_stage(source / node, binding, checkpoint) for node in NODES}
    identities = original["identities"] + [r["identities"][0] for r in readers.values()] + [identity("controller:migrate")]
    distinct(identities)
    shutil.copyfile(source / "source/authority.sqlite", out / "authority.sqlite")
    control = Authority(out / "authority.sqlite", binding, expected_anchor=anchor)
    checks = []
    releases = {n: control.release(r["candidates"]["normal"]) for n, r in readers.items()}
    rejected(checks, "read_only_replica_cannot_write", lambda: control.authorize_write("replica-b", 1, checkpoint))
    control.close()
    write_json(out / "crash-request.json", dict(binding=binding, prepared=readers["replica-a"]["prepared"]))
    crashes = [kill_at_boundary(out, "before_commit")]
    control = Authority(out / "authority.sqlite", binding)
    if control.state() != dict(epoch=1, owner="source", checkpoint=checkpoint, valid=1):
        raise AssertionError("uncommitted killed transaction changed durable owner")
    control.close()
    crashes.append(kill_at_boundary(out, "after_commit"))
    control = Authority(out / "authority.sqlite", binding)
    if control.state() != dict(epoch=2, owner="replica-a", checkpoint=checkpoint, valid=1):
        raise AssertionError("committed owner lost after process death before acknowledgment")
    rejected(checks, "old_owner_epoch_rejected", lambda: control.authorize_write("source", 1, checkpoint))
    rejected(checks, "old_owner_cannot_claim_current_epoch", lambda: control.authorize_write("source", 2, checkpoint))
    rejected(checks, "computed_before_migration_cannot_release", lambda: control.release(original["pending_source"]))
    rejected(checks, "duplicate_activation_rejected", lambda: control.migrate("replica-a", expected_epoch=1,
             expected_owner="source", prepared=readers["replica-a"]["prepared"]))
    tickets = {n: {k: control.issue(n) for k in ("normal", "pending")} for n in NODES}
    state = control.state()
    control.close()
    shutil.copytree(source / "source/bundle", out / "bundle")
    publish_stage(out, dict(phase="migrate", binding=binding, checkpoint=checkpoint, identities=identities,
                           state=state, tickets=tickets, checks=checks, crashes=crashes, replica_releases=releases))


def final_stage(source, out, binding, checkpoint, anchor):
    original = load_stage(source / "source", binding, checkpoint)
    migrated = load_stage(source / "migrate", binding, checkpoint)
    readers = {n: load_stage(source / n, binding, checkpoint) for n in NODES}
    identities = migrated["identities"] + [r["identities"][0] for r in readers.values()] + [identity("controller:final")]
    distinct(identities)
    checks = list(migrated["checks"])
    rejected(checks, "old_authority_snapshot_cannot_rejoin", lambda: Authority(
        source / "source/authority.sqlite", binding, expected_anchor=anchor))
    shutil.copyfile(source / "migrate/authority.sqlite", out / "authority.sqlite")
    control = Authority(out / "authority.sqlite", binding, expected_anchor=anchor)
    releases = {n: control.release(r["candidates"]["normal"]) for n, r in readers.items()}
    rejected(checks, "current_read_only_replica_cannot_write", lambda: control.authorize_write("replica-b", 2, checkpoint))
    rejected(checks, "consumed_result_cannot_replay", lambda: control.release(readers["replica-a"]["candidates"]["normal"]))
    forged = copy.deepcopy(readers["replica-b"]["candidates"]["pending"])
    forged["ticket"]["permission"] = "write"
    rejected(checks, "read_ticket_cannot_be_promoted", lambda: control.release(forged))
    control.revoke(checkpoint)
    for node, reader in readers.items():
        rejected(checks, "pending_after_revocation:" + node, lambda r=reader: control.release(r["candidates"]["pending"]))
    rejected(checks, "old_checkpoint_read_denied", lambda: control.release(original["pending_source"]))
    rejected(checks, "revoked_checkpoint_cannot_reactivate", lambda: control.migrate("replica-b", expected_epoch=3,
             expected_owner="replica-a", prepared=readers["replica-b"]["prepared"]))
    rejected(checks, "no_fresh_grant_for_revoked_checkpoint", lambda: control.issue("replica-a"))
    state = control.state()
    events = [dict(x) for x in control.db.execute("SELECT * FROM events ORDER BY seq")]
    control.close()
    write_json(out / "events.json", events)
    publish_stage(out, dict(phase="final", passed=True, binding=binding, checkpoint=checkpoint,
                           identities=identities, independent_runner_instances=len(identities),
                           state=state, checks=checks, crashes=migrated["crashes"],
                           fresh_readback_releases=releases, retained_checkpoint_bytes=True,
                           expected_transport="same workflow run/attempt, exact artifact names and external DB/checkpoint anchors"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("source", "replica", "migrate", "readback", "final", "crash"))
    parser.add_argument("--input", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--node", choices=NODES)
    parser.add_argument("--mode", choices=("before_commit", "after_commit"))
    args = parser.parse_args()
    if args.phase == "crash":
        crash_stage(args.input, args.mode)
        return
    args.out.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    try:
        if args.phase == "source":
            source_stage(args.input, args.out)
        else:
            binding = task_binding(os.environ["FED_NONCE"])
            checkpoint, anchor = os.environ["FED_CHECKPOINT"], os.environ.get("FED_AUTHORITY_SHA256")
            if args.phase in ("replica", "readback"):
                reader_stage(args.input, args.out, args.node, args.phase, binding, checkpoint, anchor)
            elif args.phase == "migrate":
                migrate_stage(args.input, args.out, binding, checkpoint, anchor)
            else:
                final_stage(args.input, args.out, binding, checkpoint, anchor)
        write_json(args.out / "timing.json", dict(wall_seconds=time.monotonic() - started,
                   files_bytes=sum(p.stat().st_size for p in args.out.rglob("*") if p.is_file())))
    except Exception as error:
        write_json(args.out / "blocked.json", dict(phase=args.phase, passed=False,
                   error_type=type(error).__name__, error=str(error), wall_seconds=time.monotonic() - started))
        raise


if __name__ == "__main__":
    main()
