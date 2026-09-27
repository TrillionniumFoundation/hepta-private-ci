"""Bounded HPTARQ/HPTARS data bridge over the existing pinned Laya predictor.

No model-produced code, addresses, capabilities, journal or task-success claim.
The native inference owner supplies authority, resource reservation and a durable
fence. It must supervise the process, persist the entire reply and revalidate
source/artifact currentness before consumption. This module cannot attest those
boundaries or turn a completed prediction into a computer action.
"""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
import hashlib
import math
import threading
import time
from typing import Any, Callable

from hepta_retrieval_wire import (MAX_INT, decode_reply, decode_request, encode_reply)
from laya_retrieval import (Agent, FORMAT, EnteredFailure, Rejected, RetrievalDriver,
                            digest, encoded, sha256)

CONVERSION = "hepta.laya.probability-ppm.largest-remainder.v1"


@dataclass(frozen=True)
class OwnerDeadline:
    """Conserved local deadline; capture before loading, never recreate per retry.

    Both clocks can shorten the horizon; neither may extend it. This is a local
    clock bound, not restart-persistent expiry proof or an authority token.
    """
    unix_ms: int
    monotonic_end: float
    monotonic_start: float
    wall_start: float
    wall_clock: Callable[[], float]
    monotonic_clock: Callable[[], float]

    @classmethod
    def start(cls, unix_ms: int, *, maximum_seconds: float = 60.0,
              wall_clock: Callable[[], float] = time.time,
              monotonic_clock: Callable[[], float] = time.monotonic) -> OwnerDeadline:
        if (type(unix_ms) is not int or not 1 <= unix_ms <= MAX_INT
                or type(maximum_seconds) not in (int, float)
                or not math.isfinite(maximum_seconds) or not 0 < maximum_seconds <= 300):
            raise Rejected("invalid deadline profile")
        mono, wall = monotonic_clock(), wall_clock()
        if any(type(value) not in (int, float) or not math.isfinite(value) for value in (mono, wall)):
            raise Rejected("invalid clock observation")
        duration = min(maximum_seconds, unix_ms / 1000 - wall)
        if duration <= 0:
            raise Rejected("expired before loading")
        return cls(unix_ms, mono + duration, mono, wall, wall_clock, monotonic_clock)

    def check(self, unix_ms: int) -> None:
        mono, wall = self.monotonic_clock(), self.wall_clock()
        if (type(unix_ms) is not int or unix_ms != self.unix_ms
                or any(type(value) not in (int, float) or not math.isfinite(value) for value in (mono, wall))
                or mono < self.monotonic_start or wall < self.wall_start
                or mono >= self.monotonic_end or wall * 1000 >= self.unix_ms):
            raise Rejected("expired, rebound or regressed clock")


def probability_ppm(values: list[float]) -> list[int]:
    """Normalize SDK-rounded predictions, preserving deterministic tie order.

    These are predictions, not the behavior propensity. The raw distribution and
    this conversion identity remain in the returned diagnostic observation.
    """
    if not 2 <= len(values) <= 9 or any(
            type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1
            for value in values) or abs(sum(values) - 1) > 0.002:
        raise Rejected("invalid prediction mass")
    exact = [Fraction(str(value)) for value in values]
    total = sum(exact)
    if total <= 0:
        raise Rejected("zero prediction mass")
    scaled = [value * 1_000_000 / total for value in exact]
    result = [value.numerator // value.denominator for value in scaled]
    remaining = 1_000_000 - sum(result)
    order = sorted(range(len(result)), key=lambda index: (-(scaled[index] - result[index]), index))
    for index in order[:remaining]:
        result[index] += 1
    return result


class _UsageAgent:
    """Observe the SDK's actual token-usage record without changing prediction."""
    def __init__(self, delegate: Agent):
        self.delegate = delegate
        self.tok = delegate.tok
        self.cfg = delegate.cfg
        self.usage: Any = None

    def predict(self, state: str, questions: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        self.usage = None
        before = digest([state, questions, kwargs])
        result = self.delegate.predict(state, questions, **kwargs)
        if digest([state, questions, kwargs]) != before:
            raise Rejected("predictor mutated the admitted model input")
        self.usage = result.get("usage")
        return result


@dataclass(frozen=True)
class BinaryPrediction:
    wire: bytes
    observation: dict[str, Any]


class BinaryRetrievalDriver:
    """Shared preloaded predictor; binary outputs still require owner settlement."""
    def __init__(self, agent: Agent, model_digest: str, max_len: int = 512, head_max_len: int = 192):
        self.model_digest = sha256(model_digest)
        self._usage_agent = _UsageAgent(agent)
        self._driver = RetrievalDriver(self._usage_agent, model_digest, max_len, head_max_len)
        self._max_len = max_len
        self._lock = threading.Lock()

    def predict(self, wire: bytes, deadline: OwnerDeadline) -> BinaryPrediction:
        request = decode_request(wire)
        deadline.check(request["deadline_ms"])
        if request["bundle_digest"] != self.model_digest or len(request["sources"]) > 8:
            raise Rejected("wrong model bundle or unsupported source count")
        # Source order remains bound in the original wire. HPTARS probabilities
        # are in canonical ASCII source order, not arrival or model JSON order.
        sources = sorted(request["sources"], key=lambda source: source["source_id"])
        request_hash = hashlib.sha256(wire).hexdigest()
        aliases = ["source-%03d" % index for index in range(len(sources))]
        model_request = {
            "format": FORMAT, "operation_id": "wire." + request_hash,
            "scope": "workspace." + hashlib.sha256(request["workspace_id"].encode()).hexdigest(),
            "objective_digest": request["objective_digest"], "snapshot_digest": request_hash,
            "query": request["query"],
            "candidates": [{"id": alias, "source_digest": source["content_sha256"],
                            "excerpt": source["text"]} for alias, source in zip(aliases, sources)],
        }
        if not self._lock.acquire(blocking=False):
            raise Rejected("binary worker capacity occupied")
        started = time.monotonic()
        returned = False
        try:
            observation = self._driver.predict(encoded(model_request), deadline.monotonic_end)
            returned = True
            deadline.check(request["deadline_ms"])
            usage = self._usage_agent.usage
            if (not isinstance(usage, dict) or type(usage.get("input_tokens")) is not int
                    or not 1 <= usage["input_tokens"] <= self._max_len
                    or type(usage.get("output_tokens")) is not int or usage["output_tokens"] != 0):
                raise Rejected("missing or incompatible observed SDK token usage")
            probability_order = ["abstain", *aliases]
            reply = encode_reply({
                "request_sha256": request_hash, "bundle_digest": self.model_digest,
                "prediction_ppm": probability_ppm([observation["prediction"][key] for key in probability_order]),
                "input_tokens": usage["input_tokens"], "output_tokens": usage["output_tokens"],
                "latency_us": math.ceil((time.monotonic() - started) * 1_000_000),
            })
            decode_reply(reply, wire)
            deadline.check(request["deadline_ms"])
            diagnostic = {
                "schema": "hepta.laya.binary-observation.v1", "request_sha256": request_hash,
                "reply_sha256": hashlib.sha256(reply).hexdigest(), "model_digest": self.model_digest,
                "operation_id": request["operation_id"], "workspace_id": request["workspace_id"],
                "generation": request["generation"], "observation_digest": request["observation_digest"],
                "candidate_order": [source["source_id"] for source in sources],
                "source_revisions": [source["revision"] for source in sources],
                "conversion": CONVERSION, "driver_receipt": observation,
                "observed_input_tokens": usage["input_tokens"], "authority": False,
                "source_currentness_verified": False, "task_success": None,
            }
            diagnostic["receipt_digest"] = digest(diagnostic)
            return BinaryPrediction(reply, diagnostic)
        except EnteredFailure:
            raise
        except Exception as error:
            if returned:
                raise EnteredFailure("model entered without an admissible binary reply",
                                     time.monotonic() - started) from error
            raise
        finally:
            self._lock.release()


def main() -> None:
    """One-shot experimental leaf. A supervising owner must bound pipe I/O."""
    import argparse
    import contextlib
    import json
    from pathlib import Path
    import sys
    from hepta_retrieval_wire import MAX_FRAME
    from laya_retrieval import load_pinned

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", required=True, type=Path)
    parser.add_argument("--pins", required=True, type=Path)
    args = parser.parse_args()
    wire = sys.stdin.buffer.read(MAX_FRAME + 1)
    request = decode_request(wire)
    deadline = OwnerDeadline.start(request["deadline_ms"])
    with args.pins.open("rb") as stream:
        raw_pins = stream.read(65_537)
    if len(raw_pins) > 65_536:
        raise Rejected("pin manifest byte bound")
    def unique_pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise Rejected("duplicate pin manifest key")
            result[key] = value
        return result
    pins = json.loads(raw_pins, object_pairs_hook=unique_pairs)
    if digest(pins) != request["bundle_digest"]:
        raise Rejected("wrong pinned bundle before load")
    # Model/library diagnostics cannot corrupt binary stdout. Loading consumes
    # the original deadline; no new sixty-second horizon starts after loading.
    with contextlib.redirect_stdout(sys.stderr):
        agent, identity = load_pinned(args.checkpoint, pins)
        deadline.check(request["deadline_ms"])
        result = BinaryRetrievalDriver(agent, identity).predict(wire, deadline)
    sys.stdout.buffer.write(result.wire)
    sys.stdout.buffer.flush()


if __name__ == "__main__":
    main()
