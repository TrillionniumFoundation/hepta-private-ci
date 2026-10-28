"""Native JSON transport and separately observable engineering accounting."""

import hashlib
import json
from pathlib import Path
import resource
import select
import subprocess
import time


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def write(path, value):
    with Path(path).open("x") as output:
        json.dump(value, output, indent=2, sort_keys=True, allow_nan=False)
        output.write("\n")


def permit(root):
    write(
        root / "RESEARCH_PERMIT.json",
        {
            "schema": "hepta.free-boundary.local-research-permit.v1",
            "allowed_root": str(root.resolve()),
            "external_effects": False,
            "production_authority": False,
            "scope": "User-authorized local synthetic observation/outcome files only; original native authority remains DENY_ALL",
        },
    )


def encoder_proof(model_path, destination):
    model = json.loads(Path(model_path).read_text())
    q = 1 << 24
    points = 0
    for t in range(len(model["value"])):
        for i, x in enumerate(model["states"]):
            features = [i, t, round(x * q), round(t * model["dt"] * q)]
            drive = [max(0, features[2]), max(0, -features[2]), q // 4] + [0] * 7
            if any(abs(v) > 8 * q for v in features + drive):
                raise ValueError("Finite encoder domain exceeds native numeric bounds")
            points += 1
    result = {
        "schema": "hepta.free-boundary.encoder-domain-proof.v1",
        "model_sha256": sha(model_path),
        "domain_points": points,
        "confidence_target": "registered_public_encoder_domain_validity",
        "semantic_quality_qualification": False,
        "finite_domain_ece_ppm": 0,
        "finite_domain_false_acceptance_ppm": 0,
        "proof": "Prediction target is the deterministic admitted encoder drive. The host independently enumerates its complete finite domain; this is not task-success calibration.",
    }
    write(destination, result)
    return result


class Native:
    """One bounded research host process; all requests and failures are retained."""

    def __init__(self, binary, root):
        self.started = time.monotonic_ns()
        self.before_cpu = resource.getrusage(resource.RUSAGE_CHILDREN)
        self.process = subprocess.Popen(
            [str(binary), str(root)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        self.rows = []

    def call(self, request, expect_error=False):
        started = time.monotonic_ns()
        cpu = time.process_time_ns()
        self.process.stdin.write(canonical(request).decode() + "\n")
        self.process.stdin.flush()
        if not select.select([self.process.stdout], [], [], 30)[0]:
            raise TimeoutError("Native request exceeded 30-second research limit")
        line = self.process.stdout.readline()
        if not line:
            raise RuntimeError(
                "Native host closed without a receipt: " + self.process.stderr.read()
            )
        response = json.loads(line)
        self.rows.append(
            {
                "request": request,
                "response": response,
                "client_wall_ns": time.monotonic_ns() - started,
                "client_cpu_ns": time.process_time_ns() - cpu,
            }
        )
        if bool(response["ok"]) == expect_error:
            raise ValueError(f"Unexpected native disposition: {response}")
        return response.get("result", response)

    def close(self):
        self.process.stdin.close()
        code = self.process.wait(timeout=30)
        stderr = self.process.stderr.read()
        self.process.stdout.close()
        self.process.stderr.close()
        after = resource.getrusage(resource.RUSAGE_CHILDREN)
        receipt = {
            "process_wall_ns": time.monotonic_ns() - self.started,
            "child_user_cpu_seconds": after.ru_utime - self.before_cpu.ru_utime,
            "child_system_cpu_seconds": after.ru_stime - self.before_cpu.ru_stime,
            "exit_code": code,
            "stderr": stderr,
            "rpc_count": len(self.rows),
        }
        if code:
            raise RuntimeError(f"Native process failed: {receipt}")
        return receipt


def open_request(case, model, calibration, policy, expires=64):
    return {
        "case": case,
        "expires": expires,
        "model": str(Path(model).resolve()),
        "model_sha256": sha(model),
        "calibration": str(Path(calibration).resolve()),
        "calibration_sha256": sha(calibration),
        "policy": policy,
    }


def registered_starts(model, protocol):
    """Reject CLI profiles that change any registered numeric assumption."""
    if (
        model["schema"] != "hepta.free-boundary.readout.v1"
        or model["transition_kind"] != "survival_weighted_gaussian_bins"
    ):
        raise ValueError("Unregistered readout schema or transition kind")
    for field in (
        "dt",
        "mu",
        "sigma",
        "rho",
        "killing_rate",
        "payoff_cost",
        "running_cost",
    ):
        if model[field] != protocol[field]:
            raise ValueError(f"Registered model parameter changed: {field}")
    low, high, count = protocol["state_grid"]
    states = model["states"]
    if len(states) != count or len(model["value"]) - 1 != protocol["horizon"]:
        raise ValueError("Registered state count or horizon changed")
    if any(
        abs(x - (low + i * (high - low) / (count - 1))) > 1e-12
        for i, x in enumerate(states)
    ):
        raise ValueError("Registered state grid changed")
    starts = [
        min(range(len(states)), key=lambda i: abs(states[i] - x))
        for x in protocol["starts"]
    ]
    if any(abs(states[i] - x) > 1e-12 for i, x in zip(starts, protocol["starts"])):
        raise ValueError("Registered starts absent from the exact state grid")
    return starts


def uniform(seed, start_index, step):
    raw = hashlib.sha256(
        canonical(["free-boundary.noise.v1", seed, start_index, step])
    ).digest()
    integer = int.from_bytes(raw[:8], "big") >> 11
    return (integer + 0.5) / (1 << 53)


def charge(rows):
    result = {
        "rpc_count": len(rows),
        "failed_requests": 0,
        "owner_ticks": 0,
        "model_calls": 0,
        "readout_bellman_terms": 0,
        "original_journal_replay_steps": 0,
        "event_validation_kernel_steps": 0,
        "event_validation_readout_calls": 0,
        "event_validation_bellman_terms": 0,
        "profile_validation_bellman_terms": 0,
        "profile_validation_readouts": 0,
        "finite_encoder_domain_checks": 0,
        "physical_rpc_micros": 0,
        "native_tick_micros": 0,
        "model_latency_micros": 0,
        "journal_bytes_written": 0,
        "peak_transient_allocation_bytes": 0,
    }
    for row in rows:
        envelope = row["response"]
        result["physical_rpc_micros"] += envelope["physical_rpc_micros"]
        if not envelope["ok"]:
            result["failed_requests"] += 1
            continue
        value = envelope["result"]
        for field in (
            "original_journal_replay_steps",
            "event_validation_kernel_steps",
            "event_validation_readout_calls",
            "event_validation_bellman_terms",
            "profile_validation_bellman_terms",
            "profile_validation_readouts",
            "finite_encoder_domain_checks",
        ):
            result[field] += value.get(field, 0)
        if value.get("native_transition_executed"):
            result["owner_ticks"] += 1
            result["model_calls"] += value["actual_model_calls"]
            result["readout_bellman_terms"] += value["actual_bellman_terms"]
            result["native_tick_micros"] += value["execution_micros"]
            result["model_latency_micros"] += value["model_latency_micros"]
            result["journal_bytes_written"] += value["journal_bytes_written"]
            result["peak_transient_allocation_bytes"] = max(
                result["peak_transient_allocation_bytes"],
                value["transient_allocation_bytes"],
            )
    result["all_original_kernel_executions"] = (
        result["owner_ticks"]
        + result["original_journal_replay_steps"]
        + result["event_validation_kernel_steps"]
    )
    return result
