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


class DeadlineGuard:
    """One process-local budget, starting before model loading.

    Wall time controls absolute expiry; monotonic time prevents a frozen or
    adjusted wall clock from granting extra execution time. Clock regression
    fails closed. This cannot interrupt a stuck model: the launching owner
    must still enforce process cancellation and classify an unknown result.
    The guard is not persisted and cannot certify time across a reboot.
    """

    def __init__(self, deadline_ms: int, *, now_ms: Callable[[], int],
                 monotonic_ns: Callable[[], int] = time.monotonic_ns):
        if type(deadline_ms) is not int or not 1 <= deadline_ms <= MAX_INT:
            raise WireError("invalid absolute deadline")
        self.deadline_ms = deadline_ms
        self._wall = now_ms
        self._monotonic = monotonic_ns
        self._failed = False
        self._start = self._read(self._monotonic)
        self._last_monotonic = self._start
        self._last_wall = self._read(self._wall)
        self._budget_ns = (deadline_ms - self._last_wall) * 1_000_000
        if self._budget_ns <= 0:
            self._failed = True
            raise WireError("expired request; reconcile any consumed inference cost")

    @staticmethod
    def _read(clock: Callable[[], int]) -> int:
        value = clock()
        if type(value) is not int or not 0 <= value <= MAX_INT:
            raise WireError("invalid clock observation")
        return value

    def check(self) -> None:
        if self._failed:
            raise WireError("deadline guard unavailable after clock or expiry failure")
        try:
            wall = self._read(self._wall)
            monotonic = self._read(self._monotonic)
            if wall < self._last_wall or monotonic < self._last_monotonic:
                raise WireError("clock regressed; reconcile any consumed inference cost")
            if (wall >= self.deadline_ms
                    or monotonic - self._start >= self._budget_ns):
                raise WireError("expired request; reconcile any consumed inference cost")
            self._last_wall = wall
            self._last_monotonic = monotonic
        except BaseException:
            self._failed = True
            raise


def score_frame(frame: bytes, scorer: Callable[[dict[str, Any]], dict[str, Any]],
                *, now_ms: Callable[[], int],
                monotonic_ns: Callable[[], int] = time.monotonic_ns,
                deadline: DeadlineGuard | None = None) -> bytes:
    """Invoke one scorer once; bind its output and reject expired/mutated work.

    The injectable scorer is a local testing/integration seam, not a model hook
    that can grant authority. Exceptions and lost responses never cause retries.
    main passes the guard started before loading rather than resetting its budget.
    """
    request = decode_request(frame)
    guard = deadline if deadline is not None else DeadlineGuard(
        request["deadline_ms"], now_ms=now_ms, monotonic_ns=monotonic_ns)
    if guard.deadline_ms != request["deadline_ms"]:
        raise WireError("deadline belongs to another request")
    guard.check()
    request_digest = hashlib.sha256(_canonical(request)).hexdigest()
    result = scorer(request)
    if encode_request(request) != frame:
        raise WireError("scorer changed the bound input")
    guard.check()
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
        reply = encode_reply({
            "request_sha256": hashlib.sha256(frame).hexdigest(),
            "bundle_digest": request["bundle_digest"],
            "prediction_ppm": probabilities,
            "input_tokens": result["input_tokens"],
            "output_tokens": result["output_tokens"],
            "latency_us": result["latency_us"],
        })
    except (KeyError, TypeError) as error:
        raise WireError("incomplete scoring result") from error
    guard.check()
    return reply


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-root", type=Path, required=True)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--bundle-digest", required=True)
    args = parser.parse_args()
    frame = sys.stdin.buffer.read(MAX_FRAME + 1)
    request = decode_request(frame)
    now = lambda: time.time_ns() // 1000000
    deadline = DeadlineGuard(request["deadline_ms"], now_ms=now)
    if request["bundle_digest"] != args.bundle_digest:
        raise WireError("wrong selected bundle")
    with args.bundle.open("rb") as stream:
        pin_bytes = stream.read(MAX_FRAME + 1)
    if len(pin_bytes) > MAX_FRAME:
        raise WireError("bundle manifest exceeds byte budget")
    deadline.check()
    try:
        from .hepta_laya_retrieval import PinnedLaya, Request, Source, score, strict_json
    except ImportError:
        from hepta_laya_retrieval import PinnedLaya, Request, Source, score, strict_json
    with redirect_stdout(sys.stderr):
        deadline.check()
        port = PinnedLaya(args.model_root, strict_json(pin_bytes), args.bundle_digest)
        deadline.check()
        def scorer(value):
            typed = Request(**{key: item for key, item in value.items() if key != "sources"},
                            sources=tuple(Source(**source) for source in value["sources"]))
            # This leaf sees immutable supplied bytes, not live source authority.
            # The embedding native owner must revalidate actual currentness.
            return score(typed, port, now_ms=now, current=lambda _: True)
        reply = score_frame(frame, scorer, now_ms=now, deadline=deadline)
    deadline.check()
    sys.stdout.buffer.write(reply)
    sys.stdout.buffer.flush()


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        reason = str(error) if isinstance(error, WireError) else "model or I/O failure"
        print(f"Laya worker unavailable: {type(error).__name__}: {reason}", file=sys.stderr)
        raise SystemExit(2) from error
