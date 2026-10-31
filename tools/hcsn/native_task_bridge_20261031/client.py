"""Measured, persistent JSONL transport to the real native task adapter.

This transports externally produced features and cell snapshots. It never
represents hash adoption as native execution of the cell dynamics or planner.
"""
import hashlib
import json
import os
from pathlib import Path
import selectors
import subprocess
import time

from .reference import NUMERIC_CONTRACT, deployment_digest


def canonical_digest(value):
    data = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(data).hexdigest()


class NativeClient:
    def __init__(self, binary, checkpoint, owner_dir, run_id, objective,
                 sequence=0, checkpoint_before="0"*64):
        started, cpu = time.perf_counter(), time.process_time()
        self.checkpoint_path = Path(checkpoint).resolve()
        self.model_sha256 = hashlib.sha256(self.checkpoint_path.read_bytes()).hexdigest()
        self.owner_dir = Path(owner_dir).resolve()
        self.owner_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.sequence, self.anchor = int(sequence), checkpoint_before
        self.calls, self.failures, self.request_bytes, self.response_bytes = 0, 0, 0, 0
        self.transport_wall, self.parent_cpu = 0., 0.
        self.native_micros, self.model_micros, self.journal_bytes = 0, 0, 0
        self.closed = False
        self.stderr_path = self.owner_dir / f"native-stderr-{sequence}.log"
        self._stderr = self.stderr_path.open("xb")
        self.process = subprocess.Popen([str(Path(binary).resolve()), str(self.checkpoint_path),
            str(self.owner_dir), run_id, objective, str(self.sequence), self.anchor],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self._stderr)
        self.selector = selectors.DefaultSelector()
        self.selector.register(self.process.stdout, selectors.EVENT_READ)
        self.setup_wall = time.perf_counter()-started
        self.setup_parent_cpu = time.process_time()-cpu

    def query(self, features, prior, feasible, cell_snapshot_sha256, public_state_sha256,
              monotonic_time_micros=None):
        if self.closed:
            raise RuntimeError("Native client already closed")
        start, cpu = time.perf_counter(), time.process_time()
        if monotonic_time_micros is None:
            monotonic_time_micros = (self.sequence+1)*1000
        payload = dict(numeric_contract=NUMERIC_CONTRACT, sequence=self.sequence+1, monotonic_time_micros=int(monotonic_time_micros),
            checkpoint_before=self.anchor, model_sha256=self.model_sha256,
            cell_snapshot_sha256=cell_snapshot_sha256, public_state_sha256=public_state_sha256,
            features=list(map(float, features)), prior=[float(q) if legal else 0. for q, legal in zip(prior, feasible)],
            feasible=list(map(bool, feasible)))
        encoded = (json.dumps(payload, separators=(",", ":"), allow_nan=False)+"\n").encode()
        self.request_bytes += len(encoded)
        self.calls += 1
        try:
            self.process.stdin.write(encoded)
            self.process.stdin.flush()
            if not self.selector.select(timeout=30.):
                raise TimeoutError("Native request did not complete within declared 30 seconds")
            line = self.process.stdout.readline(1_048_577)
            self.response_bytes += len(line)
            if not line.endswith(b"\n") or len(line) > 1_048_576:
                raise RuntimeError("Native process exited or produced unbounded response")
            response = json.loads(line)
            if not response["ok"]:
                raise RuntimeError(response["error"])
            receipt = response["receipt"]
            if (receipt["numeric_contract"] != NUMERIC_CONTRACT
                    or receipt["deployment_identity_sha256"] != deployment_digest(self.model_sha256)):
                raise RuntimeError("Native numeric deployment identity mismatch")
            if receipt["sequence"] != self.sequence+1 or receipt["checkpoint_before"] != self.anchor:
                raise RuntimeError("Native receipt acknowledgement mismatch")
            self.sequence, self.anchor = receipt["sequence"], receipt["checkpoint_after"]
            self.native_micros += receipt["native_execution_micros"]
            self.model_micros += receipt["model_execution_micros"]
            self.journal_bytes += receipt["journal_bytes_written"]
            receipt["transport_wall_seconds"] = time.perf_counter()-start
            receipt["transport_parent_cpu_seconds"] = time.process_time()-cpu
            return receipt
        except Exception:
            self.failures += 1
            raise
        finally:
            self.transport_wall += time.perf_counter()-start
            self.parent_cpu += time.process_time()-cpu

    def close(self):
        if not self.closed:
            started = time.perf_counter()
            self.process.stdin.close()
            deadline = time.monotonic()+30.
            while True:
                pid, status, usage = os.wait4(self.process.pid, os.WNOHANG)
                if pid:
                    code = os.waitstatus_to_exitcode(status)
                    self.process.returncode = code
                    self.child_usage = dict(user_cpu_seconds=usage.ru_utime,
                        system_cpu_seconds=usage.ru_stime,
                        peak_rss_bytes=usage.ru_maxrss*1024,
                        voluntary_context_switches=usage.ru_nvcsw,
                        involuntary_context_switches=usage.ru_nivcsw)
                    break
                if time.monotonic() > deadline:
                    raise TimeoutError("Native close did not finish within 30 seconds")
                time.sleep(.005)
            self.process.stdout.close()
            self.selector.close()
            self._stderr.close()
            self.close_wall = time.perf_counter()-started
            self.closed = True
            if code:
                raise RuntimeError(f"Native process exited with code {code}")
        return self.accounting()

    def accounting(self):
        return dict(calls=self.calls, failed_calls=self.failures, request_bytes=self.request_bytes,
            response_bytes=self.response_bytes, process_setup_wall_seconds=self.setup_wall,
            process_setup_parent_cpu_seconds=self.setup_parent_cpu, transport_wall_seconds=self.transport_wall,
            transport_parent_cpu_seconds=self.parent_cpu, native_execution_micros=self.native_micros,
            model_execution_micros=self.model_micros, journal_bytes_written=self.journal_bytes,
            child_process_usage=getattr(self, "child_usage", None),
            child_usage_source="Linux wait4 for this exact child; entire process lifetime",
            close_wall_seconds=getattr(self, "close_wall", None),
            native_physics_executed=False, production_activation=False)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()
