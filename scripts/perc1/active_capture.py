"""Execute advisory additional-perception choices through the existing owner.

The selector never receives evaluator outcomes. Decisions, including STOP, are
retained before effects, under the local owner's existing exclusive writer lock.
This does not attest source independence, learned value, physical cost or remote
fencing. Quoted microcredits and the owner's acquisition-attempt cap are distinct.
"""

import json
import os
import stat
import time
from pathlib import Path

from .acquisition import choose, features as validate_features
from .capture_entry import decode_native_wire
from .owner import UnknownOutcome
from .schema import canonical, digest, exact, identifier, require, sha

KINDS = ("expand_roi", "change_view", "reobserve")
MAX_DECISION_BYTES = 65536


def observed_prefix(owner, task_sha256, operation_ids):
    """Bind a task to successful retained owner receipts, not claimed hashes.

    An optional latent summary is the last encoded observation's token mean, capped
    at 64 coordinates. Exact source evidence stays in its original owner receipt.
    This summary establishes local lineage, not truth of the observation or task.
    """
    require(digest(task_sha256) != "0" * 64, "empty task identity")
    require(
        type(operation_ids) is list and len(operation_ids) <= 128,
        "prefix operation bound",
    )
    for operation_id in operation_ids:
        identifier(operation_id)
    require(
        len(set(operation_ids)) == len(operation_ids), "duplicate prefix operation"
    )
    receipts, latent = [], []
    for operation_id in operation_ids:
        receipt = owner.receipt(operation_id)
        require(receipt["status"] == "executed", "failed observation in actor prefix")
        receipts.append(receipt["receipt_sha256"])
        result = receipt["result"]
        if result.get("schema") == "perc1.owned-encoding.v1":
            decode_native_wire(result)
            tokens = result["producer"]["observation"]["latents"]
            require(
                type(tokens) is list and 0 < len(tokens) <= 64, "latent count bound"
            )
            values = [item["values_q24"] for item in tokens]
            width = len(values[0])
            require(
                0 < width <= 64 and all(len(row) == width for row in values),
                "latent summary dimension bound",
            )
            require(
                all(
                    type(v) is int and -(2**31) <= v < 2**31
                    for row in values
                    for v in row
                ),
                "invalid retained Q24 coordinate",
            )
            latent = [
                sum(row[j] for row in values) / len(values) / 2**24
                for j in range(width)
            ]
    return {
        "schema": "perc1.active-prefix.v1",
        "task_sha256": task_sha256,
        "owner_binding_sha256": sha(owner.binding),
        "operation_ids": list(operation_ids),
        "receipt_sha256s": receipts,
        "latent_summary": latent,
    }


def _retain_decision(owner, decision):
    """One immutable decision per operation, including decisions with no effect."""
    directory = owner.root / "active-decisions"
    directory.mkdir(exist_ok=True, mode=0o700)
    require(not directory.is_symlink(), "decision directory symlink refused")
    raw = canonical(decision)
    require(len(raw) <= MAX_DECISION_BYTES, "decision exceeds retained bound")
    path = directory / (sha(decision["operation_id"].encode()) + ".json")
    if not path.exists():
        require(sum(1 for _ in directory.iterdir()) < 4096, "decision history bound")
        try:
            descriptor = os.open(
                path,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
            )
        except FileExistsError:
            pass
        else:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
    descriptor = os.open(path, os.O_RDWR | os.O_NOFOLLOW)
    with os.fdopen(descriptor, "rb") as stream:
        info = os.fstat(stream.fileno())
        require(
            stat.S_ISREG(info.st_mode)
            and info.st_nlink == 1
            and info.st_size <= MAX_DECISION_BYTES,
            "invalid retained decision file",
        )
        require(
            stream.read(MAX_DECISION_BYTES + 1) == raw,
            "operation decision changed or incomplete; no new dispatch",
        )
        # A prior process may have stopped after complete bytes but before fsync.
        # Re-establish durability on replay before allowing any dispatch.
        os.fsync(stream.fileno())
    descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return sha(raw)


def observe(
    producer,
    operation_id,
    head,
    candidates,
    capture,
    *,
    expected_head_sha256,
    task_sha256,
    observed_operations,
    mode="active",
    seed=0,
):
    """Select STOP or a registered capture, retaining failure/UNKNOWN attempts.

    Candidates contain id, kind, upper_cost, features and a normal OwnedProducer
    request. Kind labels route operator-supplied sources; they do not prove geometric
    expansion or a live viewpoint change. The capture callback stays operator-owned.
    Only successful retained observations may enter a prefix; their receipts and any
    nonempty latent summary must match the candidate features exactly.

    Every returned measurement covers this invocation, including replay overhead.
    The original owner dispatch wall time is nested evidence, never an added charge.
    """
    started, cpu = time.perf_counter_ns(), time.process_time_ns()
    identifier(operation_id)
    require(sha(head) == digest(expected_head_sha256), "frozen selector head changed")
    require(
        type(candidates) is list and len(candidates) <= 256, "candidate count bound"
    )
    require(
        len(canonical(candidates)) <= MAX_DECISION_BYTES, "candidate byte bound"
    )
    prefix = observed_prefix(producer.owner, task_sha256, observed_operations)
    offerings = []
    for candidate in candidates:
        exact(candidate, "id kind upper_cost features request")
        require(candidate["kind"] in KINDS, "unknown perception action kind")
        exact(candidate["request"], "source_id representation regions")
        features = candidate["features"]
        validate_features(features)
        require(
            features["prefix_sha256"] == sha(prefix)
            and features["acquired_receipt_sha256s"] == prefix["receipt_sha256s"]
            and (
                features["acquired_latent"] == []
                or features["acquired_latent"] == prefix["latent_summary"]
            ),
            "candidate features include unretained or changed evidence",
        )
        offerings.append(
            {k: candidate[k] for k in ("id", "upper_cost", "features")}
        )
    selection = choose(head, offerings, mode=mode, seed=seed)
    selected = next(
        (c for c in candidates if c["id"] == selection["candidate_id"]), None
    )
    decision = {
        "schema": "perc1.active-capture-decision.v1",
        "operation_id": operation_id,
        "owner_binding_sha256": sha(producer.owner.binding),
        "code_sha256": sha(Path(__file__).read_bytes()),
        "head_sha256": expected_head_sha256,
        "prefix": prefix,
        "catalog_sha256": sha(candidates),
        "mode": mode,
        "seed": seed,
        "selection": selection,
        "kind": selected["kind"] if selected else None,
        "request": selected["request"] if selected else None,
        "quoted_microcredits": selected["upper_cost"] if selected else 0,
    }
    # Detach mutable caller dictionaries before any operator callback runs.
    decision = json.loads(canonical(decision))
    decision_sha256 = _retain_decision(producer.owner, decision)
    planning_ns = time.perf_counter_ns() - started
    before = producer.owner.status()["reserved_units"]
    receipt, outcome = None, "stopped"
    entry_started = time.perf_counter_ns()
    if selected is not None:
        try:
            receipt = producer.observe(
                operation_id,
                decision["request"],
                capture,
                decision_sha256=decision_sha256,
            )
            outcome = receipt["status"]
        except UnknownOutcome:
            outcome = "unknown"
    entry_ns = time.perf_counter_ns() - entry_started
    owner_status = producer.owner.status()
    return {
        "schema": "perc1.active-capture-result.v1",
        "decision": decision,
        "decision_sha256": decision_sha256,
        "outcome": outcome,
        "owner_receipt": receipt,
        "owner_status": owner_status,
        "new_attempt_reservations": owner_status["reserved_units"] - before,
        "measurements": {
            "invocation_wall_ns": time.perf_counter_ns() - started,
            "invocation_process_cpu_ns": time.process_time_ns() - cpu,
            "planning_and_decision_retention_wall_ns": planning_ns,
            "owned_entry_wall_ns": entry_ns,
            "retained_original_dispatch_wall_ns": (
                receipt["measurements"]["wall_ns"] if receipt else None
            ),
            "phase_breakdown": None,
            "energy_joules": None,
            "provider_billing": None,
            "scope": (
                "this invocation includes planning, persistence and executed "
                "capture/OCR/encoding/wait; original dispatch is nested historical "
                "evidence on replay, never additive"
            ),
        },
        "quoted_microcredits_enforced": False,
        "terminal_quality": None,
        "observed_net_benefit": None,
        "scientific_qualified": False,
        "adoption": "NoUpdate",
    }
