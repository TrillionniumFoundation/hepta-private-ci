"""Validate retained native Codex nonce events without calling a provider.

A nonce roundtrip is neither transport model identity, execution isolation, nor
teacher-data admission. Native JSONL is not Gateway agentMeta.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re

from teacher_connectivity import MAX_BYTES, NONCE, strict_json

MAX_EVENTS = 256
MODEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,159}\Z")
SAFE_ITEMS = frozenset(("agent_message", "reasoning"))
EVENT_FIELDS = {
    "thread.started": {"type", "thread_id"}, "turn.started": {"type"},
    "item.started": {"type", "item"}, "item.updated": {"type", "item"},
    "item.completed": {"type", "item"}, "turn.completed": {"type", "usage"},
}


def observe_native(*, events: bytes, final: bytes, diagnostics: bytes,
                   requested_model: str, nonce: str, exit_code: int | None) -> dict:
    """Accept one closed nonce-only turn; retain uncertainty and never retry.

    requested_model is caller context, not the transport-owned served identity.
    A completed turn plus local failure retains its observation but is not a
    successful connectivity receipt or evidence that remote work never happened.
    """
    if (not isinstance(requested_model, str) or not isinstance(nonce, str) or
            not MODEL.fullmatch(requested_model) or not NONCE.fullmatch(nonce)):
        raise ValueError("invalid requested model or nonce")
    if exit_code is not None and (type(exit_code) is not int or not -255 <= exit_code <= 255):
        raise ValueError("invalid observed local exit")
    if any(type(raw) is not bytes or len(raw) > MAX_BYTES for raw in (events, final, diagnostics)):
        raise ValueError("native observation exceeds bound")
    lines = events.splitlines()
    if len(lines) > MAX_EVENTS:
        raise ValueError("native event count exceeds bound")
    report = {
        "schema": "hepta.native-codex-nonce-observation.v1",
        "requested_model": requested_model, "exit_code": exit_code,
        "events_sha256": hashlib.sha256(events).hexdigest(),
        "final_sha256": hashlib.sha256(final).hexdigest(),
        "diagnostics_sha256": hashlib.sha256(diagnostics).hexdigest(),
        "nonce_sha256": hashlib.sha256(nonce.encode()).hexdigest(),
        "thread_id": None, "event_count": len(lines), "turn_completed": False,
        "nonce_matched": False, "connectivity_verified": False,
        "status": "native_observation_incomplete", "observed_item_types": [],
        "transport_observed_provider": None, "transport_observed_model": None,
        "tool_isolation_verified": False, "provider_qualified": False,
        "training_rights_verified": False, "training_data_admitted": False,
        "production_activation": False, "operator_acceptance": False,
        "retry_authorized": False, "remote_nonexecution_proven": False,
    }
    phase, items, messages, kinds, problem = "before_thread", {}, [], set(), None
    for raw in lines:
        event = strict_json(raw)
        if not isinstance(event, dict) or not isinstance(event.get("type"), str):
            raise ValueError("invalid native event object")
        kind = event["type"]
        if kind in EVENT_FIELDS and set(event) != EVENT_FIELDS[kind]:
            problem = "native_event_shape_unsupported"
            break
        if phase == "terminal":
            problem = "native_event_after_terminal"
            break
        if kind == "thread.started":
            if phase != "before_thread":
                problem = "native_thread_sequence_invalid"
                break
            identity = event.get("thread_id")
            if not isinstance(identity, str) or not NONCE.fullmatch(identity):
                raise ValueError("invalid native thread identity")
            report["thread_id"], phase = identity, "before_turn"
        elif kind == "turn.started":
            if phase != "before_turn":
                problem = "native_turn_sequence_invalid"
                break
            phase = "in_turn"
        elif kind in ("item.started", "item.updated", "item.completed"):
            if phase != "in_turn":
                problem = "native_item_outside_turn"
                break
            item = event.get("item")
            if not isinstance(item, dict):
                raise ValueError("invalid native item")
            identity, item_type = item.get("id"), item.get("type")
            if not isinstance(identity, str) or not NONCE.fullmatch(identity):
                raise ValueError("invalid native item identity")
            if not isinstance(item_type, str) or not NONCE.fullmatch(item_type):
                raise ValueError("invalid native item type")
            kinds.add(item_type)
            if item_type not in SAFE_ITEMS:
                problem = "native_non_nonce_activity_observed"
                break
            if set(item) - {"id", "type", "text"}:
                problem = "native_item_shape_unsupported"
                break
            previous = items.get(identity)
            if (previous is not None and (previous[0] != item_type or previous[1] == "item.completed")) or (
                    kind == "item.started" and previous is not None):
                problem = "native_item_sequence_invalid"
                break
            if kind == "item.updated" and previous is None:
                problem = "native_item_sequence_invalid"
                break
            items[identity] = (item_type, kind)
            if kind == "item.completed" and item_type == "agent_message":
                if not isinstance(item.get("text"), str):
                    raise ValueError("invalid native message")
                messages.append(item["text"])
        elif kind == "turn.completed":
            if phase != "in_turn" or any(state != "item.completed" for _, state in items.values()):
                problem = "native_turn_sequence_invalid"
                break
            usage = event.get("usage")
            if not isinstance(usage, dict) or any(
                    type(usage.get(key)) is not int or not 0 <= usage[key] <= 1_000_000_000
                    for key in ("input_tokens", "cached_input_tokens", "output_tokens")):
                raise ValueError("invalid native usage counters")
            if usage["cached_input_tokens"] > usage["input_tokens"]:
                raise ValueError("invalid native cached token count")
            report["turn_completed"], phase = True, "terminal"
        elif kind in ("turn.failed", "error"):
            problem = "native_error_reconcile_before_retry"
            break
        else:
            problem = "native_event_not_supported"
            break
    report["observed_item_types"] = sorted(kinds)
    if problem is not None:
        report["status"] = problem
    elif phase != "terminal":
        report["status"] = "native_observation_incomplete"
    elif messages != [nonce] or final not in (nonce.encode(), nonce.encode() + b"\n"):
        report["status"] = "native_nonce_binding_mismatch"
    else:
        report["nonce_matched"] = True
        if exit_code != 0:
            report["status"] = "native_local_exit_not_success"
        else:
            report.update(status="native_connected_identity_unobserved", connectivity_verified=True)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("events", "final", "diagnostics", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--requested-model", required=True)
    parser.add_argument("--nonce", required=True)
    parser.add_argument("--exit-code", type=int)
    args = parser.parse_args()
    def read(path):
        with path.open("rb") as stream:
            return stream.read(MAX_BYTES + 1)
    report = observe_native(events=read(args.events), final=read(args.final),
                            diagnostics=read(args.diagnostics), requested_model=args.requested_model,
                            nonce=args.nonce, exit_code=args.exit_code)
    report["validator_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    report["json_validator_sha256"] = hashlib.sha256(Path(__file__).with_name("teacher_connectivity.py").read_bytes()).hexdigest()
    data = json.dumps(report, sort_keys=True, indent=2, allow_nan=False).encode() + b"\n"
    descriptor = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    print(json.dumps({"status": report["status"], "output": str(args.output),
                      "sha256": hashlib.sha256(data).hexdigest()}, sort_keys=True))
    return 0 if report["connectivity_verified"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
