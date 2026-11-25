"""Inference-only cached matrix plans for an explicitly frozen local law.

No training source is changed. The complete population, phase and signed-mark
state still advances at every observation, including input writes and old-message
coupling. Only law-dependent _flow operators are reused. This is not a compiler
for input-driven laws, a banded implementation, or a reusable backward graph.
"""

import time
_ENTRY = time.perf_counter()
import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import resource
import statistics
import sys
import torch
from .model import ModelConfig, SmallHCSN

_FIELDS = ("density", "boundary", "drift", "cost", "message")


class FixedLawHCSN(SmallHCSN):
    """Reject changing laws or enabled autograd instead of using a stale plan."""
    def __init__(self, config=None):
        config = config or ModelConfig(slow_every=10**9, backend="dense")
        if config.backend != "dense" or config.slow_every < 10**9:
            raise ValueError("cached inference requires dense backend and an explicitly frozen control schedule")
        super().__init__(config)
        self.clear_plan()

    def clear_plan(self):
        self._plan = None
        self.cache_hits, self.plan_builds, self.plan_seconds, self.plan_cpu_seconds = 0, 0, 0., 0.

    def _build_plan(self, generator, event, boundary, cost):
        started = time.perf_counter()
        started_cpu = time.process_time()
        c, size = self.config, generator.shape[-1]
        active = torch.cat((event.new_ones(c.bins), event.new_zeros(c.stages+1)))
        rewards = torch.stack((event, active.expand_as(event)), -1)
        augmented = torch.cat((torch.cat((generator, rewards), -1),
                               event.new_zeros(*event.shape[:-1], 2, size+2)), -2)
        action = torch.matrix_exp(augmented*c.dt)
        destination = torch.eye(size, dtype=event.dtype, device=event.device)[c.bins].clone()
        killed = generator-event[..., None]*destination
        first = torch.cat((torch.cat((killed, event[..., None]), -1),
                           event.new_zeros(*event.shape[:-1], 1, size+1)), -2)
        terminal = event.new_zeros(*event.shape[:-1], size+1, 1)
        terminal[..., -1, 0] = 1
        first_prob = (torch.matrix_exp(first*c.dt) @ terminal)[..., :size, 0].clone()
        _, centers = self._geometry(event)
        reward = torch.cat((c.gain*(boundary[..., None]+centers)-c.maintenance,
                            event.new_zeros(*event.shape[:-1], c.stages+1)), -1)-cost[..., None]*event
        value = torch.linalg.solve(c.discount*torch.eye(size, dtype=event.dtype, device=event.device)
                                   -generator, reward[..., None])[..., 0]
        self._plan = {"config": c, "law": tuple(t.detach().clone() for t in (generator, event, boundary, cost)),
            "augmented_action": action, "transition": action[..., :size, :size],
            "integrated_event_and_occupation_rewards": action[..., :size, size:],
            "first_hit_probability": first_prob, "value": value, "destination": destination, "centers": centers}
        self.plan_builds += 1
        self.plan_seconds += time.perf_counter()-started
        self.plan_cpu_seconds += time.process_time()-started_cpu

    def _flow(self, density, jump, generator, event, boundary, cost):
        if torch.is_grad_enabled():
            raise RuntimeError("fixed-law cache is inference-only: enter torch.no_grad or inference_mode")
        law = (generator, event, boundary, cost)
        if self._plan is None:
            self._build_plan(*law)
        else:
            same = self.config == self._plan["config"] and all(
                a.shape == b.shape and a.dtype == b.dtype and a.device == b.device and torch.equal(a, b)
                for a, b in zip(law, self._plan["law"]))
            if not same:
                raise ValueError("fixed-law cache mismatch; clear the plan explicitly before a new law")
            self.cache_hits += 1
        plan, c, size = self._plan, self.config, generator.shape[-1]
        padded = torch.cat((density, density.new_zeros(*density.shape[:-1], 2)), -1)
        result = padded @ plan["augmented_action"]
        next_density, increments = result[..., :size], result[..., size:]
        never_hit = density[..., 0, :]-jump[..., :1]*plan["destination"]
        risk = jump[..., 0]+(never_hit*plan["first_hit_probability"]).sum(-1)
        continuation = (next_density[..., 0, :]*plan["value"]).sum(-1)
        margin = (next_density[..., 0, :c.bins]*plan["centers"]).sum(-1)/c.extent
        return next_density, jump+increments[..., 0], continuation, risk, margin

    def plan_statistics(self):
        if self._plan is None:
            return {"plan_builds": 0, "cache_hits": 0, "plan_construction_s": 0., "plan_cpu_seconds": 0., "plan_tensor_bytes": 0}
        # transition/reward are views of action, counted exactly once here.
        tensors = [*self._plan["law"], *(self._plan[key] for key in
                   ("augmented_action", "first_hit_probability", "value", "destination", "centers"))]
        return {"plan_builds": self.plan_builds, "cache_hits": self.cache_hits,
                "plan_construction_s": self.plan_seconds,
                "plan_cpu_seconds": self.plan_cpu_seconds,
                "plan_tensor_bytes": sum(t.numel()*t.element_size() for t in tensors),
                "cache_scope": "one exact batch and per-neuron generator/event/boundary/cost/config; no autograd graph"}


def parity(reference, candidate):
    a, f, state = reference
    b, g, other = candidate
    tensors = (a, f, b, g, *(getattr(state, name) for name in _FIELDS), *(getattr(other, name) for name in _FIELDS))
    if not all(bool(torch.isfinite(t).all()) for t in tensors):
        raise FloatingPointError("nonfinite output or complete state in cache parity check")
    errors = {"logits": float((a-b).abs().max()), "features": float((f-g).abs().max()),
              **{name: float((getattr(state, name)-getattr(other, name)).abs().max()) for name in _FIELDS}}
    return {"max_absolute_error": errors, "all_outputs_and_state_finite": all(bool(torch.isfinite(t).all()) for t in tensors),
            "step_equal": state.step == other.step, "config_equal": state.config == other.config,
            "maximum_error": max(errors.values()),
            "probability_mass_error": float((other.density[..., 0, :].sum(-1)-1).abs().max())}


def tensor_digest(values):
    h = hashlib.sha256()
    for name, value in values:
        h.update(str((name, tuple(value.shape), str(value.dtype))).encode())
        h.update(value.detach().cpu().contiguous().numpy().tobytes())
    return h.hexdigest()


def one_case(width, precision, args):
    torch.manual_seed(args.seed+width)
    config = ModelConfig(neurons=width, precision=precision, slow_every=10**9, backend="dense")
    begin = time.perf_counter()
    reference = SmallHCSN(config).eval()
    cached = FixedLawHCSN(config).eval()
    cached.load_state_dict(reference.state_dict())
    construction = time.perf_counter()-begin
    x = torch.randn(args.steps, args.batch, config.input_size, dtype=reference.input_drive.weight.dtype)*.3
    margin = torch.linspace(.28, .82, width, dtype=reference.reset_absolute.dtype)[None].expand(args.batch, -1)
    reference_samples, cached_samples, reference_cpu, cached_cpu = [], [], [], []
    with torch.no_grad():
        for _ in range(args.repeats):
            begin = time.perf_counter()
            cpu = time.process_time()
            actual = reference(x, state=reference.initial_state(args.batch, margin), return_features=True)
            reference_samples.append(time.perf_counter()-begin)
            reference_cpu.append(time.process_time()-cpu)
        begin = time.perf_counter()
        cpu = time.process_time()
        cold = cached(x, state=cached.initial_state(args.batch, margin), return_features=True)
        cold_seconds = time.perf_counter()-begin
        cold_cpu = time.process_time()-cpu
        cold_stats = cached.plan_statistics()
        cold_parity = parity(actual, cold)
        for _ in range(args.repeats):
            begin = time.perf_counter()
            cpu = time.process_time()
            warm = cached(x, state=cached.initial_state(args.batch, margin), return_features=True)
            cached_samples.append(time.perf_counter()-begin)
            cached_cpu.append(time.process_time()-cpu)
        warm_parity = parity(actual, warm)
    tolerance = 3e-11 if precision == "float64" else 3e-7
    passed = all(p["maximum_error"] <= tolerance and p["all_outputs_and_state_finite"] and
                 p["step_equal"] and p["config_equal"] for p in (cold_parity, warm_parity))
    return {"neurons": width, "precision": precision, "config": asdict(config), "steps": args.steps,
            "batch": args.batch, "status": "passed" if passed else "parity_failed", "parity_absolute_tolerance": tolerance,
            "two_model_construction_s": construction, "reference_full_forward_samples_s": reference_samples,
            "reference_full_forward_median_s": statistics.median(reference_samples),
            "reference_full_forward_cpu_samples_s": reference_cpu,
            "reference_full_forward_cpu_median_s": statistics.median(reference_cpu),
            "cold_cached_full_forward_s": cold_seconds, "cold_plan": cold_stats, "cold_parity": cold_parity,
            "cold_cached_full_forward_cpu_s": cold_cpu,
            "warm_cached_full_forward_samples_s": cached_samples,
            "warm_cached_full_forward_median_s": statistics.median(cached_samples),
            "warm_cached_full_forward_cpu_samples_s": cached_cpu,
            "warm_cached_full_forward_cpu_median_s": statistics.median(cached_cpu),
            "warm_speed_ratio_reference_over_cached": statistics.median(reference_samples)/statistics.median(cached_samples),
            "warm_cpu_ratio_reference_over_cached": statistics.median(reference_cpu)/statistics.median(cached_cpu),
            "warm_parity": warm_parity, "final_plan": cached.plan_statistics(),
            "input_sha256": tensor_digest((("input", x), ("initial_margin", margin))),
            "model_state_sha256": tensor_digest(reference.state_dict().items()),
            "final_state_elements": sum(getattr(warm[2], name).numel() for name in _FIELDS)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--steps", type=int, default=64)
    parser.add_argument("--batch", type=int, default=4)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--seed", type=int, default=5117)
    parser.add_argument("--budget-seconds", type=float, default=90.)
    args = parser.parse_args()
    if (args.output.exists() or not 2 <= args.steps <= 512 or not 1 <= args.batch <= 16
            or not 1 <= args.repeats <= 5 or not 10 <= args.budget_seconds <= 105):
        parser.error("fresh output and bounded benchmark arguments required")
    torch.set_num_threads(1)
    begin_cpu = time.process_time()
    report = {"schema": "hcsn-fixed-law-inference-cache-v1", "torch": torch.__version__, "python": sys.version,
        "device": "cpu", "threads": 1, "seed": args.seed, "cases": [],
        "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "frozen_model_sha256": hashlib.sha256(Path(__file__).with_name("model.py").read_bytes()).hexdigest(),
        "timing_scope": "complete inference forward including initial state, QVI/control edge, input writes, recurrent messages, feature/readout and invariant checks",
        "remaining_work": "per-step generator construction and exact cache-key validation remain in the measured forward",
        "law_scope": "controls updated at step 0 then held; every later input still writes signed content and old-message coupling remains active",
        "not_measured": "training, BP/backward reuse, changing input-driven laws, an end-to-end multimodal model",
        "energy_joules": None, "energy_reason": "No process-attributable hardware energy counter."}
    for width in (8, 32, 64):
        for precision in ("float64", "mixed"):
            if time.perf_counter()-_ENTRY >= args.budget_seconds:
                report["cases"].append({"neurons": width, "precision": precision, "status": "budget_not_run"})
                continue
            try:
                report["cases"].append(one_case(width, precision, args))
            except (ValueError, RuntimeError, FloatingPointError) as exc:
                report["cases"].append({"neurons": width, "precision": precision, "status": "failed",
                                        "error_type": type(exc).__name__, "error": str(exc)})
    report["benchmark_body_cpu_seconds"] = time.process_time()-begin_cpu
    report["worker_cpu_through_report_seconds"] = time.process_time()
    report["worker_script_wall_seconds"] = time.perf_counter()-_ENTRY
    report["process_peak_rss_kib_linux"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as handle:
        json.dump(report, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
    print(json.dumps({"output": str(args.output), "worker_script_wall_seconds": report["worker_script_wall_seconds"],
        "cases": [{"neurons": r["neurons"], "precision": r["precision"], "status": r["status"],
                   "speed_ratio": r.get("warm_speed_ratio_reference_over_cached"),
                   "max_error": r.get("warm_parity", {}).get("maximum_error")} for r in report["cases"]]}, sort_keys=True))


if __name__ == "__main__":
    main()
