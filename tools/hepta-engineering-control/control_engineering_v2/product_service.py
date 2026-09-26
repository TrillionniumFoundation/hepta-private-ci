"""Bounded POSIX control-pipe adapter over the existing engineering owner.

The launcher's pipe and verifier factory are trusted host configuration, not
candidate input. Receipts still pass the typed signature/context verifiers.
This adapter has no worker executor, signing fallback, merge or release action.
"""

from dataclasses import asdict
import importlib
import json
import math
import os
import re
import selectors
import sqlite3
import time

from .cli import MAX_INPUT_BYTES, _record, _records, _unique_pairs
from .control_plane import EngineeringError, WorkEnvelope, checked_id
from .integration_controller import (
    IntegrationStageReceipt, IntegrationTerminalReceipt,
    integration_context_binding, integration_receipt_context,
)
from .orchestration import (
    CompletionReceipt, EngineeringCapacity, EngineeringWorkPackage,
    ReviewCapacity, WorkerProfile,
)
from .product_runtime import EngineeringControlProduct
from .worker_lifecycle import (
    WorkerHeartbeatReceipt, WorkerRegistrationReceipt, WorkerResultReceipt,
)


def load_verifier_factory(specification: str):
    """Load only the operator-selected factory, before accepting any request."""
    if not re.fullmatch(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*:[A-Za-z_]\w*", specification):
        raise EngineeringError("invalid_verifier_factory")
    module, name = specification.split(":")
    try:
        verifier = getattr(importlib.import_module(module), name)()
    except Exception:
        raise EngineeringError("verifier_configuration_failed") from None
    if not callable(getattr(verifier, "verify", None)):
        raise EngineeringError("signature_verifier_required")
    return verifier


def dispatch_product_request(product, request):
    """Translate one bounded request; native operation IDs own deduplication."""
    if not isinstance(request, dict) or set(request) != {"id", "operation", "params"}:
        raise EngineeringError("invalid_product_request")
    checked_id(request["id"], "request_id")
    op, params = request["operation"], request["params"]
    if not isinstance(op, str) or not isinstance(params, dict):
        raise EngineeringError("invalid_product_request")
    # Callers cannot set time, trust, raw database rows or recovery decisions.
    fields = {
        "recover": (), "audit": (),
        "admit": ("envelope",), "register": ("receipt",),
        "lease": ("lease_id", "envelope_id", "holder", "paths", "authority_epoch", "expires_unix_ns"),
        "plan": ("envelope", "packages", "workers", "completion_receipts", "capacity", "generation_id"),
        "plan_state": ("generation_id",), "claim_state": ("claim_id",),
        "claim": ("generation_id", "package_id", "worker_id", "lease_id", "heartbeat_ttl_ns"),
        "heartbeat": ("receipt", "heartbeat_ttl_ns"), "result": ("receipt",),
        "completion": ("claim_id", "receipt"),
        "publish": ("generation_id", "queue_generation_id", "base_commit", "base_tree"),
        "context": ("queue_generation_id", "package_id"),
        "stage": ("queue_generation_id", "package_id", "current_base_commit", "current_base_tree", "receipt"),
        "terminal": ("queue_generation_id", "package_id", "current_base_commit", "current_base_tree", "receipt"),
    }
    if op not in fields or set(params) != set(fields[op]):
        raise EngineeringError("invalid_product_parameters")
    p = dict(params)
    if op in {"recover", "plan", "claim"}:
        report = product.startup_reconcile()
        if op == "recover":
            return asdict(report)
    if op == "audit":
        return product.audit_anchor()
    if op == "admit":
        return asdict(product.admit_repository_envelope(_record(WorkEnvelope, p["envelope"])))
    if op == "register":
        return {"registrationDigest": product.register_worker(_record(WorkerRegistrationReceipt, p["receipt"]))}
    if op == "lease":
        if not isinstance(p["paths"], list):
            raise EngineeringError("invalid_product_parameters")
        return asdict(product.acquire_lease(**p))
    if op == "plan":
        capacity = p.pop("capacity")
        if not isinstance(capacity, dict) or set(capacity) != {"ci_units", "review"}:
            raise EngineeringError("invalid_engineering_capacity")
        return asdict(product.plan_work(
            _record(WorkEnvelope, p["envelope"]),
            _records(EngineeringWorkPackage, p["packages"], 4096),
            _records(WorkerProfile, p["workers"], 256),
            _records(CompletionReceipt, p["completion_receipts"], 4096),
            EngineeringCapacity(capacity["ci_units"], _records(ReviewCapacity, capacity["review"], 16)),
            generation_id=p["generation_id"],
        ))
    if op == "plan_state":
        return asdict(product.plan_state(**p))
    if op == "claim_state":
        return asdict(product.claim_state(**p))
    if op == "claim":
        return asdict(product.claim(**p))
    if op == "heartbeat":
        return asdict(product.heartbeat(_record(WorkerHeartbeatReceipt, p["receipt"]), heartbeat_ttl_ns=p["heartbeat_ttl_ns"]))
    if op == "result":
        return asdict(product.submit_result(_record(WorkerResultReceipt, p["receipt"])))
    if op == "completion":
        return asdict(product.observe_external_completion(p["claim_id"], _record(CompletionReceipt, p["receipt"])))
    if op == "publish":
        plan = product.plan_state(p.pop("generation_id"))
        return asdict(product.publish_integration_queue(plan, **p))
    if op == "context":
        return integration_receipt_context(integration_context_binding(product.store, **p))
    receipt = p.pop("receipt")
    if op == "stage":
        return asdict(product.reconcile_integration(**p, stage_receipt=_record(IntegrationStageReceipt, receipt)))
    return asdict(product.reconcile_integration(**p, terminal_receipt=_record(IntegrationTerminalReceipt, receipt)))


def _reject_constant(_value):
    raise EngineeringError("nonfinite_product_input")


def _write_reply(fd, value):
    encoded = json.dumps(value, separators=(",", ":"), sort_keys=True).encode() + b"\n"
    if len(encoded) > MAX_INPUT_BYTES:
        raise EngineeringError("product_output_limit")
    deadline = time.monotonic() + 5.0
    with selectors.PollSelector() as selector:
        selector.register(fd, selectors.EVENT_WRITE)
        view = memoryview(encoded)
        while view:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not selector.select(remaining):
                raise EngineeringError("product_reply_timeout")
            try:
                count = os.write(fd, view)
            except BlockingIOError:
                continue
            if count <= 0:
                raise EngineeringError("product_reply_closed")
            view = view[count:]


def serve_product(args, *, input_fd=0, output_fd=1):
    """Run recovery during idle/partial input and stop on bounded channel failure."""
    if os.name != "posix":
        raise EngineeringError("product_service_posix_required")
    interval = args.scan_interval_seconds
    if not math.isfinite(interval) or not 0.01 <= interval <= 60:
        raise EngineeringError("invalid_recovery_scan_interval")
    if not 1 <= args.maximum_requests <= 1_000_000:
        raise EngineeringError("invalid_product_request_limit")
    verifier = load_verifier_factory(args.verifier_factory)
    prior_blocking = os.get_blocking(output_fd)
    os.set_blocking(output_fd, False)
    try:
        with EngineeringControlProduct(
            args.database, args.repository,
            expected_repository=args.repository_full_name, trust_store=verifier,
        ) as product, selectors.PollSelector() as selector:
            report = product.startup_reconcile()
            _write_reply(output_fd, {"ready": True, "schema": "hepta.engineering-control-pipe.v1", "recovery": asdict(report), "authorityGranted": False})
            selector.register(input_fd, selectors.EVENT_READ)
            buffer = bytearray()
            processed = 0
            next_scan = time.monotonic() + interval
            while processed < args.maximum_requests:
                if time.monotonic() >= next_scan:
                    product.startup_reconcile()
                    next_scan = time.monotonic() + interval
                if b"\n" not in buffer:
                    if not selector.select(max(0, next_scan - time.monotonic())):
                        continue
                    chunk = os.read(input_fd, min(65536, MAX_INPUT_BYTES + 1 - len(buffer)))
                    if not chunk:
                        if buffer:
                            raise EngineeringError("incomplete_product_frame")
                        return 0
                    buffer.extend(chunk)
                end = buffer.find(b"\n")
                if end < 0:
                    if len(buffer) >= MAX_INPUT_BYTES:
                        raise EngineeringError("input_byte_limit_exceeded")
                    continue
                raw = bytes(buffer[:end])
                del buffer[:end + 1]
                processed += 1
                request_id = None
                try:
                    request = json.loads(raw, object_pairs_hook=_unique_pairs, parse_constant=_reject_constant)
                    if isinstance(request, dict):
                        request_id = checked_id(request.get("id"), "request_id")
                    result = dispatch_product_request(product, request)
                    response = {"id": request_id, "result": result, "authorityGranted": False}
                except (EngineeringError, ValueError, TypeError, RecursionError) as error:
                    code = error.code if isinstance(error, EngineeringError) else "invalid_product_request"
                    response = {"id": request_id, "error": code, "authorityGranted": False}
                _write_reply(output_fd, response)
            return 0
    except sqlite3.Error:
        raise EngineeringError("product_store_failure") from None
    finally:
        os.set_blocking(output_fd, prior_blocking)
