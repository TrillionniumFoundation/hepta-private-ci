"""Persistent original-native kernel/owner adapter; no Python sparse emulator.

Actions are ordered keep, repair, stop. All temporal updates and final score
comparisons execute inside the Rust binary. Mathematical cell feature production
may remain a separately identified Python research adapter.
"""

import hashlib
import json
import math
import os
from pathlib import Path
import resource
import subprocess
import time

Q = 1 << 24
ACTIONS = ("keep", "repair", "stop")


def digest(value):
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def quantize(value, bound=8):
    value = float(value)
    if not math.isfinite(value) or abs(value) > bound:
        raise ValueError(f"Out-of-domain Q24 value: {value}")
    return round(value * Q)


def features(raw, *, margin=0.0, risk=0.0, flow=0.0):
    if not 0 <= risk <= 1:
        raise ValueError("risk is a probability, not a put value")
    return {
        "raw_q24": [quantize(x) for x in raw],
        "continuous": {
            "margin_q24": quantize(margin),
            "risk_q24": quantize(risk, 1),
            "flow_q24": quantize(flow),
        },
    }


def make_profile(
    feature_names,
    encoder_weights,
    encoder_bias,
    head_weights,
    head_bias,
    *,
    source_model_digest,
    objective_digest,
    arm_id,
    stage="act",
    kernel=None,
    use_margin=True,
    use_risk=True,
    use_flow=True,
    maximum_ticks=512,
):
    width = len(encoder_weights)
    if kernel is None:
        kernel = {
            "width": width,
            "top_k": max(1, width // 5),
            "temporal_decay_q24": 3 * Q // 4,
            "activity_decay_q24": 3 * Q // 4,
            "target_activity_q24": Q // 5,
            "threshold_rate_q24": Q // 64,
            "threshold_min_q24": 0,
            "threshold_max_q24": Q // 2,
            "eligibility_decay_q24": Q // 2,
        }
    return {
        "schema": "hepta.continuous-boundary.native-profile.v1",
        "profile_id": "continuous-cell.v1",
        "source_model_digest": source_model_digest,
        "objective_digest": objective_digest,
        "arm_id": arm_id,
        "stage": stage,
        "feature_names": list(feature_names),
        "use_margin": use_margin,
        "use_risk": use_risk,
        "use_flow": use_flow,
        "kernel": kernel,
        "encoder_weights_q24": [[quantize(v) for v in row] for row in encoder_weights],
        "encoder_bias_q24": [quantize(v) for v in encoder_bias],
        "head_weights_q24": [[quantize(v) for v in row] for row in head_weights],
        "head_bias_q24": [quantize(v) for v in head_bias],
        "risk_ceiling_q24": Q,
        "maximum_ticks": maximum_ticks,
        "tick_micros": 10000,
    }


def save_profile(directory, profile):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    raw = (
        json.dumps(
            profile, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
        + b"\n"
    )
    identity = hashlib.sha256(raw).hexdigest()
    path = directory / f"{identity}.json"
    if path.exists() and path.read_bytes() != raw:
        raise ValueError("Conflicting immutable profile")
    if not path.exists():
        with path.open("xb") as stream:
            stream.write(raw)
    return path, identity


class NativeBridge:
    """One long-lived executable: batched causal kernels and one durable owner."""

    def __init__(self, binary, root, *, expected_binary_sha256=None):
        self.binary, self.root = Path(binary).resolve(), Path(root).resolve()
        actual = hashlib.sha256(self.binary.read_bytes()).hexdigest()
        if expected_binary_sha256 is not None and actual != expected_binary_sha256:
            raise ValueError("Native binary identity changed")
        self.root.mkdir(parents=True, exist_ok=True)
        permit = {
            "schema": "hepta.continuous-boundary.local-research-permit.v1",
            "allowed_root": str(self.root),
            "external_effects": False,
            "production_authority": False,
        }
        permit_path = self.root / "RESEARCH_PERMIT.json"
        if permit_path.exists() and json.loads(permit_path.read_text()) != permit:
            raise ValueError("Conflicting research-root permit")
        permit_path.write_text(json.dumps(permit, sort_keys=True) + "\n")
        self.stderr = (self.root / "native.stderr.log").open("ab")
        self.cpu_before = resource.getrusage(resource.RUSAGE_CHILDREN)
        self.start_ns = time.perf_counter_ns()
        self.process = subprocess.Popen(
            [str(self.binary), str(self.root)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=self.stderr,
            text=True,
            bufsize=1,
        )
        self.counters = {
            "rpc_calls": 0,
            "actual_kernel_calls": 0,
            "actual_ndu_calls": 0,
            "original_journal_replay_steps": 0,
            "event_validation_kernel_steps": 0,
            "event_validation_ndu_calls": 0,
            "native_physical_rpc_micros": 0,
            "python_roundtrip_ns": 0,
            "request_bytes": 0,
            "response_bytes": 0,
            "owner_ticks": 0,
            "batch_ticks": 0,
            "native_errors": 0,
        }
        self.current = None
        self.closed_receipt = None
        self.identity = self.rpc({"command": "Identity"})
        if self.identity["binary_sha256"] != actual:
            raise ValueError("Runtime binary identity mismatch")

    def rpc(self, request, *, allow_error=False):
        raw = json.dumps(request, separators=(",", ":"), allow_nan=False) + "\n"
        if len(raw.encode()) > 16 * 1024 * 1024:
            raise ValueError("Bounded native request exceeded")
        started = time.perf_counter_ns()
        self.process.stdin.write(raw)
        self.process.stdin.flush()
        response = self.process.stdout.readline()
        self.counters["python_roundtrip_ns"] += time.perf_counter_ns() - started
        self.counters["request_bytes"] += len(raw.encode())
        self.counters["response_bytes"] += len(response.encode())
        self.counters["rpc_calls"] += 1
        if not response:
            raise RuntimeError(
                f"Native host exited; inspect {self.root / 'native.stderr.log'}"
            )
        envelope = json.loads(response)
        self.counters["native_physical_rpc_micros"] += envelope["physical_rpc_micros"]
        if not envelope["ok"]:
            self.counters["native_errors"] += 1
            if allow_error:
                return envelope
            raise RuntimeError(envelope["error"])
        result = envelope["result"]
        for key in (
            "actual_kernel_calls",
            "actual_ndu_calls",
            "original_journal_replay_steps",
            "event_validation_kernel_steps",
            "event_validation_ndu_calls",
        ):
            self.counters[key] += result.get(key, 0)
        if request["command"] in ("KernelBatch", "KernelAdvance"):
            self.counters["batch_ticks"] += result.get("actual_kernel_calls", 0)
        if request["command"] == "Tick" and result.get("native_transition_executed"):
            self.counters["owner_ticks"] += 1
            self.counters["actual_kernel_calls"] += 1
        return result

    def load_profile(self, path, identity=None):
        path = Path(path).resolve()
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if identity is not None and actual != identity:
            raise ValueError("Frozen profile changed before native load")
        self.rpc({"command": "LoadProfile", "path": str(path), "sha256": actual})
        return actual

    def kernel_batch(self, profile_sha256, sequences):
        return self.rpc(
            {
                "command": "KernelBatch",
                "profile_sha256": profile_sha256,
                "sequences": sequences,
            }
        )

    def kernel_reset(self, profile_sha256, case_ids):
        return self.rpc(
            {
                "command": "KernelReset",
                "profile_sha256": profile_sha256,
                "case_ids": list(case_ids),
            }
        )

    def kernel_advance(self, profile_sha256, observations):
        return self.rpc(
            {
                "command": "KernelAdvance",
                "profile_sha256": profile_sha256,
                "observations": observations,
            }
        )

    def open(self, case, seed, profile_sha256, *, resume=False):
        request = {"case": case, "seed": int(seed), "profile_sha256": profile_sha256}
        result = self.rpc(
            {"command": "Resume" if resume else "Open", "request": request}
        )
        self.current = dict(
            request,
            step=result["status"]["step"],
            checkpoint=result["status"]["checkpoint"],
        )
        return result

    def tick(self, values, *, evidence_digest=None, event_id=None):
        if self.current is None:
            raise ValueError("Open a durable native owner first")
        step = self.current["step"] + 1
        observation = {
            "event_id": event_id or f"{self.current['case']}.event.{step}",
            "step": step,
            "checkpoint": self.current["checkpoint"],
            "features": values,
            "evidence_digest": evidence_digest
            or digest(
                {
                    "case": self.current["case"],
                    "seed": self.current["seed"],
                    "step": step,
                    "features": values,
                }
            ),
        }
        result = self.rpc({"command": "Tick", "observation": observation})
        self.current.update(step=result["step"], checkpoint=result["checkpoint_after"])
        return result

    def close_owner(self):
        result = self.rpc({"command": "Close"})
        self.current = None
        return result

    def close(self):
        if self.closed_receipt is not None:
            return self.closed_receipt
        if self.current is not None:
            self.close_owner()
        self.process.stdin.close()
        deadline = time.monotonic() + 30
        while True:
            pid, status, usage = os.wait4(self.process.pid, os.WNOHANG)
            if pid:
                self.process.returncode = os.waitstatus_to_exitcode(status)
                break
            if time.monotonic() > deadline:
                raise TimeoutError("Native host did not exit after input closed")
            time.sleep(0.001)
        self.process.stdout.close()
        self.stderr.close()
        counters = dict(self.counters)
        counters["total_native_kernel_calls"] = (
            counters["actual_kernel_calls"]
            + counters["original_journal_replay_steps"]
            + counters["event_validation_kernel_steps"]
        )
        counters["total_native_ndu_calls"] = (
            counters["actual_ndu_calls"] + counters["event_validation_ndu_calls"]
        )
        self.closed_receipt = {
            "schema": "hepta.continuous-boundary.native-process-cost.v1",
            "identity": self.identity,
            "counters": counters,
            "wall_ns": time.perf_counter_ns() - self.start_ns,
            "child_cpu_seconds": usage.ru_utime + usage.ru_stime,
            "child_max_rss_kib": usage.ru_maxrss,
            "cpu_scope": "this exact native child PID from wait4",
            "exit_code": self.process.returncode,
            "hardware_energy_measured": False,
        }
        return self.closed_receipt

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
