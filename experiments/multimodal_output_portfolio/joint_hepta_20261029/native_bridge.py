"""Serial research guard using the actual unchanged AgentdNeuronOwner host.

The Rust finite encoder sees only its registered phase/feedback alphabet. The
PyTorch generator and NDU policy execute in Python; their identities, decisions,
and actual output file hashes are bound into every native event receipt. Native
confidence certifies only that finite encoder domain, never semantic quality.
The owner retains DENY_ALL. A separate bounded research permit controls the
Python dispatcher, and native abstention actually prevents further dispatch.
"""

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import selectors
import signal
import subprocess
import time


Q24 = 1 << 24
SOURCE_COMMIT = "a50c8974ac23c20c5174f7c3ad542a96e5652854"
FEEDBACK = (-1.0, -0.5, 0.0, 1.0)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def file_sha(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while chunk := stream.read(1 << 20):
            result.update(chunk)
    return result.hexdigest()


def _write(path, value):
    with Path(path).open("x") as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")


def _sha(value):
    if not isinstance(value, str) or not re.fullmatch("[0-9a-f]{64}", value):
        raise ValueError("A lowercase SHA256 digest is required")
    return value


class _Process:
    """Original client's JSON-lines protocol with bounded POSIX response wait."""

    def __init__(self, binary):
        if os.name == "nt":
            raise ValueError("This inherited fsync journal host is a POSIX research probe")
        self.process = subprocess.Popen(
            [str(binary)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, bufsize=1,
        )
        self._protocol_failed = False
        self._usage = None

    def call(self, request):
        if self._protocol_failed:
            raise RuntimeError("A failed native transport cannot accept further requests")
        try:
            self.process.stdin.write(canonical(request).decode() + "\n")
            self.process.stdin.flush()
            with selectors.DefaultSelector() as selector:
                selector.register(self.process.stdout, selectors.EVENT_READ)
                if not selector.select(timeout=30):
                    raise TimeoutError("Native owner failed to acknowledge within 30 seconds")
            line = self.process.stdout.readline()
            if not line:
                raise RuntimeError("Native owner exited before acknowledging the request")
            return json.loads(line)
        except Exception:
            # A timed-out response must not be mistaken for the next command's
            # response during cleanup. Closing/reaping remains available.
            self._protocol_failed = True
            raise

    def finish(self, *, timeout=10, terminate_on_timeout=False):
        if self._usage is not None:
            return dict(self._usage)
        try:
            self.process.stdin.close()
        except BrokenPipeError:
            pass
        deadline = time.monotonic() + timeout
        sent_signals = []
        while True:
            waited, status, usage = os.wait4(self.process.pid, os.WNOHANG)
            if waited:
                self.process.returncode = os.waitstatus_to_exitcode(status)
                break
            if time.monotonic() >= deadline:
                if not terminate_on_timeout or len(sent_signals) == 2:
                    raise TimeoutError("Native owner did not exit after stdin close")
                selected = signal.SIGTERM if not sent_signals else signal.SIGKILL
                try:
                    # Popen.terminate() polls and can reap without wait4. Send
                    # only to this owned PID so its exact usage is retained.
                    os.kill(self.process.pid, selected)
                except ProcessLookupError:
                    pass
                sent_signals.append(selected.name)
                deadline = time.monotonic() + 1
            time.sleep(0.01)
        error = self.process.stderr.read()
        self.process.stdout.close()
        self.process.stderr.close()
        self._usage = {"pid": self.process.pid, "user_seconds": usage.ru_utime,
                       "system_seconds": usage.ru_stime,
                       "cpu_seconds": usage.ru_utime + usage.ru_stime,
                       "returncode": self.process.returncode, "stderr_tail": error[-4000:],
                       "termination_signals": sent_signals,
                       "measurement": "POSIX wait4 usage of this exact native child PID"}
        return dict(self._usage)


class NativeGuard:
    """Bounded guard around externally selected actions and actual media writes.

    ``perform(action, trace, dispatch)`` calls ``dispatch()`` only after a real
    native gate. The callback returns artifact_refs, artifact_sha256,
    public_feedback in {-1,-.5,0,1}, and optionally final_state_digest. File bytes
    are reopened and verified before feedback reaches the owner. ``stop`` is
    terminal; ``reopen`` replaces the OS process and recovers the native journal.
    """

    def __init__(
        self, *, binary, directory, case, model_sha256, profile_sha256,
        allowed_actions=("continue", "stop"), max_actions=8, expires=64,
        readout=None, calibration=None, max_artifact_bytes=16 << 20, build_receipt=None,
    ):
        self._self_cpu_start = time.process_time()
        self.native_process_cpu = []
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", case):
            raise ValueError("case must be a bounded stable research identity")
        if type(max_actions) is not int or not 1 <= max_actions <= 8:
            raise ValueError("The inherited 32-record host supports at most eight actions here")
        if expires not in (6, 7, 64):
            raise ValueError("Unregistered native calibration lifetime")
        if (not allowed_actions or "stop" not in allowed_actions
                or len(set(allowed_actions)) != len(allowed_actions)
                or any(not isinstance(a, str) or not re.fullmatch(r"[a-zA-Z0-9_.-]{1,64}", a)
                       for a in allowed_actions)):
            raise ValueError("A finite action permit including stop is required")
        if type(max_artifact_bytes) is not int or max_artifact_bytes < 1:
            raise ValueError("A positive artifact byte capacity is required")
        self.binary = Path(binary).resolve()
        build_path = (Path(build_receipt).resolve() if build_receipt else
                      self.binary.parents[3] / "BUILD_RECEIPT.json")
        built = json.loads(build_path.read_text())
        binary_sha = file_sha(self.binary)
        if (built.get("schema") != "hepta.joint-output.native-build.v1"
                or built.get("source_commit") != SOURCE_COMMIT
                or built.get("binary_sha256") != binary_sha
                or built.get("owner_and_three_crates_unmodified") is not True
                or built.get("host_sources_unmodified") is not True
                or built.get("all_dependencies_name_version_source_checksum_match") is not True):
            raise ValueError("Binary is not bound to the qualified unchanged native build")
        self.directory = Path(directory).resolve()
        self.directory.mkdir(parents=True, exist_ok=False)
        self.case, self.expires = case, expires
        self.max_actions, self.max_artifact_bytes = max_actions, max_artifact_bytes
        self.actions, self.finished = 0, False
        self.history, self.transcript, self.recoveries = [], [], []
        self.failures, self.current_action = [], None
        self.process, self._process_reaped = None, False
        self.last_artifact_sha256 = {}
        self.allowed_actions = tuple(allowed_actions)
        self.readout = Path(readout).resolve() if readout else self.directory / "NATIVE_DIAGNOSTIC_HEAD.json"
        self.calibration = Path(calibration).resolve() if calibration else self.directory / "NATIVE_DOMAIN_PROOF.json"
        if readout is None:
            # A constant diagnostic head is intentionally NOT described as the
            # trained generator or policy. Its proposed_repair output is unused.
            _write(self.readout, {"schema": "hepta.continuation.owner-readout.v1", "weights": [0.0] * 11})
        if calibration is None:
            _write(self.calibration, {
                "schema": "hepta.continuation.encoder-domain-proof.v1",
                "confidence_target": "registered_public_encoder_domain_validity",
                "semantic_quality_qualification": False,
                "finite_domain_ece_ppm": 0, "finite_domain_false_acceptance_ppm": 0,
                "basis": "Deterministic drive equals prediction on registered phase/feedback alphabet; invalid input is rejected",
                "valid_feedback_symbols": list(FEEDBACK), "active_sequence_only": True,
            })
        self.identity = {
            "schema": "hepta.joint-output.native-guard.v1", "source_commit": SOURCE_COMMIT,
            "case": case, "generator_model_sha256": _sha(model_sha256),
            "ndu_profile_sha256": _sha(profile_sha256),
            "binary_sha256": binary_sha,
            "native_build_receipt_sha256": file_sha(build_path),
            "native_readout_sha256": file_sha(self.readout),
            "native_calibration_sha256": file_sha(self.calibration),
            "native_readout_role": "caller-provided diagnostic" if readout else "constant untrained diagnostic; not action selector",
            "allowed_actions": list(allowed_actions), "max_actions": max_actions,
            "owner_authority": "DENY_ALL", "full_daemon_activation": False,
            "trained_tensor_model_executed_inside_native_port": False,
            "native_readout_selected_host_action": False,
            "permit_scope": "bounded local research dispatcher only",
        }
        _write(self.directory / "BRIDGE_IDENTITY.json", self.identity)
        try:
            self.process = _Process(self.binary)
            self._open("Open")
        except Exception as error:
            self.abort("native_open_failed", error=error)
            raise

    def _call(self, request, *, expect_error=False):
        began = time.perf_counter()
        response = self.process.call(request)
        self.transcript.append({"request": request, "response": response,
                                "host_roundtrip_wall_seconds": time.perf_counter() - began})
        if response.get("ok") == expect_error:
            raise RuntimeError("Unexpected native owner response: " + repr(response))
        return response.get("result", response)

    def _open(self, command):
        return self._call({
            "command": command, "directory": str(self.directory / "owner"),
            "case": self.case, "expires": self.expires,
            "model": str(self.readout), "model_sha256": self.identity["native_readout_sha256"],
            "calibration": str(self.calibration),
            "calibration_sha256": self.identity["native_calibration_sha256"],
        })

    def _tick(self, label, phase, feedback, evidence):
        if feedback not in FEEDBACK or not math.isfinite(feedback):
            raise ValueError("Public feedback must use the registered finite encoder alphabet")
        payload = {"identity_sha256": digest(self.identity), **evidence}
        if len(canonical(payload)) > 65536:
            raise ValueError("Native evidence payload exceeds the bounded research permit")
        result = self._call({
            "command": "Tick", "event_id": f"{self.case}.{label}",
            "phase": phase, "feedback_q24": round(feedback * Q24),
            "receipt_digest": digest(payload),
        })
        self.transcript[-1]["bound_evidence"] = payload
        if result["owner_authority"] != "DENY_ALL" or not result["native_transition_executed"]:
            raise ValueError("Native event did not execute under the declared authority")
        return result

    def perform(self, action, action_trace, dispatch=None):
        if self.finished:
            raise ValueError("Native-guarded episode is already stopped")
        if action not in self.allowed_actions:
            raise ValueError("Action is outside the research permit")
        if not isinstance(action_trace, dict):
            raise ValueError("A concrete action trace must be supplied")
        trace = json.loads(canonical(action_trace))
        if action == "stop":
            return self.stop(reason="policy_stop", action_trace=trace)
        if not callable(dispatch):
            raise ValueError("A real dispatcher callback is required")
        self.current_action = {"action": action, "action_index": self.actions,
                               "action_trace": trace, "dispatch_entered": False,
                               "dispatch_completed": False}
        try:
            result = self._perform_action(action, trace, dispatch)
        except Exception as error:
            self.abort("native_action_failed", action_trace=trace, error=error)
            raise
        self.current_action = None
        return result

    def _perform_action(self, action, trace, dispatch):
        if self.actions >= self.max_actions:
            return self.stop(reason="action_budget", action_trace=trace)
        evidence = {"action": action, "action_index": self.actions, "action_trace": trace,
                    "previous_artifact_sha256": self.last_artifact_sha256}
        gate = self._tick(f"action.{self.actions}.gate", 0, 0.0, evidence)
        if gate["native_abstain"]:
            return self.stop(reason="native_abstain_before_dispatch", action_trace=trace)
        index = self.actions
        self.actions += 1
        started = time.perf_counter()
        self.current_action["dispatch_entered"] = True
        delivered = dispatch()
        self.current_action["dispatch_completed"] = True
        dispatch_seconds = time.perf_counter() - started
        if not isinstance(delivered, dict):
            raise ValueError("Dispatcher must return its actual result receipt")
        refs, hashes = delivered.get("artifact_refs", {}), delivered.get("artifact_sha256", {})
        if not isinstance(refs, dict) or not isinstance(hashes, dict) or set(refs) != set(hashes) or len(refs) > 16:
            raise ValueError("Physical artifact references and hashes must match")
        refs, hashes = {name: str(Path(path).resolve()) for name, path in refs.items()}, dict(hashes)
        total_bytes = 0
        for name, path in refs.items():
            total_bytes += Path(path).stat().st_size
            if total_bytes > self.max_artifact_bytes or file_sha(path) != _sha(hashes[name]):
                raise ValueError("Actual output bytes exceed capacity or differ from the declared digest")
        if not refs:
            _sha(delivered.get("final_state_digest"))
        feedback = delivered["public_feedback"]
        if isinstance(feedback, bool) or feedback not in FEEDBACK:
            raise ValueError("Dispatcher feedback is outside the native finite alphabet")
        actual = {**evidence, "artifact_sha256": hashes, "public_feedback": feedback,
                  "final_state_digest": delivered.get("final_state_digest"), "actual_output_bytes": total_bytes}
        tick = self._tick(f"action.{index}.feedback", 1, feedback, actual)
        hold = self._tick(f"action.{index}.hold", 2, 0.0, actual)
        record = {"action": action, "action_index": index, "executed": True,
                  "action_trace": trace, "artifact_refs": refs, "artifact_sha256": hashes,
                  "public_feedback": feedback, "verified_artifact_bytes": total_bytes,
                  "final_state_digest": delivered.get("final_state_digest"),
                  "dispatch_wall_seconds": dispatch_seconds,
                  "gate": gate, "feedback_tick": tick, "hold_tick": hold,
                  "native_abstain_after_dispatch": tick["native_abstain"] or hold["native_abstain"]}
        self.history.append(record)
        self.last_artifact_sha256 = dict(hashes)
        if record["native_abstain_after_dispatch"]:
            self.stop(reason="native_abstain_after_dispatch", action_trace=trace)
        return record

    def reopen(self):
        if self.finished:
            raise ValueError("A terminated episode cannot resume generation")
        try:
            before = self._call({"command": "Status"})
            if before["sequence"] == 0:
                raise ValueError("Cold recovery requires a committed native prefix")
            began = time.perf_counter()
            closed = self._call({"command": "Close"})
            self._finish_process()
            replacement = _Process(self.binary)
            self.process, self._process_reaped = replacement, False
            after = self._open("Resume")
            if before != closed or before != after:
                raise ValueError("Native state changed during cold process recovery")
        except Exception as error:
            self.abort("native_recovery_failed", error=error)
            raise
        receipt = {"before": before, "after": after, "same_native_state": True,
                   "new_os_process": True, "wall_seconds": time.perf_counter() - began,
                   "ledger_validation_kernel_steps": before["durable_event_count"],
                   "trained_tensor_runtime_restore": "separate caller-owned checkpoint"}
        self.recoveries.append(receipt)
        return receipt

    def stop(self, *, reason="policy_stop", action_trace=None):
        if self.finished:
            return self.final_record
        try:
            tick = self._tick("stop", 3, 0.0, {"terminal_reason": reason,
                              "action_trace": action_trace or {},
                              "final_artifact_sha256": self.last_artifact_sha256})
            closed = self._call({"command": "Close"})
            self._finish_process()
        except Exception as error:
            self.abort("native_stop_failed", action_trace=action_trace, error=error)
            raise
        self.finished = True
        self.final_record = {"action": "stop", "executed": False, "reason": reason,
                             "native_stop_tick": tick, "native_closed_status": closed,
                             "native_process_reaped": self._process_reaped,
                             "aborted": False,
                             "actual_dispatched_actions": self.actions}
        _write(self.directory / "NATIVE_RECEIPT.json", self.receipt())
        return self.final_record

    def _finish_process(self, *, abort=False):
        if self.process is None or self._process_reaped:
            return
        usage = self.process.finish(timeout=2 if abort else 10, terminate_on_timeout=abort)
        self.native_process_cpu.append(usage)
        self._process_reaped = True
        if usage.get("returncode", 0) and not abort:
            raise RuntimeError("Native owner exited unsuccessfully: " + usage.get("stderr_tail", ""))

    def abort(self, reason, *, action_trace=None, error=None):
        """Fail closed and reap the owned child after an ordinary exception.

        This method returns cleanup evidence instead of hiding the original
        error. A lost transport cannot prove an acknowledged native STOP; it is
        closed and reaped, and that distinction remains explicit in the receipt.
        KeyboardInterrupt and SystemExit are never caught by this adapter.
        """
        if self.finished:
            return self.final_record
        try:
            trace = json.loads(canonical(action_trace or {}))
        except Exception:
            trace = {"invalid_action_trace": True}
        failure = {"reason": str(reason), "action_trace": trace,
                   "error_type": type(error).__name__ if error is not None else None,
                   "error": str(error)[:4000] if error is not None else None}
        self.failures.append(failure)
        if (self.current_action is not None
                and not any(row.get("action_index") == self.current_action["action_index"]
                            for row in self.history)):
            self.history.append({**self.current_action, "executed": False,
                                 "failed": True, "failure": failure})
        tick, closed, cleanup_errors = None, None, []

        def usable():
            return (self.process is not None and not self._process_reaped
                    and not getattr(self.process, "_protocol_failed", False))

        if usable():
            try:
                tick = self._tick("abort", 3, 0.0, {"terminal_failure": failure,
                                  "final_artifact_sha256": self.last_artifact_sha256})
            except Exception as cleanup_error:
                cleanup_errors.append({"stage": "native_abort_tick", "error": str(cleanup_error)[:4000]})
        if usable():
            try:
                closed = self._call({"command": "Close"})
            except Exception as cleanup_error:
                cleanup_errors.append({"stage": "native_close", "error": str(cleanup_error)[:4000]})
        try:
            self._finish_process(abort=True)
        except Exception as cleanup_error:
            cleanup_errors.append({"stage": "native_reap", "error": str(cleanup_error)[:4000]})
        self.finished = True
        self.final_record = {"action": "stop", "executed": False, "reason": str(reason),
                             "aborted": True, "failure": failure,
                             "native_stop_tick": tick, "native_closed_status": closed,
                             "native_process_reaped": self._process_reaped,
                             "cleanup_errors": cleanup_errors,
                             "actual_dispatched_actions": self.actions}
        self.current_action = None
        for name in ("NATIVE_FAILURE.json", "NATIVE_RECEIPT.json"):
            try:
                if not (self.directory / name).exists():
                    _write(self.directory / name, self.receipt())
            except Exception as cleanup_error:
                cleanup_errors.append({"stage": "write_" + name, "error": str(cleanup_error)[:4000]})
        return self.final_record

    def receipt(self):
        ticks = [row["response"]["result"] for row in self.transcript
                 if (row["request"]["command"] == "Tick" and row["response"].get("ok")
                     and isinstance(row["response"].get("result"), dict))]
        physical = sum(row["response"].get("physical_receipt_processing_micros", 0) for row in self.transcript)
        return {"identity": self.identity, "history": self.history,
                "recoveries": self.recoveries, "transcript": self.transcript,
                "failures": self.failures,
                "finished": self.finished, "final": getattr(self, "final_record", None),
                "native_tick_count": len(ticks), "native_host_processing_micros": physical,
                "native_execution_micros": sum(t.get("execution_micros", 0) for t in ticks),
                "native_journal_bytes_written": sum(t.get("journal_bytes_written", 0) for t in ticks),
                "native_checkpoint_peak_bytes": max((t.get("checkpoint_bytes", 0) for t in ticks), default=0),
                "native_process_cpu": self.native_process_cpu,
                "native_owner_cpu_seconds": (sum(p["cpu_seconds"] for p in self.native_process_cpu)
                                             if self.finished and self._process_reaped else None),
                "native_process_reaped": self._process_reaped,
                "host_process_cpu_seconds_during_guard_lifetime": time.process_time() - self._self_cpu_start,
                "cpu_accounting_scope": "Native CPU includes ticks and recovery; host-process CPU includes dispatcher and overlaps the caller's episode meter; other children are caller-metered",
                "actual_dispatched_actions": self.actions,
                "native_policy_readout_used_for_action": False}


def lifecycle_probe(binary, output):
    """Actual native tick/reopen/expiry probe; never substitutes a Python owner."""
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    calls = []

    def dispatch():
        path = output / f"artifact-{len(calls)}.txt"
        path.write_text(f"actual dispatcher call {len(calls)}\n")
        calls.append(str(path))
        return {"artifact_refs": {"text": str(path)}, "artifact_sha256": {"text": file_sha(path)},
                "public_feedback": 1.0}

    guard = NativeGuard(binary=binary, directory=output / "recovery", case="joint.lifecycle",
                        model_sha256=digest({"probe_model": True}), profile_sha256=digest({"probe_profile": True}))
    guard.perform("continue", {"step": 0}, dispatch)
    recovered = guard.reopen()
    guard.perform("continue", {"step": 1}, dispatch)
    terminal = guard.perform("stop", {"step": 2}, dispatch)
    try:
        guard.perform("continue", {"step": 3}, dispatch)
    except ValueError:
        stopped_rejects = True
    else:
        stopped_rejects = False
    before_expiry_calls = len(calls)
    expired = NativeGuard(binary=binary, directory=output / "expiry", case="joint.expiry", expires=6,
                          model_sha256=digest({"probe_model": True}), profile_sha256=digest({"probe_profile": True}))
    expired.perform("continue", {"step": 0}, dispatch)
    expired.perform("continue", {"step": 1}, dispatch)
    declined = expired.perform("continue", {"step": 2}, dispatch)
    passed = (recovered["same_native_state"] and terminal["actual_dispatched_actions"] == 2
              and stopped_rejects and len(calls) - before_expiry_calls == 2
              and declined["reason"] == "native_abstain_before_dispatch")
    result = {"schema": "hepta.joint-output.native-lifecycle-probe.v1", "passed": passed,
              "actual_native_owner": True, "cold_recovery_exact": recovered["same_native_state"],
              "stop_prevented_later_dispatch": stopped_rejects,
              "expiry_prevented_third_dispatch": len(calls) - before_expiry_calls == 2,
              "recovery_receipt": guard.receipt(), "expiry_receipt": expired.receipt()}
    _write(output / "LIFECYCLE_PROBE.json", result)
    if not passed:
        raise ValueError("Native lifecycle probe failed")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    options = parser.parse_args()
    print(json.dumps({"passed": lifecycle_probe(options.binary, options.output)["passed"]}))
