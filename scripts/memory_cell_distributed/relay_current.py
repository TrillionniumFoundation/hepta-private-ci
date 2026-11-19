"""Current remote evidence is acknowledged before the sole source writer revokes.

The original training, inference, withdrawal and restart recipes remain intact.
No target model call follows receipt of source evidence. Same-run Actions is the
trust/bootstrap transport; this does not qualify online or replicated authority.
"""

# ruff: noqa: E402
import argparse
from dataclasses import asdict
import os
from pathlib import Path
import resource
import time

import relay_trial as legacy
import relay_evaluate
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from artifact_relay import await_artifact
from memory_service import MemoryService
from relay_current_contract import (
    acknowledgment_binding,
    digest,
    evidence_request,
    same_runner,
)
from relay_current_contract import verify_ack, verify_evidence, verify_ready
from relay_protocol import (
    PROTOCOL,
    SCOPE,
    identity,
    provenance,
    read,
    retain,
    seal,
    verify,
)
from source_evidence import SourceEvidence


def offer_at(path):
    envelope = read(path)
    return verify(envelope, envelope["payload"]["public_key"], "offer")


def secret_at(root, path):
    if path is None or path.is_symlink() or root.resolve() in path.resolve().parents:
        raise ValueError("relay private key must be outside uploaded evidence")
    return path


def target_ready(root, model, secret_file):
    ready = read(root / "out-ready/ready.json")
    if not same_runner(identity(), ready["identity"]):
        raise ValueError("ready signer is not the actual target reader")
    key = Ed25519PrivateKey.generate()
    path = secret_at(root, secret_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        os.fchmod(stream.fileno(), 0o600)
        stream.write(key.private_bytes_raw())
        stream.flush()
        os.fsync(stream.fileno())
    envelope = seal(
        dict(ready, public_key=key.public_key().public_bytes_raw().hex()), key
    )
    verify_ready(envelope, offer_at(root / "in-offer/offer.json"))
    retain(root / "out-current-ready/ready.json", envelope)


def source_evidence(root, model, secret_file):
    offer = offer_at(root / "out-offer/offer.json")
    ready_envelope = read(await_artifact("ready", root / "in-ready-signed"))
    ready = verify_ready(ready_envelope, offer)
    retain(root / "in-ready/ready.json", ready)
    local = legacy.worker(
        root / "worker-a", model, "source-a", offer["target_snapshot"]
    )
    retain(root / "source-after-target-ready-refusal.json", legacy.refused(local))
    source = MemoryService(root / "source-owner", SCOPE)
    snapshot = source.snapshot()
    reader = SourceEvidence(source.store)
    evidence = reader.dispatch(ready["evidence_request"])
    if source.snapshot() != snapshot:
        raise ValueError("source changed while preparing current evidence")
    frontier = asdict(source.authority_view())
    frontier["revoked"] = list(frontier["revoked"])
    payload = dict(
        **provenance("current-evidence"),
        offer_sha256=digest(offer),
        ready_sha256=digest(ready_envelope),
        target_public_key=ready["public_key"],
        request=evidence_request(offer),
        manifest_sha256=offer["package"]["manifest_sha256"],
        source_frontier=frontier,
        source_snapshot_sha256=snapshot["digest"],
        source_actor=identity(),
        evidence=evidence,
    )
    key = Ed25519PrivateKey.from_private_bytes(
        secret_at(root, secret_file).read_bytes()
    )
    envelope = seal(payload, key)
    verify_evidence(envelope, offer, ready_envelope)
    retain(
        root / "source-current-read.json",
        dict(
            snapshot=snapshot,
            completed_source_reads=reader.completed_reads,
            evidence_sha256=digest(envelope),
        ),
    )
    retain(root / "out-current-evidence/current-evidence.json", envelope)


def target_ack(root, model, secret_file):
    offer = offer_at(root / "in-offer/offer.json")
    ready = read(root / "out-current-ready/ready.json")
    local = legacy.worker(
        root / "worker-b", model, "worker-b", offer["target_snapshot"]
    )
    before = local.fences.calls()
    envelope = read(await_artifact("current-evidence", root / "in-current-evidence"))
    value = verify_evidence(envelope, offer, ready)
    payload = dict(
        **provenance("current-ack"),
        **acknowledgment_binding(offer, ready, envelope),
        target_actor=identity(),
        accepted_under_delivered_cut=True,
        source_database_present=any(root.rglob("sources.sqlite")),
        callbacks_before=before,
        callbacks_after=local.fences.calls(),
    )
    key = Ed25519PrivateKey.from_private_bytes(
        secret_at(root, secret_file).read_bytes()
    )
    acknowledgment = seal(payload, key)
    verify_ack(acknowledgment, offer, ready, envelope)
    retain(
        root / "target-current-evidence.json",
        dict(
            evidence=value["evidence"],
            accepted_under_delivered_cut=True,
            online_authority_checked=False,
            causal_source_confirmation_pending=True,
            model_callbacks_added=local.fences.calls() - before,
        ),
    )
    retain(root / "out-current-ack/current-ack.json", acknowledgment)


def source_ack_withdraw(root, model, secret_file):
    offer = offer_at(root / "out-offer/offer.json")
    ready = read(root / "in-ready-signed/ready.json")
    evidence_envelope = read(root / "out-current-evidence/current-evidence.json")
    acknowledgment = read(await_artifact("current-ack", root / "in-current-ack"))
    verify_ack(acknowledgment, offer, ready, evidence_envelope)
    actor = identity()
    if not same_runner(actor, offer["source_identity"]):
        raise ValueError("current acknowledgment reached a different source owner")
    source = MemoryService(root / "source-owner", SCOPE)
    before = source.snapshot()
    reader = SourceEvidence(source.store)
    evidence = reader.dispatch(evidence_request(offer))
    if (
        before != source.snapshot()
        or before["digest"] != evidence_envelope["payload"]["source_snapshot_sha256"]
        or evidence != evidence_envelope["payload"]["evidence"]
    ):
        raise ValueError(
            "source was no longer current when exact acknowledgment arrived"
        )
    receipt = dict(
        ack_sha256=digest(acknowledgment),
        evidence_sha256=digest(evidence_envelope),
        snapshot=before,
        evidence=evidence,
        completed_source_reads=reader.completed_reads,
        source_current_after_ack=True,
        source_actor=actor,
        assumption="sole workflow source writer; monotonic source epoch; no volume rollback",
    )
    retain(root / "source-ack-current.json", receipt)
    revoked = source.revoke("remote/source_00", 0)
    frontier = asdict(source.authority_view())
    frontier["revoked"] = list(frontier["revoked"])
    if (
        frontier["epoch"] != before["epoch"] + 1
        or offer["evidence_grant_root"] not in frontier["revoked"]
    ):
        raise ValueError("actual source withdrawal did not advance the authorized root")
    retain(
        root / "source-withdraw-transition.json",
        dict(
            revocation=asdict(revoked),
            frontier=frontier,
            prior_ack_sha256=digest(acknowledgment),
            confirmed_current_sha256=digest(receipt),
        ),
    )
    key = Ed25519PrivateKey.from_private_bytes(
        secret_at(root, secret_file).read_bytes()
    )
    retain(
        root / "out-withdrawal/withdrawal.json",
        seal(
            dict(
                **provenance("withdrawal"),
                snapshot=dict(
                    frontier=frontier, placement=offer["target_snapshot"]["placement"]
                ),
                evidence_before_withdrawal=evidence,
                offer_manifest_sha256=offer["package"]["manifest_sha256"],
                current_ack_sha256=digest(acknowledgment),
                source_ack_current_sha256=digest(receipt),
            ),
            key,
        ),
    )


def target_withdraw(root, model, secret_file):
    legacy.target_withdraw(root, model)
    offer = offer_at(root / "in-offer/offer.json")
    withdrawal = verify(
        read(root / "in-withdrawal/withdrawal.json"), offer["public_key"], "withdrawal"
    )
    acknowledgment = read(root / "out-current-ack/current-ack.json")
    if withdrawal["current_ack_sha256"] != digest(acknowledgment):
        raise ValueError(
            "withdrawal is not causally bound to this target acknowledgment"
        )
    retain(
        root / "current-withdrawal-linked.json",
        dict(
            current_ack_sha256=digest(acknowledgment),
            source_ack_current_sha256=withdrawal["source_ack_current_sha256"],
            withdrawal_link_verified=True,
        ),
    )


def target_finish(root, model, secret_file):
    legacy.target_replay(root, model)
    retain(
        root / "out-current-finished/finished.json",
        dict(
            read(root / "out-finished/finished.json"),
            **read(root / "current-withdrawal-linked.json"),
        ),
    )


def evaluate(root, model, secret_file):
    original_status = relay_evaluate.evaluate(root, model)
    original = read(root / "report.json")
    finished = read(root / "in-finished/finished.json")
    confirmation = read(root / "source-ack-current.json")
    acknowledged = read(root / "in-current-ack/current-ack.json")
    ready = verify_ready(
        read(root / "in-ready-signed/ready.json"),
        offer_at(root / "out-offer/offer.json"),
    )
    checks = dict(
        original_recipe_mechanism_passed=original_status == 0,
        source_observed_exact_ack_while_current=confirmation["source_current_after_ack"]
        is True
        and confirmation["ack_sha256"] == digest(acknowledged),
        target_verified_causal_withdrawal=finished["withdrawal_link_verified"] is True
        and finished["current_ack_sha256"] == digest(acknowledged)
        and finished["source_ack_current_sha256"] == digest(confirmation),
        target_finished_same_authenticated_run_and_runner=all(
            finished.get(key) == value for key, value in provenance("finished").items()
        )
        and same_runner(finished["identity"], ready["identity"]),
    )
    retain(
        root / "current-report.json",
        dict(
            schema="hepta.memory.current-relay.v1",
            checks=checks,
            mechanism_passed=all(checks.values()),
            original_recipe=PROTOCOL,
            original_report_sha256=digest(original),
            raw_accuracy=original["raw_accuracy"],
            current_source_reads=read(root / "source-current-read.json")[
                "completed_source_reads"
            ]
            + confirmation["completed_source_reads"],
            acknowledgment_sha256=digest(acknowledged),
            currentness_assumption=confirmation["assumption"],
            online_authority=False,
            physical_hardware_attested=False,
            production_accepted=False,
            independent_future_tasks=0,
            future_accuracy=None,
            full_research_gates_closed=0,
        ),
    )
    if not all(checks.values()):
        raise ValueError("current relay mechanism qualification failed")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "phase",
        choices=(
            "target-ready",
            "source-evidence",
            "target-ack",
            "source-ack-withdraw",
            "target-withdraw",
            "target-finish",
            "evaluate",
        ),
    )
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--secret-file", type=Path)
    args = parser.parse_args()
    started = time.perf_counter()
    completed = False
    try:
        globals()[args.phase.replace("-", "_")](args.root, args.model, args.secret_file)
        completed = True
    finally:
        own, children = (
            resource.getrusage(resource.RUSAGE_SELF),
            resource.getrusage(resource.RUSAGE_CHILDREN),
        )
        retain(
            args.root / ("current-" + args.phase + "-resources.json"),
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
