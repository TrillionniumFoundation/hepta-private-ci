"""Pinned persistent JSON-lines resolver for the real daemon memory read path.

Stdout contains exactly one bounded decision per request. Startup and process
errors use stderr. A framing overflow terminates the worker without attempting
to reinterpret the remaining bytes as another authorized request.
"""

import argparse
import json
from pathlib import Path
import sys
import time

PROJECT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT.parent))
sys.path.insert(0, str(PROJECT.parents[1] / "memory-cell-v6"))

from addressing.contracts import canonical
from addressing.model import IntentModel, policy_digest
from addressing.planner import AddressPlanner
from v6.encoder import MiniLMEncoder


MAX_FRAME_BYTES = 2_097_152
MAX_RESPONSE_BYTES = 32_768


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON field")
        result[key] = value
    return result


def reject_constant(value):
    raise ValueError("nonfinite JSON number")


def empty_decision(model, reason):
    return {
        "schema": "hepta.memory.v7.address-decision.v1",
        "query_id": None,
        "request_digest": None,
        "status": "rejected",
        "reason": reason,
        "request": None,
        "plan": None,
        "model_digest": model.identity,
        "registry_digest": None,
        "source_cut": None,
        "decision": None,
        "authority": False,
    }


def serve(model, incoming, outgoing, errors):
    while True:
        raw = incoming.readline(MAX_FRAME_BYTES + 1)
        if not raw:
            return 0
        if len(raw) > MAX_FRAME_BYTES or not raw.endswith(b"\n"):
            outgoing.write(
                canonical(
                    empty_decision(model, "worker-frame-exceeds-bound-or-is-incomplete")
                )
                + b"\n"
            )
            outgoing.flush()
            return 2
        started, cpu = time.perf_counter(), time.process_time()
        try:
            frame = json.loads(
                raw, object_pairs_hook=unique_object, parse_constant=reject_constant
            )
            if (
                not isinstance(frame, dict)
                or set(frame) != {"schema", "request", "registry"}
                or frame["schema"] != "hepta.memory.v7.address-worker-request.v1"
            ):
                raise ValueError("invalid worker frame schema")
            result = AddressPlanner(model, frame["registry"]).plan(frame["request"])
        except (ValueError, TypeError, UnicodeDecodeError, RecursionError) as error:
            result = empty_decision(
                model, "invalid-worker-input:" + type(error).__name__
            )
        except Exception as error:
            errors.write(
                "memory-address-worker inference failure: "
                + type(error).__name__
                + "\n"
            )
            errors.flush()
            result = empty_decision(model, "resolver-unavailable")
            result["status"] = "unavailable"
        result["cost"] = {
            "request_body_bytes": len(raw) - 1,
            "processing_wall_seconds": time.perf_counter() - started,
            "processing_cpu_seconds": time.process_time() - cpu,
        }
        response = canonical(result)
        if len(response) > MAX_RESPONSE_BYTES:
            response = canonical(empty_decision(model, "worker-response-exceeds-bound"))
        outgoing.write(response + b"\n")
        outgoing.flush()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--model-digest", required=True)
    parser.add_argument("--encoder", type=Path, required=True)
    args = parser.parse_args()
    try:
        model = IntentModel.load(
            args.model, MiniLMEncoder(args.encoder), args.model_digest
        )
        if not model.calibration:
            raise ValueError("uncalibrated worker model")
        print(
            json.dumps(
                {
                    "schema": "hepta.memory.v7.address-worker-ready.v1",
                    "model_digest": model.identity,
                    "policy_digest": policy_digest(),
                    "max_frame_bytes": MAX_FRAME_BYTES,
                    "max_response_bytes": MAX_RESPONSE_BYTES,
                }
            ),
            file=sys.stderr,
            flush=True,
        )
        raise SystemExit(serve(model, sys.stdin.buffer, sys.stdout.buffer, sys.stderr))
    except (OSError, ValueError, KeyError) as error:
        print(
            "memory-address-worker startup rejected: " + type(error).__name__,
            file=sys.stderr,
            flush=True,
        )
        raise SystemExit(2) from error
