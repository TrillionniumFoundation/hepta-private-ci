"""Causal current-evidence handshake; trust starts at the exact Actions run.

Target acceptance refers to the delivered signed cut. The source must later
observe that exact acknowledgment while its monotonic source state is still
unchanged, before it revokes. This is not an online authority or a quorum.
"""

import base64
import hashlib

from authority_contract import encode
from relay_protocol import PROTOCOL, SCOPE, provenance, verify

MAX_EVIDENCE_BYTES = 64 * 1024


def digest(value):
    return hashlib.sha256(encode(value)).hexdigest()


def evidence_request(offer):
    return dict(
        op="evidence",
        scope=SCOPE,
        source_root=offer["evidence_grant_root"],
        expected_epoch=offer["target_snapshot"]["frontier"]["epoch"],
    )


def same_runner(left, right):
    return all(
        left[key] == right[key]
        for key in (
            "source_sha",
            "run_id",
            "run_attempt",
            "job",
            "boot_id_sha256",
            "runner_name",
        )
    )


def verify_ready(envelope, offer):
    ready = verify(envelope, envelope["payload"]["public_key"], "ready")
    source, target = offer["source_identity"], ready["identity"]
    context = provenance("ready")
    if (
        any(
            source[k] != context[k] or target[k] != context[k]
            for k in ("source_sha", "run_id", "run_attempt")
        )
        or source["job"] != "source-owner"
        or target["job"] != "target-worker"
        or source["boot_id_sha256"] == target["boot_id_sha256"]
        or ready["manifest_sha256"] != offer["package"]["manifest_sha256"]
        or ready["evidence_request"] != evidence_request(offer)
        or ready["source_database_present"] is not False
    ):
        raise ValueError("current relay ready identity, grant or placement mismatch")
    return ready


def verify_evidence(envelope, offer, ready_envelope):
    ready = verify_ready(ready_envelope, offer)
    value = verify(envelope, offer["public_key"], "current-evidence")
    expected = dict(
        offer_sha256=digest(offer),
        ready_sha256=digest(ready_envelope),
        request=evidence_request(offer),
        target_public_key=ready["public_key"],
        manifest_sha256=offer["package"]["manifest_sha256"],
        source_frontier=offer["target_snapshot"]["frontier"],
    )
    if any(value[key] != expected[key] for key in expected):
        raise ValueError("current evidence context mismatch")
    frontier, evidence = value["source_frontier"], value["evidence"]
    granted = offer["evidence_grant_root"]
    if (
        frontier["scope"] != SCOPE
        or granted in frontier["revoked"]
        or granted not in offer["target_snapshot"]["placement"]["roots"]
        or evidence["scope"] != SCOPE
        or evidence["source_root"] != granted
        or type(evidence["source_epoch"]) is not int
        or evidence["source_epoch"] != frontier["epoch"]
        or evidence["origin"] != "source_evidence"
        or evidence["parameter_output"] is not False
        or type(evidence["bytes"]) is not int
        or not 0 < evidence["bytes"] <= MAX_EVIDENCE_BYTES
        or len(evidence["payload_base64"]) > 4 * ((MAX_EVIDENCE_BYTES + 2) // 3)
        or not same_runner(value["source_actor"], offer["source_identity"])
    ):
        raise ValueError("current evidence lacks the exact source root/epoch grant")
    raw = base64.b64decode(evidence["payload_base64"], validate=True)
    if (
        len(raw) != evidence["bytes"]
        or hashlib.sha256(raw).hexdigest() != granted
        or evidence["payload_sha256"] != granted
    ):
        raise ValueError("current evidence byte identity mismatch")
    return value


def acknowledgment_binding(offer, ready_envelope, evidence_envelope):
    value = verify_evidence(evidence_envelope, offer, ready_envelope)
    evidence = value["evidence"]
    return dict(
        ready_sha256=digest(ready_envelope),
        evidence_sha256=digest(evidence_envelope),
        source_snapshot_sha256=value["source_snapshot_sha256"],
        manifest_sha256=offer["package"]["manifest_sha256"],
        request=evidence_request(offer),
        source_root=evidence["source_root"],
        source_epoch=evidence["source_epoch"],
        payload_sha256=evidence["payload_sha256"],
        bytes=evidence["bytes"],
    )


def verify_ack(envelope, offer, ready_envelope, evidence_envelope):
    ready = verify_ready(ready_envelope, offer)
    ack = verify(envelope, ready["public_key"], "current-ack")
    expected = acknowledgment_binding(offer, ready_envelope, evidence_envelope)
    if (
        any(ack[key] != expected[key] for key in expected)
        or not same_runner(ack["target_actor"], ready["identity"])
        or ack["accepted_under_delivered_cut"] is not True
        or ack["source_database_present"] is not False
        or ack["callbacks_before"] != ack["callbacks_after"]
        or ack["callbacks_after"] != PROTOCOL["load_requests"] + 1
    ):
        raise ValueError("current evidence acknowledgment mismatch")
    return ack
