"""Two independent hosted jobs transfer a real adapter and replay a withdrawal.

No public tunnel, shared filesystem, source DB, facts or gold enter target
inference. The source later sends one explicitly requested evidence record;
it is received only after target inference and is already withdrawn on arrival.
"""

# Standalone entry resolves the pinned sibling implementation.
# ruff: noqa: E402
import argparse
import base64
from dataclasses import asdict
import hashlib
import os
from pathlib import Path
import resource
import secrets
import sys
import time

SCRIPTS = Path(__file__).resolve().parents[1]
for module in (
    "memory_cell",
    "memory_cell_service",
    "memory_cell_network",
    "memory_cell_system",
):
    sys.path.insert(0, str(SCRIPTS / module))

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from artifact_relay import await_artifact
from memory_service import MemoryService
from network_checkpoints import pack
from network_worker import Worker
from relay_protocol import (
    PROTOCOL,
    SCOPE,
    identity,
    provenance,
    read,
    retain,
    runtime,
    seal,
    verify,
)
from source_evidence import SourceEvidence
from system_runtime import train_once

QUESTION = "According to the retained record, state the color associated with {entity}."
QUESTIONS = [QUESTION.format(entity=f"remote_{i:02d}") for i in range(3)]


def worker(root, model, node_id, snapshot):
    def source_cut(scope, cell):
        if (scope, cell) != (SCOPE, "memory"):
            raise ValueError("relay only authorizes the registered cell and scope")
        return snapshot

    # No HTTP is called: the independently verified relay supplies the cut.
    return Worker(
        root, node_id, "http://127.0.0.1:1", b"", model, authority_snapshot=source_cut
    )


def refused(instance):
    before = instance.fences.calls()
    try:
        instance.read(SCOPE, "memory", QUESTIONS, "adapter")
    except ValueError as error:
        receipt = dict(
            rejected=True,
            reason=str(error),
            callbacks_before=before,
            callbacks_after=instance.fences.calls(),
        )
        if receipt["callbacks_before"] != receipt["callbacks_after"]:
            raise ValueError("rejected read entered the model") from error
        return receipt
    raise ValueError("withdrawn or migrated read was served")


def source_prepare(root, model, secret_file):
    retain(root / "protocol.json", PROTOCOL)
    retain(root / "runtime.json", runtime())
    who = identity()
    retain(root / "source-identity.json", who)
    service = MemoryService(root / "source-owner", SCOPE)
    colors = ["red", "blue", "green", "yellow", "orange", "purple", "black", "white"]
    facts = []
    for i in range(3):
        value = colors.pop(secrets.randbelow(len(colors)))
        receipt = service.write(
            f"remote/source_{i:02d}", f"remote_{i:02d}", "color", value
        )
        facts.append(dict(entity=f"remote_{i:02d}", value=value, write=asdict(receipt)))
    retain(root / "source-facts.json", dict(facts=facts))
    trained = train_once(service, model, root, "train", PROTOCOL["train_updates"])
    retain(root / "training.json", trained)
    if trained["status"] != "published":
        raise ValueError("source training did not publish")
    active = service.parameter_binding()["active"]
    placement = dict(
        scope=SCOPE,
        cell_id="memory",
        node_id="source-a",
        generation=0,
        manifest_sha256=active.manifest_sha256,
        roots=list(active.roots),
    )
    snapshot = dict(frontier=asdict(service.authority_view()), placement=placement)
    snapshot["frontier"]["revoked"] = list(snapshot["frontier"]["revoked"])
    local = worker(root / "worker-a", model, "source-a", snapshot)
    package = pack(active.directory, active.manifest_sha256, SCOPE)
    installed = local.dispatch(
        dict(
            op="stage", package=package, retained_manifest_sha256=active.manifest_sha256
        )
    )
    retain(root / "source-install.json", installed)
    for control in ("adapter", "base", "shuffled"):
        retain(
            root / f"source-{control}.json",
            local.read(SCOPE, "memory", QUESTIONS, control),
        )
    key = Ed25519PrivateKey.generate()
    if root.resolve() in secret_file.resolve().parents:
        raise ValueError("private relay key must be outside uploaded evidence")
    secret_file.parent.mkdir(parents=True, exist_ok=True)
    with secret_file.open("xb") as stream:
        os.fchmod(stream.fileno(), 0o600)
        stream.write(key.private_bytes_raw())
        stream.flush()
        os.fsync(stream.fileno())
    target = dict(snapshot, placement=dict(placement, node_id="worker-b", generation=1))
    retain(
        root / "source-old-placement-refusal.json",
        refused(worker(root / "worker-a", model, "source-a", target)),
    )
    payload = dict(
        **provenance("offer"),
        public_key=key.public_key().public_bytes_raw().hex(),
        source_identity=who,
        package=package,
        base_identity=active.base_identity,
        source_snapshot=snapshot,
        target_snapshot=target,
        questions=QUESTIONS,
        evidence_grant_root=facts[0]["write"]["source_digest"],
        source_database_transferred=False,
    )
    retain(root / "out-offer" / "offer.json", seal(payload, key))


def source_withdraw(root, model, secret_file):
    ready_path = await_artifact("ready", root / "in-ready")
    ready = read(ready_path)
    offer_file = read(root / "out-offer" / "offer.json")
    offer = verify(offer_file, offer_file["payload"]["public_key"], "offer")
    target_identity = ready["identity"]
    if (
        target_identity["boot_id_sha256"] == offer["source_identity"]["boot_id_sha256"]
        or target_identity["job"] == offer["source_identity"]["job"]
        or ready["manifest_sha256"] != offer["package"]["manifest_sha256"]
    ):
        raise ValueError(
            "target is not an independent runner with the exact checkpoint"
        )
    local = worker(root / "worker-a", model, "source-a", offer["target_snapshot"])
    retain(root / "source-after-target-ready-refusal.json", refused(local))
    service = MemoryService(root / "source-owner", SCOPE)
    request = ready["evidence_request"]
    expected = dict(
        op="evidence",
        scope=SCOPE,
        source_root=offer["evidence_grant_root"],
        expected_epoch=offer["target_snapshot"]["frontier"]["epoch"],
    )
    if request != expected:
        raise ValueError("target evidence request lacks the exact root grant")
    evidence = SourceEvidence(service.store).dispatch(request)
    service.revoke("remote/source_00", 0)
    frontier = asdict(service.authority_view())
    frontier["revoked"] = list(frontier["revoked"])
    snapshot = dict(frontier=frontier, placement=offer["target_snapshot"]["placement"])
    key = Ed25519PrivateKey.from_private_bytes(secret_file.read_bytes())
    retain(
        root / "out-withdrawal" / "withdrawal.json",
        seal(
            dict(
                **provenance("withdrawal"),
                snapshot=snapshot,
                evidence_before_withdrawal=evidence,
                offer_manifest_sha256=offer["package"]["manifest_sha256"],
            ),
            key,
        ),
    )


def target_read(root, model):
    retain(root / "protocol.json", PROTOCOL)
    retain(root / "runtime.json", runtime())
    path = await_artifact("offer", root / "in-offer")
    envelope = read(path)
    offer = verify(envelope, envelope["payload"]["public_key"], "offer")
    if (
        offer["questions"] != QUESTIONS
        or offer["source_database_transferred"] is not False
    ):
        raise ValueError("target receives only fixed queries and checkpoint metadata")
    who = identity()
    retain(root / "target-identity.json", who)
    local = worker(root / "worker-b", model, "worker-b", offer["target_snapshot"])
    installed = local.dispatch(
        dict(
            op="stage",
            package=offer["package"],
            retained_manifest_sha256=offer["package"]["manifest_sha256"],
        )
    )
    if installed["base_identity"] != offer["base_identity"]:
        raise ValueError("transferred base identity changed")
    retain(root / "target-install.json", installed)
    journal = local.read(SCOPE, "memory", QUESTIONS, "adapter")
    retain(root / "target-read.json", journal)
    load_started = time.perf_counter()
    load_rows = []
    for ordinal in range(PROTOCOL["load_requests"]):
        index = ordinal % len(QUESTIONS)
        before = time.perf_counter()
        result = local.read(SCOPE, "memory", [QUESTIONS[index]], "adapter")
        latency = time.perf_counter() - before
        retain(root / "load" / f"request-{ordinal:03d}.json", result)
        load_rows.append(
            dict(
                ordinal=ordinal,
                question_index=index,
                wall_seconds=latency,
                raw_row=result["journal"]["rows"][0],
            )
        )
    wall = time.perf_counter() - load_started
    latencies = sorted(item["wall_seconds"] for item in load_rows)
    load = dict(
        requests=len(load_rows),
        wall_seconds=wall,
        requests_per_second=len(load_rows) / wall,
        p50_seconds=latencies[(len(latencies) - 1) // 2],
        p95_seconds=latencies[(95 * len(latencies) + 99) // 100 - 1],
        arrival_model=PROTOCOL["load_arrivals"],
        control_cut="delivered signed artifact, not online mTLS authority",
        concurrency=1,
        rows=load_rows,
    )
    retain(root / "load-summary.json", load)
    request = dict(
        op="evidence",
        scope=SCOPE,
        source_root=offer["evidence_grant_root"],
        expected_epoch=offer["target_snapshot"]["frontier"]["epoch"],
    )
    retain(
        root / "out-ready" / "ready.json",
        dict(
            **provenance("ready"),
            identity=who,
            manifest_sha256=installed["manifest_sha256"],
            raw_rows=journal["journal"]["rows"],
            load=load,
            evidence_request=request,
            source_database_present=any(root.rglob("sources.sqlite")),
        ),
    )


def target_withdraw(root, model):
    path = await_artifact("withdrawal", root / "in-withdrawal")
    offer_file = read(root / "in-offer" / "offer.json")
    offer = verify(offer_file, offer_file["payload"]["public_key"], "offer")
    withdrawn = verify(read(path), offer["public_key"], "withdrawal")
    if withdrawn["offer_manifest_sha256"] != offer["package"]["manifest_sha256"]:
        raise ValueError("withdrawal applies to another checkpoint")
    local = worker(root / "worker-b", model, "worker-b", withdrawn["snapshot"])
    retain(root / "target-withdraw-refusal.json", refused(local))
    evidence = withdrawn["evidence_before_withdrawal"]
    raw = base64.b64decode(evidence["payload_base64"], validate=True)
    if (
        hashlib.sha256(raw).hexdigest() != evidence["source_root"]
        or evidence["payload_sha256"] != evidence["source_root"]
        or len(raw) != evidence["bytes"]
        or evidence["source_root"] != offer["evidence_grant_root"]
        or evidence["source_root"] not in withdrawn["snapshot"]["frontier"]["revoked"]
    ):
        raise ValueError("requested evidence is not covered by the withdrawal")
    retain(
        root / "evidence-refusal.json",
        dict(
            received_from_remote_source=True,
            current_support_accepted=False,
            reason="source withdrawn before delivery",
            bytes=evidence["bytes"],
            source_root=evidence["source_root"],
        ),
    )


def target_replay(root, model):
    offer_file = read(root / "in-offer" / "offer.json")
    offer = verify(offer_file, offer_file["payload"]["public_key"], "offer")
    local = worker(root / "worker-b", model, "worker-b", offer["target_snapshot"])
    rejection = refused(local)
    retain(root / "target-restart-replay-refusal.json", rejection)
    retain(
        root / "out-finished" / "finished.json",
        dict(
            **provenance("finished"),
            identity=identity(),
            withdrawal=read(root / "target-withdraw-refusal.json"),
            restart_replay=rejection,
            evidence=read(root / "evidence-refusal.json"),
            decoder_callbacks_total=local.fences.calls(),
            source_database_present=any(root.rglob("sources.sqlite")),
        ),
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "phase",
        choices=(
            "source-prepare",
            "source-withdraw",
            "target-read",
            "target-withdraw",
            "target-replay",
        ),
    )
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--secret-file", type=Path)
    args = parser.parse_args()
    args.root.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    completed = False
    try:
        if args.phase.startswith("source-"):
            if args.secret_file is None:
                parser.error(
                    "source role needs its private signing file outside evidence"
                )
            globals()[args.phase.replace("-", "_")](
                args.root, args.model, args.secret_file
            )
        else:
            globals()[args.phase.replace("-", "_")](args.root, args.model)
        completed = True
    finally:
        own, children = (
            resource.getrusage(resource.RUSAGE_SELF),
            resource.getrusage(resource.RUSAGE_CHILDREN),
        )
        retain(
            args.root / (args.phase + "-resources.json"),
            dict(
                phase=args.phase,
                completed=completed,
                wall_seconds=time.perf_counter() - started,
                cpu_seconds=own.ru_utime
                + own.ru_stime
                + children.ru_utime
                + children.ru_stime,
                coordinator_peak_rss_bytes=own.ru_maxrss * 1024,
                maximum_child_peak_rss_bytes=children.ru_maxrss * 1024,
                aggregate_peak_rss_measured=False,
            ),
        )
