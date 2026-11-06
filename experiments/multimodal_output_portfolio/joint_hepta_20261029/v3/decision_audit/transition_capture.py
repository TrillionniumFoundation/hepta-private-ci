"""Optional development observations of the real dual runtime, never labels.

Declared train/development membership is a binding, not authenticated custody.
The journal observes existing calls; it neither selects actions nor scores them.
A partial record is not evidence of an unobserved backend return or model call.
"""

from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import threading
import time


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def file_identity(path):
    path = Path(path)
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        for part in iter(lambda: handle.read(1024 * 1024), b""):
            size += len(part)
            digest.update(part)
    return {"bytes": size, "sha256": digest.hexdigest()}


def write_new(path, value):
    raw = canonical(value) + b"\n"
    with Path(path).open("xb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


@dataclass(frozen=True)
class DevelopmentSource:
    """Explicit public request membership; excludes test/evaluator inputs."""

    split: str
    source_id: str
    image_sha256: str
    instruction_sha256: str
    roster_sha256: str

    def __post_init__(self):
        if self.split not in ("train", "development") or not self.source_id:
            raise ValueError("Only declared train/development sources can be captured")
        for name in ("image_sha256", "instruction_sha256", "roster_sha256"):
            if not re.fullmatch(r"[0-9a-f]{64}", getattr(self, name)):
                raise ValueError("Frozen source hashes must be lowercase SHA256")


class TransitionCapture:
    """One run's hash-chained observations; capture errors fence this trace.

    The original episode can still fail, abstain or deliver independently.
    Consumers must validate a COMPLETE trace, not infer it from report.status.
    A successful capture authenticates neither the declared roster nor rewards.
    """

    def __init__(self, source):
        if type(source) is not DevelopmentSource:
            raise TypeError("An explicit DevelopmentSource is required")
        self.source = source
        self._claim_lock = threading.Lock()
        self._claimed = False
        self._directory = None
        self._head = "0" * 64
        self._sequence = 0
        self._events = []
        self._costs = []
        self._ended = False
        self._fault = None
        self._run_started = None
        self._source_paths = {}
        self._source_before = {}
        self.summary = None

    def claim(self, request):
        # Called before the run creates output or invokes any backend. Reuse
        # cannot append a second episode to a previously completed capture.
        with self._claim_lock:
            if self._claimed:
                raise ValueError("TransitionCapture is single-use, including failed admission")
            self._claimed = True
            actual = (request.source_id, request.image_sha256,
                      hashlib.sha256(request.instruction.encode("utf-8")).hexdigest())
            expected = (self.source.source_id, self.source.image_sha256,
                        self.source.instruction_sha256)
            if actual != expected:
                raise ValueError("Actual request differs from the declared development roster")

    def _fail(self, error, phase):
        if self._fault is None:
            self._fault = {"phase": phase, "type": type(error).__name__, "message": str(error)}

    def _append(self, phase, payload, placement):
        row = {"sequence": self._sequence, "phase": phase,
               "previous_sha256": self._head, "payload": payload}
        row["sha256"] = hashlib.sha256(canonical(row)).hexdigest()
        with (self._directory / "transitions.jsonl").open("ab") as handle:
            handle.write(canonical(row) + b"\n")
            handle.flush()
            os.fsync(handle.fileno())
        self._sequence += 1
        self._head = row["sha256"]

    def _observe(self, phase, payload, placement):
        if self._fault is not None:
            return False
        before = time.process_time(), time.perf_counter()
        sequence = self._sequence
        ok = False
        try:
            self._append(phase, payload, placement)
            ok = True
        except Exception as error:
            self._fail(error, phase)
        finally:
            cpu = time.process_time() - before[0]
            wall = time.perf_counter() - before[1]
            self._costs.append({"sequence": sequence, "phase": phase, "placement": placement,
                                "cpu_seconds": cpu, "wall_seconds": wall, "append_returned": ok})
        return ok

    def start(self, request, output, settings, runtime_file, run_started):
        before = time.process_time(), time.perf_counter()
        self._run_started = run_started
        self._directory = Path(output) / "transition_capture"
        try:
            self._directory.mkdir(exist_ok=False)
            # Refuse a pre-existing journal even in an otherwise new directory.
            with (self._directory / "transitions.jsonl").open("xb"):
                pass
            self._source_paths = {"runtime": Path(runtime_file), "recorder": Path(__file__)}
            self._source_before = {name: file_identity(path) for name, path in self._source_paths.items()}
            self._observe("start", {
                "schema": "hepta.development-transition-capture.v1",
                "request": vars(request), "declared_source": asdict(self.source),
                "settings": settings, "runtime_source": self._source_before["runtime"],
                "recorder_source": self._source_before["recorder"],
                "roster_custody_authenticated": False, "independent_labels_available": False,
                "backend_intent_is_not_model_entry_proof": True,
            }, "inside_episode")
        except Exception as error:
            self._fail(error, "start")
        finally:
            self._costs.append({"phase": "capture_setup_envelope", "placement": "inside_episode",
                                "cpu_seconds": time.process_time() - before[0],
                                "wall_seconds": time.perf_counter() - before[1],
                                "inclusive_contains_start_append": True})

    def observe(self, phase, state, events, artifacts, selected, detail):
        if self._fault is not None:
            return
        before = time.process_time(), time.perf_counter()
        placement = "after_original_event_clock" if phase == "episode_end" else "inside_episode"
        try:
            # Copy through the actual JSON representation, never retain aliases
            # to mutable runtime state or predict a future state.
            plain = json.loads(canonical({"state": state, "events": events,
                                          "artifacts": artifacts, "selected": selected,
                                          "detail": detail}))
            if plain["events"][:len(self._events)] != self._events:
                raise ValueError("Previously observed original cost events changed")
            new_events = plain.pop("events")[len(self._events):]
            if [event["event_id"] for event in new_events] != list(
                    range(len(self._events), len(self._events) + len(new_events))):
                raise ValueError("Original cost events have a gap or duplicate")
            plain["new_original_events"] = new_events
            if self._observe(phase, plain, placement):
                self._events.extend(new_events)
                if phase == "episode_end":
                    self._ended = True
        except Exception as error:
            self._fail(error, phase)
        finally:
            self._costs.append({"phase": phase + "_envelope", "placement": placement,
                                "cpu_seconds": time.process_time() - before[0],
                                "wall_seconds": time.perf_counter() - before[1],
                                "inclusive_contains_phase_append": True})

    def finish(self, report, output):
        """Bind actual original outputs after their writes; do not rewrite them."""
        out = Path(output)
        before = time.process_time(), time.perf_counter()
        completed = None
        try:
            if self._fault is None:
                source_after = {name: file_identity(path) for name, path in self._source_paths.items()}
                if source_after != self._source_before:
                    raise ValueError("Runtime or recorder source changed during capture")
                plain = json.loads(canonical(report))
                if not self._ended or plain["events"] != self._events:
                    raise ValueError("Final original events are absent or differ from observed events")
                if json.loads((out / "report.json").read_bytes()) != plain:
                    raise ValueError("Original on-disk report differs from the actual return value")
                retained = []
                for item in plain["retained_files"]:
                    if Path(item["path"]).name != item["path"]:
                        raise ValueError("Retained artifact is not an original direct-child file")
                    actual = file_identity(out / item["path"])
                    if actual != {key: item[key] for key in actual}:
                        raise ValueError("Original retained artifact changed after inventory")
                    retained.append(item)
                selected = {(item["path"], item["sha256"]) for item in plain["selected"]}
                completed = {
                    "source_files_after": source_after,
                    "report": file_identity(out / "report.json"),
                    "report_write_cost": file_identity(out / "report_write_cost.json"),
                    "request_file": file_identity(out / "request.json") if (out / "request.json").is_file() else None,
                    "backend_files": {name: file_identity(out / name) for name in
                                      ("backend.json", "backend_final.json") if (out / name).is_file()},
                    "episode_status": plain["status"], "episode_error": plain["error"],
                    "retained_files": retained, "selected": plain["selected"],
                    "unselected_retained_files": [item for item in retained if
                        (item["path"], item["sha256"]) not in selected],
                    "original_cost": {key: plain[key] for key in
                                      ("cpu_seconds", "wall_seconds", "tariff_amount", "tariffs", "unknown_costs")},
                }
                self._observe("finish", completed, "after_original_report")
        except Exception as error:
            self._fail(error, "finish")
        # This envelope includes verification and the finish append; do not add
        # it again to nested append timings. The summary write is measured next.
        self._costs.append({"phase": "capture_finalize_envelope", "placement": "after_original_report",
                            "cpu_seconds": time.process_time() - before[0],
                            "wall_seconds": time.perf_counter() - before[1],
                            "inclusive_contains_finish_append": True})
        self.summary = {
            "schema": "hepta.development-transition-summary.v1",
            "status": "COMPLETE" if self._fault is None and completed else "INCOMPLETE",
            "fault": self._fault, "records": self._sequence, "chain_head": self._head,
            "result": completed, "observation_costs": self._costs,
            "run_envelope_through_capture_finalize": {
                "cpu_seconds": time.process_time() - self._run_started[0],
                "wall_seconds": time.perf_counter() - self._run_started[1],
                "scope": "inclusive original run clock through capture finalization; excludes initial output mkdir and subsequent summary/receipt writes",
            } if self._run_started is not None else None,
            "cost_rule": "inside_episode timings are already in original intervals; episode_end/finalize/summary are outer; inclusive envelopes must not be added to nested append or original event timings",
            "unknown_costs": ["observer bookkeeping outside measured calls", "last capture-write receipt construction/write", "child process CPU", "energy"],
            "roster_custody_authenticated": False, "independent_evaluation": False,
            "training_performed": False, "production_qualified": False,
        }
        summary_start = time.process_time(), time.perf_counter()
        try:
            summary_identity = write_new(self._directory / "SUMMARY.json", self.summary)
            write_new(self._directory / "summary_write_cost.json", {
                "summary": summary_identity,
                "cpu_seconds": time.process_time() - summary_start[0],
                "wall_seconds": time.perf_counter() - summary_start[1],
                "scope": "outer summary serialization/write/fsync; this receipt's own construction/write is unknown",
            })
        except Exception as error:
            self._fail(error, "summary_write")
            self.summary["status"], self.summary["fault"] = "INCOMPLETE", self._fault
        return self.summary
