"""Frozen ACK-only information boundary and durable pilot accounting."""

from contextlib import contextmanager
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import random
import sys
import time


VERSION = "verify1-mlx-ack-pilot-v1"
FAULTS = ("clean", "stale_read", "missing_receipt", "semantic_error", "partial_success", "common_misjudgment")
ARMS = ("single", "repeat_two", "roles_two", "readout_heads_two", "bases_two", "constant_prior", "fixed_check")
EVENT = "goal_value_error_at_step3_without_optional_interruption"
PHASE1 = {
    "runtime": "af8b6cf4ed31cb6024c536771f056c5a3481902e011990ab70d43b8e961079a4",
    "contracts": "60a38923c46e3df3ad4ec357cbe0287062986e84aa8123267b5ef2954062730d",
    "metrics": "3e0a9a996ad62a0feae24a9905c7885352917b195146564b04ac6b15771b302d",
}
MODELS = {
    "qwen": {"repo": "Qwen/Qwen3-0.6B", "revision": "c1899de289a04d12100db370d81485cdf75e47ca", "config_sha256": "660db3b73d788119c04535e48cf9be5f55bc3100841a718637ae695b442f27dd"},
    "smol": {"repo": "HuggingFaceTB/SmolLM2-360M-Instruct", "revision": "a10cc1512eabd3dde888204e902eca88bddb4951", "config_sha256": "224f72354f10d617a359cc82ad15a3c96e866b9b2ffadb81997eeea9e88e22ee"},
}
ROLES = {
    "neutral": "Estimate the error risk from the supplied observations.",
    "auditor": "Audit what the supplied acknowledgements establish about correctness.",
    "skeptic": "Examine the limits of the supplied evidence before estimating error risk.",
}
LIMITS = {"assessments": 900, "forward_passes": 1800, "input_tokens": 600000, "prompt_tokens": 512, "elapsed_seconds": 1800}
DECODER = {"kind": "teacher_forced_candidate_likelihood", "candidates": ["YES", "NO"], "sampling": False, "temperature": None, "generated_tokens": 0}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def file_sha(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def load_phase1(root):
    modules = {}
    for name, expected in PHASE1.items():
        path = Path(root).resolve() / (name + ".py")
        if file_sha(path) != expected:
            raise ValueError("frozen dependency digest mismatch: " + name)
        module_name = "verify1_pilot_frozen_" + name
        spec = importlib.util.spec_from_file_location(module_name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        modules[name] = module
    return modules


def public_view(acks):
    if type(acks) is not list or len(acks) > 3 or any(type(value) is not bool for value in acks):
        raise ValueError("only a bounded list of acknowledgement booleans is public")
    return {"version": "ack-only-v1", "tick": len(acks), "acks": list(acks)}


def messages(view, role):
    if type(view) is not dict or set(view) != {"version", "tick", "acks"} or view != public_view(view["acks"]) or type(view["tick"]) is not int:
        raise ValueError("unregistered model-visible fields")
    if role not in ROLES:
        raise ValueError("unknown role")
    return [{"role": "user", "content": (
        ROLES[role] + "\nA fixed task has three planned operations: write the left target, write the right target, then finish. "
        "A YES means the actual stored values will differ from the intended targets after all three operations complete without interruption. "
        "A NO means both values will match. An acknowledgement confirms only that a response arrived; it is not a readback of values. "
        "You receive only the completed step count and acknowledgement booleans, not stored values. "
        "Answer YES or NO.\nObservation: " + canonical(view)
    )}]


def cases(split, groups=2):
    if split not in ("train", "calibration", "confirmation") or groups != 2:
        raise ValueError("the pilot freezes exactly two groups per split")
    offset = {"train": 0, "calibration": 10000, "confirmation": 20000}[split]
    result = []
    for group in range(groups):
        for fault in FAULTS:
            identifier = digest({"split": split, "group": group, "fault": fault})[:24]
            result.append({"split": split, "source_group": f"{split}/synthetic-template/{group}", "fault": fault,
                           "goal": {"task_id": identifier, "left": offset + 100 + group, "right": offset + 200 + group}})
    random.Random(771 + offset).shuffle(result)
    return result


def frozen_plan():
    sources = {path.name: file_sha(path) for path in sorted(Path(__file__).parent.glob("*.py"))}
    return {
        "version": VERSION, "source_sha256": sources, "source_bytes": {path.name: path.stat().st_size for path in sorted(Path(__file__).parent.glob("*.py"))}, "phase1_sha256": PHASE1, "models": MODELS,
        "cases": {split: cases(split) for split in ("train", "calibration", "confirmation")},
        "arms": ARMS, "roles": ROLES, "limits": LIMITS, "decoder": DECODER,
        "event": EVENT, "public_view": "tick and ACK booleans only; no identity, goal, fault, oracle, latency or database",
        "primary_voters": 2, "single_voters": 1, "diagnostic_only": ["skeptic", "head_2"],
        "backend_check": "one neutral score per base and one Qwen feature forward, retained and charged before training",
        "aggregation": "arithmetic mean score; individual votes at score>=0.5; ties do not assert independence",
        "optional_steps": [2, 3], "optional_cost": 0.2, "optional_budget": 0.4, "error_loss": 1.0,
        "check_cost_units": "declared decision-loss units; separate from measured wall time", "elapsed_limit_is_cooperative": True,
        "mandatory_check": "separate reserved terminal SQLite readback, regardless of model score",
        "head_training": {"kind": "frozen_feature_logistic_readout", "seeds": [17, 29, 43], "epochs": 250, "step_size": 0.05, "l2": 0.01, "source": "train only", "views": [0, 2, 3], "bootstrap_unit": "trajectory within training only"},
        "calibration": "diagnostics on calibration split only; no fitted calibration map or confirmation tuning",
        "interventions": [{"name": "risk_low", "risk": 0.01, "cost": 0.4}, {"name": "risk_high", "risk": 0.9, "cost": 0.4}, {"name": "cost_low", "risk": 0.4, "cost": 0.1}, {"name": "cost_high", "risk": 0.4, "cost": 0.8}],
        "intervention_scope": "one confirmation source group, actual step2 policy override, budget1; model/evidence unchanged",
        "qualification": "controlled synthetic pilot; shared templates are not independent natural tasks; no trajectory probability certificate; production and scientific generalization HOLD",
    }


class Journal:
    """Create-only attempt log. Failed operations and consumed budgets persist."""

    def __init__(self, directory, plan):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=False)
        self.started = time.monotonic()
        self.serial = 0
        self.counters = {"assessments": 0, "forward_passes": 0, "input_tokens": 0}
        self.write("plan.json", plan)

    def write(self, name, value):
        with (self.directory / name).open("x", encoding="utf-8") as stream:
            stream.write(canonical(value) + "\n")
            stream.flush()
            os.fsync(stream.fileno())

    def append(self, name, value):
        with (self.directory / name).open("a", encoding="utf-8") as stream:
            stream.write(canonical(value) + "\n")
            stream.flush()
            os.fsync(stream.fileno())

    def consume(self, **increments):
        if time.monotonic() - self.started > LIMITS["elapsed_seconds"]:
            raise RuntimeError("pilot elapsed-time budget exhausted")
        if any(type(v) is not int or v < 0 or k not in self.counters for k, v in increments.items()):
            raise ValueError("invalid cost increment")
        if any(self.counters[k] + v > LIMITS[k] for k, v in increments.items()):
            raise RuntimeError("pilot inference budget exhausted")
        for key, value in increments.items():
            self.counters[key] += value

    @contextmanager
    def operation(self, kind, context):
        self.serial += 1
        receipt = {"operation_id": f"op/{self.serial}", "kind": kind, "context": context, "started_unix_ns": time.time_ns()}
        self.append("attempts.jsonl", {**receipt, "status": "started"})
        wall, cpu = time.perf_counter_ns(), time.process_time_ns()
        status = "completed"
        try:
            yield receipt
        except BaseException as error:
            status = "cancelled" if isinstance(error, KeyboardInterrupt) else "failed"
            receipt["failure"] = {"type": type(error).__name__, "message": str(error)}
            raise
        finally:
            receipt.update(status=status, wall_ns=time.perf_counter_ns() - wall,
                           cpu_ns=time.process_time_ns() - cpu, energy_joules=None,
                           counters=dict(self.counters))
            self.append("operations.jsonl", receipt)


def finite_probability(value):
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError("invalid probability-like score")
    return float(value)
