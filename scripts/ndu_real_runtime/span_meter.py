"""Replayable v2 observation; it does not authenticate a native owner or admit work.

Clocks are sampled in one emitting thread of one process. Process CPU includes
that process's other threads, excludes child processes, and is never wall time.
Nested spans allocate exclusive intervals. Uninstrumented time stays UNKNOWN.
An immutable JSONL sink can retain each event before work begins; its durability
and the process/host identity still require the existing native owner contract.
"""

from contextlib import contextmanager
import copy
import hashlib
import json
import math
import os
import subprocess
import sys
import threading
import time
import uuid

SCHEMA = "ndu.real.span-meter.v2"
CATEGORIES = ("encoder", "shared", "decoder", "critic", "planning", "codec", "failure", "retry", "sync")
STATUSES = {"SUCCEEDED", "FAILED", "CANCELED", "BUDGET_STOP", "UNKNOWN"}
CPU_SCOPE = "emitting_process_all_threads_excluding_children"
_PROCESS_INSTANCE = (os.getpid(), uuid.uuid4().hex)


class MeterError(ValueError):
    """A malformed or incomplete observation must not become complete costs."""


def canonical_bytes(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def record_sha256(value):
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _require(condition, code):
    if not condition:
        raise MeterError(code)


def _identity(value):
    return isinstance(value, str) and 0 < len(value) <= 256 and not any(ord(c) < 32 for c in value)


class _Scope:
    def __init__(self, span_id):
        self.span_id, self.status, self.error_type = span_id, "SUCCEEDED", None

    def set_status(self, status):
        _require(isinstance(status, str) and status in STATUSES, "INVALID_STATUS")
        self.status = status


class SpanMeter:
    """One append-only process-local event stream, with an optional bytes sink.

    The sink first receives ``{"header": ...}\n``, then ``{"event": ...}\n``.
    A sink exception poisons this meter; never continue work after that exception.
    ``snapshot`` observes an open prefix; ``finish`` never closes open children.
    """

    def __init__(self, operation_id, *, event_sink=None):
        global _PROCESS_INSTANCE
        _require(_identity(operation_id), "INVALID_OPERATION_ID")
        if _PROCESS_INSTANCE[0] != os.getpid():
            _PROCESS_INSTANCE = (os.getpid(), uuid.uuid4().hex)
        self._header = {
            "schema": SCHEMA, "operation_id": operation_id, "meter_id": uuid.uuid4().hex,
            "process_id": os.getpid(), "process_instance_id": _PROCESS_INSTANCE[1],
            "thread_id": threading.get_ident(), "wall_clock": "time.monotonic_ns",
            "cpu_clock": "time.process_time_ns", "cpu_scope": CPU_SCOPE,
        }
        self._events, self._stack, self._nodes, self._errors = [], [], {}, []
        self._sink, self._closed = event_sink, False
        self._publish({"header": self._header})
        self._open("envelope", "envelope", None, None)

    def _publish(self, value):
        if self._sink is not None:
            try:
                self._sink(canonical_bytes(value) + b"\n")
            except BaseException:
                self._errors.append("EVENT_SINK_FAILED")
                raise

    def _emit(self, kind, **fields):
        _require(not self._closed and not self._errors, "CLOSED_OR_POISONED_METER")
        _require((os.getpid(), threading.get_ident()) ==
                 (self._header["process_id"], self._header["thread_id"]), "FOREIGN_PROCESS_OR_THREAD")
        event = {"seq": len(self._events), "kind": kind, "monotonic_ns": time.monotonic_ns(),
                 "process_time_ns": time.process_time_ns(), "process_id": os.getpid(),
                 "thread_id": threading.get_ident(), "previous_sha256":
                 self._events[-1]["sha256"] if self._events else record_sha256(self._header), **fields}
        event["sha256"] = record_sha256(event)
        previous = self._events[-1] if self._events else None
        self._events.append(event)
        self._publish({"event": event})
        if previous and any(event[k] < previous[k] for k in ("monotonic_ns", "process_time_ns")):
            self._errors.append("CLOCK_REGRESSION")
            raise MeterError("CLOCK_REGRESSION")

    def _open(self, node_kind, span_id, category, retry_of):
        _require(_identity(span_id) and span_id not in self._nodes, "DUPLICATE_OR_INVALID_SPAN")
        parent = self._nodes[self._stack[-1]] if self._stack else None
        attempt_id = span_id[len("attempt:"):] if node_kind == "attempt" else (
            parent["attempt_id"] if parent else None)
        _require(node_kind != "attempt" or self._stack == ["envelope"], "ATTEMPT_OVERLAP")
        _require(node_kind != "span" or category in CATEGORIES, "INVALID_CATEGORY")
        if retry_of is not None:
            previous = self._nodes.get("attempt:" + retry_of, {})
            _require(node_kind == "attempt" and previous.get("status") in
                     {"FAILED", "CANCELED", "BUDGET_STOP"}, "UNBOUND_OR_UNRESOLVED_RETRY")
        fields = {"span_id": span_id, "node_kind": node_kind,
                  "parent_id": self._stack[-1] if self._stack else None,
                  "attempt_id": attempt_id, "category": category, "retry_of": retry_of}
        self._emit("open", **fields)
        self._nodes[span_id] = fields
        self._stack.append(span_id)

    def _close(self, span_id, status, error_type=None):
        _require(bool(self._stack) and self._stack[-1] == span_id, "NON_LIFO_CLOSE")
        _require(isinstance(status, str) and status in STATUSES, "INVALID_STATUS")
        self._emit("close", span_id=span_id, status=status, error_type=error_type)
        self._nodes[span_id]["status"] = status
        self._stack.pop()

    @contextmanager
    def _scope(self, kind, span_id, category, retry_of):
        self._open(kind, span_id, category, retry_of)
        scope = _Scope(span_id)
        try:
            yield scope
        except BaseException as error:
            scope.status = "CANCELED" if isinstance(error, (KeyboardInterrupt, SystemExit)) else "FAILED"
            scope.error_type = type(error).__name__
            raise
        finally:
            if not self._errors:
                self._close(span_id, scope.status, scope.error_type)

    def attempt(self, attempt_id, *, retry_of=None):
        _require(_identity(attempt_id) and (retry_of is None or _identity(retry_of)), "INVALID_ATTEMPT_ID")
        return self._scope("attempt", "attempt:" + attempt_id, None, retry_of)

    def span(self, span_id, category):
        return self._scope("span", span_id, category, None)

    def snapshot(self):
        if not self._closed and not self._errors:
            self._emit("checkpoint")
        return {"header": copy.deepcopy(self._header), "events": copy.deepcopy(self._events),
                "capture_errors": list(self._errors)}

    def finish(self, status="SUCCEEDED"):
        _require(self._stack == ["envelope"], "UNCLOSED_CHILD_SPANS")
        self._close("envelope", status)
        self._closed = True
        return self.snapshot()


def record_from_jsonl(raw):
    """Read a retained complete-line prefix; refuse truncated/ambiguous JSON bytes."""
    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            _require(key not in result, "DUPLICATE_JSON_KEY")
            result[key] = value
        return result

    _require(isinstance(raw, bytes) and raw.endswith(b"\n"), "TRUNCATED_JOURNAL_LINE")
    rows = [json.loads(line, object_pairs_hook=unique_object) for line in raw.splitlines()]
    _require(bool(rows) and isinstance(rows[0], dict) and set(rows[0]) == {"header"}, "MISSING_JOURNAL_HEADER")
    _require(all(isinstance(row, dict) and set(row) == {"event"} for row in rows[1:]), "INVALID_JOURNAL_ROW")
    return {"header": rows[0]["header"], "events": [row["event"] for row in rows[1:]], "capture_errors": []}


def verify_record(record, *, expected_sha256=None):
    """Replay raw events; an external digest pin is integrity, not native authority."""
    result = {"schema": "ndu.real.span-replay.v2", "valid": False, "diagnostics": [],
              "native_owner_authentication": "SEPARATE_REQUIRED", "full_physical_cost_complete": False,
              "energy_joules": None, "provider_charges": None}
    try:
        result["record_sha256"] = record_sha256(record)
        _require(expected_sha256 is None or result["record_sha256"] == expected_sha256, "EXTERNAL_DIGEST_MISMATCH")
        _require(isinstance(record, dict) and set(record) == {"header", "events", "capture_errors"}, "INVALID_RECORD_SHAPE")
        _require(record["capture_errors"] == [], "CAPTURE_ERROR")
        header, events = record["header"], record["events"]
        _require(isinstance(header, dict) and set(header) == {"schema", "operation_id", "meter_id", "process_id",
                 "process_instance_id", "thread_id", "wall_clock", "cpu_clock", "cpu_scope"}, "INVALID_HEADER")
        _require(header["schema"] == SCHEMA and header["wall_clock"] == "time.monotonic_ns"
                 and header["cpu_clock"] == "time.process_time_ns" and header["cpu_scope"] == CPU_SCOPE, "UNSUPPORTED_CLOCK_SCOPE")
        _require(all(_identity(header[k]) for k in ("operation_id", "meter_id", "process_instance_id"))
                 and all(type(header[k]) is int and header[k] > 0 for k in ("process_id", "thread_id")), "INVALID_PROCESS_IDENTITY")
        _require(isinstance(events, list) and 0 < len(events) <= 65536, "INVALID_EVENT_COUNT")
        nodes, stack, previous = {}, [], None
        common = {"seq", "kind", "monotonic_ns", "process_time_ns", "process_id", "thread_id", "previous_sha256", "sha256"}
        for index, event in enumerate(events):
            _require(isinstance(event, dict), "INVALID_EVENT")
            fields = {k: v for k, v in event.items() if k != "sha256"}
            _require(event.get("sha256") == record_sha256(fields) and event.get("previous_sha256") ==
                     (previous["sha256"] if previous else record_sha256(header)), "BROKEN_EVENT_CHAIN")
            _require(type(event.get("seq")) is int and event["seq"] == index, "EVENT_SEQUENCE_MISMATCH")
            _require(all(type(event.get(k)) is int and event[k] >= 0 for k in ("monotonic_ns", "process_time_ns")), "INVALID_CLOCK_SAMPLE")
            _require(all(type(event.get(k)) is int and event[k] == header[k]
                         for k in ("process_id", "thread_id")), "FOREIGN_PROCESS_OR_THREAD")
            if previous:
                _require(bool(stack), "EVENT_AFTER_ENVELOPE_CLOSE")
                _require(all(event[k] >= previous[k] for k in ("monotonic_ns", "process_time_ns")), "CLOCK_REGRESSION")
            kind = event.get("kind")
            if kind == "open":
                _require(set(event) == common | {"span_id", "node_kind", "parent_id", "attempt_id", "category", "retry_of"}, "INVALID_OPEN_FIELDS")
                name, node_kind = event["span_id"], event["node_kind"]
                _require(_identity(name) and name not in nodes, "DUPLICATE_OR_INVALID_SPAN")
                _require(event["parent_id"] == (stack[-1] if stack else None), "PARENT_OR_OVERLAP_MISMATCH")
                if index == 0:
                    _require(name == "envelope" and node_kind == "envelope" and
                             all(event[k] is None for k in ("attempt_id", "category", "retry_of")), "INVALID_ENVELOPE")
                elif node_kind == "attempt":
                    _require(stack == ["envelope"] and _identity(event["attempt_id"]) and
                             name == "attempt:" + event["attempt_id"] and event["category"] is None, "ATTEMPT_OVERLAP_OR_ID")
                    if event["retry_of"] is not None:
                        _require(_identity(event["retry_of"]), "INVALID_RETRY_ID")
                        predecessor = nodes.get("attempt:" + event["retry_of"], {})
                        _require(predecessor.get("status") in {"FAILED", "CANCELED", "BUDGET_STOP"}, "UNBOUND_OR_UNRESOLVED_RETRY")
                else:
                    _require(node_kind == "span" and event["category"] in CATEGORIES and event["retry_of"] is None
                             and event["attempt_id"] == nodes[stack[-1]]["attempt_id"], "INVALID_SPAN_CONTEXT")
                nodes[name] = {**{k: event[k] for k in ("span_id", "node_kind", "parent_id", "attempt_id", "category", "retry_of")},
                               "start_monotonic_ns": event["monotonic_ns"], "start_process_time_ns": event["process_time_ns"],
                               "end_monotonic_ns": None, "end_process_time_ns": None, "status": "UNKNOWN", "error_type": None, "children": []}
                if stack:
                    nodes[stack[-1]]["children"].append(name)
                stack.append(name)
            elif kind == "close":
                _require(set(event) == common | {"span_id", "status", "error_type"} and bool(stack) and
                         event["span_id"] == stack[-1], "NON_LIFO_CLOSE")
                _require(isinstance(event["status"], str) and event["status"] in STATUSES, "INVALID_STATUS")
                _require(event["error_type"] is None or _identity(event["error_type"]), "INVALID_ERROR_TYPE")
                nodes[stack.pop()].update(end_monotonic_ns=event["monotonic_ns"],
                                         end_process_time_ns=event["process_time_ns"], status=event["status"], error_type=event["error_type"])
            else:
                _require(kind == "checkpoint" and set(event) == common and bool(stack), "INVALID_CHECKPOINT_OR_KIND")
            previous = event
        _require("envelope" in nodes, "MISSING_ENVELOPE")
        categories = {k: {"exclusive_wall_ns": 0, "exclusive_process_cpu_ns": 0, "span_count": 0} for k in CATEGORIES}
        unknown = {"status": "UNKNOWN", "wall_ns": 0, "process_cpu_ns": 0}
        for node in reversed(list(nodes.values())):
            for clock, clock_field, short in (("monotonic", "monotonic_ns", "wall"), ("process_time", "process_time_ns", "process_cpu")):
                end = node["end_" + clock + "_ns"]
                duration = (previous[clock_field] if end is None else end) - node["start_" + clock + "_ns"]
                exclusive = duration - sum(nodes[c]["inclusive_" + short + "_ns"] for c in node["children"])
                _require(exclusive >= 0, "NEGATIVE_EXCLUSIVE_DURATION")
                node["inclusive_" + short + "_ns"], node["exclusive_" + short + "_ns"] = duration, exclusive
                if node["category"] is None:
                    unknown["wall_ns" if short == "wall" else "process_cpu_ns"] += exclusive
                else:
                    categories[node["category"]]["exclusive_" + short + "_ns"] += exclusive
            if node["category"] is not None:
                categories[node["category"]]["span_count"] += 1
            node["observed_prefix_only"] = node["end_monotonic_ns"] is None
        envelope = nodes["envelope"]
        result.update(valid=True, header=copy.deepcopy(header), complete_record=not stack,
                      observed_through_monotonic_ns=previous["monotonic_ns"],
                      unobserved_tail=bool(stack), envelope=envelope, spans=list(nodes.values()),
                      attempts=[n for n in nodes.values() if n["node_kind"] == "attempt"],
                      categories=categories, uninstrumented=unknown,
                      cpu_scope=CPU_SCOPE, child_process_cpu_ns=None)
    except (MeterError, KeyError, TypeError, ValueError, IndexError, OverflowError, RecursionError) as error:
        result["diagnostics"].append({"code": str(error), "event_index": locals().get("index")})
    return result


def run_subprocess_probe(*, timeout_seconds=3.0):
    """Bounded real stdlib diagnostic; no task model, research fit, or adoption.

    Child CPU measures its body after imports and is returned separately from
    parent CPU. Child startup CPU, physical energy and charges remain unknown.
    """
    _require(type(timeout_seconds) in (float, int) and math.isfinite(timeout_seconds)
             and 0 < timeout_seconds <= 5, "INVALID_PROBE_DEADLINE")
    nonce = uuid.uuid4().hex
    source = "\n".join([
        "import hashlib,json,os,time", "w=time.monotonic_ns();c=time.process_time_ns()",
        "x=b'ndu-span-observer-probe'", "for _ in range(4000): x=hashlib.sha256(x).digest()",
        "print(json.dumps(dict(nonce=" + repr(nonce) + ",pid=os.getpid(),start_monotonic_ns=w,"
        "end_monotonic_ns=time.monotonic_ns(),start_process_time_ns=c,end_process_time_ns=time.process_time_ns(),"
        "body_digest=x.hex())),flush=True)",
    ])
    meter, status, observed = SpanMeter("stdlib-subprocess-probe:" + nonce), "SUCCEEDED", None
    with meter.attempt("probe-1") as attempt:
        with meter.span("fixed-child-computation", "shared") as span:
            try:
                child = subprocess.run([sys.executable, "-I", "-c", source], capture_output=True, timeout=timeout_seconds, check=False)
                observed = {"returncode": child.returncode, "stdout": child.stdout.decode(), "stderr": child.stderr.decode(), "body": None}
                if child.returncode == 0:
                    body = json.loads(observed["stdout"])
                    _require(body["nonce"] == nonce and body["end_process_time_ns"] >= body["start_process_time_ns"], "INVALID_CHILD_BODY")
                    observed["body"] = body
                else:
                    status = "FAILED"
            except subprocess.TimeoutExpired as error:
                status = "CANCELED"
                observed = {"returncode": None, "stdout": (error.stdout or b"").decode(errors="replace"),
                            "stderr": (error.stderr or b"").decode(errors="replace"), "body": None, "timed_out": True}
            except (OSError, ValueError, KeyError) as error:
                status = "FAILED"
                observed = {"returncode": None, "body": None, "error_type": type(error).__name__}
            span.set_status(status)
            attempt.set_status(status)
    record = meter.finish(status)
    return {"record": record, "replay": verify_record(record), "subprocess": observed,
            "child_cpu_scope": "child_body_after_imports_only_separate_from_parent",
            "child_startup_cpu_ns": None, "energy_joules": None, "provider_charges": None,
            "scientific_admission": "HOLD", "task_model_executions": 0}
