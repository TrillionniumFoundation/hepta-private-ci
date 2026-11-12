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
MAX_TRAINED_HEAD_BYTES = 2 * 1024 * 1024
# Exact shipped v2 reader/selector at a5583f0f. Its prefix and selection path
# below stays unchanged; other historical code identities remain refused.
LEGACY_V2_CODE_SHA256 = (
    "fa0edc0b0fe696f0b7e71a1f6a2f3ff7ccc8ca3d1d0334bb552839275a419eb6"
)


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
    require(len(set(operation_ids)) == len(operation_ids), "duplicate prefix operation")
    receipts, latent = [], []
    for operation_id in operation_ids:
        receipt = owner.receipt(operation_id)
        require(receipt["status"] == "executed", "failed observation in actor prefix")
        receipts.append(receipt["receipt_sha256"])
        result = receipt["result"]
        if result.get("schema") in (
            "perc1.owned-encoding.v1",
            "perc1.owned-encoding.v2",
        ):
            if result["schema"] == "perc1.owned-encoding.v2":
                decode_native_wire(result, source_root=owner.root)
            else:
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


def _retain(owner, kind, identity, value, *, max_bytes=MAX_DECISION_BYTES):
    """Retain immutable bounded JSON under the local owner's existing writer lock."""
    directory = owner.root / kind
    directory.mkdir(exist_ok=True, mode=0o700)
    require(not directory.is_symlink(), "decision directory symlink refused")
    parent = os.open(owner.root, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(parent)
    finally:
        os.close(parent)
    raw = canonical(value)
    require(len(raw) <= max_bytes, "decision/head exceeds retained bound")
    path = directory / (identity + ".json")
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
            and info.st_size <= max_bytes,
            "invalid retained decision file",
        )
        require(
            stream.read(max_bytes + 1) == raw,
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


def _read(owner, kind, identity, *, max_bytes=MAX_DECISION_BYTES):
    directory = owner.root / kind
    require(not directory.is_symlink(), "decision directory symlink refused")
    descriptor = os.open(
        directory / (identity + ".json"), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
    )
    with os.fdopen(descriptor, "rb") as stream:
        info = os.fstat(stream.fileno())
        require(
            stat.S_ISREG(info.st_mode)
            and info.st_nlink == 1
            and 0 < info.st_size <= max_bytes,
            "invalid retained decision/head file",
        )
        raw = stream.read(max_bytes + 1)
    value = json.loads(raw)
    require(canonical(value) == raw, "noncanonical retained decision/head")
    return value


def _selector_sha256():
    return sha(
        {
            name: sha(Path(__file__).with_name(name + ".py").read_bytes())
            for name in ("acquisition", "mlp_head")
        }
    )


def _select(head, candidates, prefix, mode, seed):
    require(
        type(candidates) is list and len(candidates) <= 256, "candidate count bound"
    )
    require(len(canonical(candidates)) <= MAX_DECISION_BYTES, "candidate byte bound")
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
                (
                    prefix["schema"] == "perc1.active-prefix.v1"
                    and features["acquired_latent"] == []
                )
                or features["acquired_latent"] == prefix["latent_summary"]
            ),
            "candidate features include unretained or changed evidence",
        )
        offerings.append({k: candidate[k] for k in ("id", "upper_cost", "features")})
    selection = choose(head, offerings, mode=mode, seed=seed)
    selected = next(
        (c for c in candidates if c["id"] == selection["candidate_id"]), None
    )
    return selection, selected


def _check_operation(owner, decision):
    # Package-internal read preserves the existing owner version and reservation
    # rules. A STOP must not reuse an ordinary capture's already admitted token.
    row = owner._row(decision["operation_id"])
    if row is not None:
        owner._validate(row)
        request = json.loads(row["payload"])["request"]
        require(
            decision["selection"]["action"] == "ACQUIRE"
            and request.get("decision_sha256") == sha(decision)
            and request.get("capture") == decision["request"],
            "operation already belongs to another decision or ordinary capture",
        )


def read_decision(owner, operation_id):
    """Recheck a stored decision and original head/prefix without new effects.

    An ACQUIRE decision alone does not establish that dispatch completed. The owner
    receipt/status remains the separate authority for that local effect outcome.
    """
    owner.status()  # Require an open, exclusively owned journal before sidecar I/O.
    identifier(operation_id)
    decision = _read(owner, "active-decisions", sha(operation_id.encode()))
    profiled = decision.get("schema") == "perc1.active-capture-decision.v3"
    exact(
        decision,
        (
            "schema operation_id owner_binding_sha256 code_sha256 selector_code_sha256 "
            "head_sha256 prefix catalog_sha256 catalog mode seed selection kind request quoted_microcredits"
            + (" feature_profile_sha256" if profiled else "")
        ),
    )
    require(
        decision["schema"]
        in ("perc1.active-capture-decision.v2", "perc1.active-capture-decision.v3")
        and decision["operation_id"] == operation_id
        and decision["owner_binding_sha256"] == sha(owner.binding)
        and (
            decision["code_sha256"] == sha(Path(__file__).read_bytes())
            or (not profiled and decision["code_sha256"] == LEGACY_V2_CODE_SHA256)
        )
        and decision["selector_code_sha256"] == _selector_sha256(),
        "decision owner or execution version changed",
    )
    head = _read(
        owner,
        "active-heads",
        digest(decision["head_sha256"]),
        max_bytes=MAX_TRAINED_HEAD_BYTES if profiled else MAX_DECISION_BYTES,
    )
    require(sha(head) == decision["head_sha256"], "retained selector head changed")
    prefix = decision["prefix"]
    if profiled:
        from .source_feature_profile import bind_head
        from .source_feature_profile import observed_prefix as profiled_prefix

        profile = _read(
            owner, "active-feature-profiles", digest(decision["feature_profile_sha256"])
        )
        require(
            sha(profile) == decision["feature_profile_sha256"],
            "retained feature profile changed",
        )
        bind_head(profile, head)
        restored_prefix = profiled_prefix(
            owner, prefix["task_sha256"], prefix["operation_ids"], profile
        )
    else:
        restored_prefix = observed_prefix(
            owner, prefix["task_sha256"], prefix["operation_ids"]
        )
    require(
        restored_prefix == prefix,
        "retained actor prefix changed",
    )
    require(
        sha(decision["catalog"]) == decision["catalog_sha256"],
        "retained catalog changed",
    )
    selection, selected = _select(
        head, decision["catalog"], prefix, decision["mode"], decision["seed"]
    )
    require(
        selection == decision["selection"]
        and decision["kind"] == (selected["kind"] if selected else None)
        and decision["request"] == (selected["request"] if selected else None)
        and decision["quoted_microcredits"]
        == (selected["upper_cost"] if selected else 0),
        "retained decision does not match its frozen selector inputs",
    )
    _check_operation(owner, decision)
    return decision


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
    feature_profile=None,
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
    producer.owner.status()
    identifier(operation_id)
    require(sha(head) == digest(expected_head_sha256), "frozen selector head changed")
    if feature_profile is None:
        prefix = observed_prefix(producer.owner, task_sha256, observed_operations)
    else:
        from .source_feature_profile import bind_head
        from .source_feature_profile import observed_prefix as profiled_prefix

        feature_profile = json.loads(canonical(feature_profile))
        bind_head(feature_profile, head)
        prefix = profiled_prefix(
            producer.owner, task_sha256, observed_operations, feature_profile
        )
    selection, selected = _select(head, candidates, prefix, mode, seed)
    decision = {
        "schema": "perc1.active-capture-decision.v2"
        if feature_profile is None
        else "perc1.active-capture-decision.v3",
        "operation_id": operation_id,
        "owner_binding_sha256": sha(producer.owner.binding),
        "code_sha256": sha(Path(__file__).read_bytes()),
        "selector_code_sha256": _selector_sha256(),
        "head_sha256": expected_head_sha256,
        "prefix": prefix,
        "catalog_sha256": sha(candidates),
        "catalog": candidates,
        "mode": mode,
        "seed": seed,
        "selection": selection,
        "kind": selected["kind"] if selected else None,
        "request": selected["request"] if selected else None,
        "quoted_microcredits": selected["upper_cost"] if selected else 0,
    }
    if feature_profile is not None:
        decision["feature_profile_sha256"] = sha(feature_profile)
    # Detach mutable caller dictionaries before any operator callback runs.
    decision = json.loads(canonical(decision))
    _check_operation(producer.owner, decision)
    _retain(
        producer.owner,
        "active-heads",
        expected_head_sha256,
        head,
        max_bytes=MAX_DECISION_BYTES
        if feature_profile is None
        else MAX_TRAINED_HEAD_BYTES,
    )
    if feature_profile is not None:
        _retain(
            producer.owner,
            "active-feature-profiles",
            sha(feature_profile),
            feature_profile,
        )
    decision_sha256 = _retain(
        producer.owner, "active-decisions", sha(operation_id.encode()), decision
    )
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
