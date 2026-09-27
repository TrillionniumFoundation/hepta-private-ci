#!/usr/bin/env python3
"""One-shot offline Laya scoring leaf with a bounded binary data interface.

A host must provide an immutable pinned model directory, a bounded/terminated
stdin stream, process isolation and an execution deadline. The native inference
owner still owns admission, durable result storage, cancellation, reconciliation
and source/artifact currentness at final use. This is not a daemon, scheduler,
authority service, source observer or automatic recovery loop.
"""
from __future__ import annotations

import argparse
from contextlib import redirect_stdout
import hashlib
import json
from pathlib import Path
import sys
import time
from typing import Any, Callable

try:
    from .hepta_retrieval_wire import (
        MAX_FRAME, MAX_INT, WireError, decode_request, encode_reply, encode_request,
    )
except ImportError:
    from hepta_retrieval_wire import (
        MAX_FRAME, MAX_INT, WireError, decode_request, encode_reply, encode_request,
    )


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def score_frame(frame: bytes, scorer: Callable[[dict[str, Any]], dict[str, Any]],
                *, now_ms: Callable[[], int]) -> bytes:
    """Invoke one scorer once; bind its output and reject expired/mutated work.

    The injectable scorer is a local testing/integration seam, not a model hook
    that can grant authority. Exceptions and lost responses never cause retries.
    """
    request = decode_request(frame)
    def check_time() -> None:
        observed = now_ms()
        if type(observed) is not int or not 0 <= observed <= MAX_INT:
            raise WireError("invalid clock observation")
        if observed >= request["deadline_ms"]:
            raise WireError("request expired; reconcile any consumed inference cost")
    check_time()
    # Capture before calling untrusted computation; labels/outcomes never enter
    # these inputs. Re-encoding detects nested source mutation as well.
    request_digest = hashlib.sha256(_canonical(request)).hexdigest()
    result = scorer(request)
    if encode_request(request) != frame:
        raise WireError("scorer changed the bound input")
    check_time()
    if not isinstance(result, dict):
        raise WireError("missing scoring result")
    expected = {
        "schema": "hepta.laya.retrieval.v1",
        "operation_id": request["operation_id"],
        "workspace_id": request["workspace_id"],
        "generation": request["generation"],
        "bundle_digest": request["bundle_digest"],
        "observation_digest": request["observation_digest"],
        "request_digest": request_digest,
    }
    if any(type(result.get(key)) is not type(value) or result[key] != value
           for key, value in expected.items()):
        raise WireError("scoring result scope differs from the admitted request")
    if result.get("production_authority") is not False:
        raise WireError("scoring result cannot grant authority")
    labels = (None, *sorted(source["source_id"] for source in request["sources"]))
    if not isinstance(result.get("labels"), (tuple, list)) or tuple(result["labels"]) != labels:
        raise WireError("scoring result changed the complete candidate order")
    expected_result = hashlib.sha256(_canonical({
        key: value for key, value in result.items() if key != "result_digest"
    })).hexdigest()
    if result.get("result_digest") != expected_result:
        raise WireError("scoring result digest mismatch")
    try:
        probabilities = result["prediction_ppm"]
        if len(probabilities) != len(labels):
            raise WireError("scoring result shape mismatch")
        return encode_reply({
            "request_sha256": hashlib.sha256(frame).hexdigest(),
            "bundle_digest": request["bundle_digest"],
            "prediction_ppm": probabilities,
            "input_tokens": result["input_tokens"],
            "output_tokens": result["output_tokens"],
            "latency_us": result["latency_us"],
        })
    except (KeyError, TypeError) as error:
        raise WireError("incomplete scoring result") from error


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-root", type=Path, required=True)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--bundle-digest", required=True)
    args = parser.parse_args()
    # Reject malformed requests before importing a model runtime or loading any
    # weight. The launching host must close stdin and enforce its own I/O budget.
    frame = sys.stdin.buffer.read(MAX_FRAME + 1)
    request = decode_request(frame)
    now = lambda: time.time_ns() // 1000000
    if now() >= request["deadline_ms"] or request["bundle_digest"] != args.bundle_digest:
        raise WireError("expired request or wrong selected bundle")
    with args.bundle.open("rb") as stream:
        pin_bytes = stream.read(MAX_FRAME + 1)
    if len(pin_bytes) > MAX_FRAME:
        raise WireError("bundle manifest exceeds byte budget")
    # Only this explicit entry point imports the optional model dependency.
    try:
        from .hepta_laya_retrieval import PinnedLaya, Request, Source, score, strict_json
    except ImportError:
        from hepta_laya_retrieval import PinnedLaya, Request, Source, score, strict_json
    with redirect_stdout(sys.stderr):
        port = PinnedLaya(args.model_root, strict_json(pin_bytes), args.bundle_digest)
        def scorer(value):
            typed = Request(**{key: item for key, item in value.items() if key != "sources"},
                            sources=tuple(Source(**source) for source in value["sources"]))
            # This leaf sees immutable supplied bytes, not live source authority.
            # The embedding native owner must revalidate actual currentness.
            return score(typed, port, now_ms=now, current=lambda _: True)
        reply = score_frame(frame, scorer, now_ms=now)
    sys.stdout.buffer.write(reply)
    sys.stdout.buffer.flush()


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        # No binary success frame follows any parsing/model/IO error. This is
        # a single process boundary; the host retains unknown execution state.
        reason = str(error) if isinstance(error, WireError) else "model or I/O failure"
        print(f"Laya worker unavailable: {type(error).__name__}: {reason}", file=sys.stderr)
        raise SystemExit(2) from error
