"""Small-CPU, separately identified history/delay/Call component benchmark.

Run from the repository root with -m. A new output directory is mandatory.
This measures finite-state retention of an input intervention, not task memory
capacity, training speedup, or an exact deterministic-refractory process.
"""

import argparse
from dataclasses import asdict, fields, replace
import hashlib
import json
import math
from pathlib import Path
import platform
import re
import statistics
import sys
import time

import torch

from qualification.hcsn.tensor import HXParams, prepare_hx_equity, prepared_hx_equity
from qualification.hcsn_adaptive.batched_flow import BatchedFlow, FlowConfig
from .call_adapters import FrozenHXCurve, financial_parameters, hx_active_feature
from .call_adapters import hx_curve, policy_call, replace_call


BASE = "0cee57ca617e0324e2df8e9447a2c075a6c76952"
FROZEN = {"qualification/hcsn/tensor.py": "093d206e96cce71d21fa25c3335178888dedf387",
          "qualification/hcsn/reference.py": "34dbca501eb633788845be7ab0c128ecba1d1320",
          "qualification/hcsn_training/population_generator.py": "fc0322aa90a51c4c5a491d30dc8d1bd2dd7a0957"}
SEED, BATCH, CHECKPOINTS, STAGES = 1729, 4, (32, 128, 512), (1, 2, 4, 8)


def deadline_check(deadline):
    if time.monotonic() >= deadline:
        raise TimeoutError("declared wall-clock budget exhausted")


def source_identity():
    root = Path(__file__).resolve().parents[2]
    paths = set(FROZEN) | {"qualification/hcsn_adaptive/batched_flow.py"}
    paths |= {str(p.relative_to(root)) for p in Path(__file__).parent.glob("*.py")}
    records = {}
    for name in sorted(paths):
        content = (root/name).read_bytes()
        blob = hashlib.sha1(b"blob "+str(len(content)).encode()+b"\0"+content).hexdigest()
        if name in FROZEN and blob != FROZEN[name]:
            raise ValueError(f"baseline source mismatch: {name}")
        records[name] = {"sha256": hashlib.sha256(content).hexdigest(), "git_blob": blob}
    return records


def make_model(stages, dtype):
    torch.manual_seed(SEED)
    return BatchedFlow(FlowConfig(input_size=3, stages=stages, upper_mode="reflecting",
                                  transport_precision="float64")).to(dtype=dtype)


def observations(step, dtype):
    group = torch.arange(BATCH, dtype=dtype)//2
    value = torch.stack((torch.sin(.13*step+.4*group), torch.cos(.07*step-.2*group),
                         .5*torch.sin(.11*step+group)), -1)
    if step == 0:
        value[1::2, 0] += 1.0
        value[1::2, 1] -= .5
    return value


def delay_law(stages, refractory, draws=8192):
    rate = stages/refractory
    transient = -rate*torch.eye(stages, dtype=torch.float64)
    if stages > 1:
        transient += torch.diag(torch.full((stages-1,), rate, dtype=torch.float64), diagonal=1)
    m1 = torch.linalg.solve(-transient, torch.ones(stages, dtype=torch.float64))
    m2 = 2*torch.linalg.solve(-transient, m1)
    mean, variance = float(m1[0]), float(m2[0]-m1[0]**2)
    if not math.isclose(mean, refractory, rel_tol=1e-12) or not math.isclose(
            variance, refractory**2/stages, rel_tol=1e-12):
        raise AssertionError("phase-generator delay moments disagree with Erlang law")
    rng = torch.Generator().manual_seed(SEED+stages)
    samples = -torch.log1p(-torch.rand(draws, stages, generator=rng,
                                     dtype=torch.float64)).sum(-1)/rate
    cdf = lambda t: 1-math.exp(-rate*t)*sum((rate*t)**k/math.factorial(k) for k in range(stages))
    return {"stages": stages, "mean": mean, "variance": variance,
            "coefficient_of_variation": math.sqrt(variance)/mean,
            "probability_before_half_mean": cdf(refractory/2), "cdf_at_mean": cdf(refractory),
            "sample_count": draws, "sample_seed": SEED+stages,
            "sample_mean": float(samples.mean()), "sample_variance": float(samples.var(unbiased=False)),
            "sample_relative_absolute_delay_error": float((samples-refractory).abs().mean()/refractory),
            "strict_minimum_delay": False, "deterministic_delay": False}


def history_case(stages, dtype, emit, deadline):
    model = make_model(stages, dtype)
    state = model.initial_state(BATCH)
    initial_bytes = state.tensor_bytes()
    expected_bytes = (BATCH*(1+model.config.content_size)*(model.config.bins+stages+1)+BATCH)*8
    if initial_bytes != expected_bytes:
        raise AssertionError("state tensor payload disagrees with declared shape/precision")
    max_mass = max_content_balance = max_content_excess = step_wall = step_cpu = 0.0
    min_probability, max_bytes = 1.0, initial_bytes
    total_events = torch.zeros(BATCH, dtype=torch.float64)
    start_wall, start_cpu = time.perf_counter(), time.process_time()
    with torch.no_grad():
        for step in range(max(CHECKPOINTS)):
            deadline_check(deadline)
            inputs = observations(step, dtype)
            w, c = time.perf_counter(), time.process_time()
            output, state, diag = model.step(inputs, state)
            step_wall += time.perf_counter()-w
            step_cpu += time.process_time()-c
            p = state.density[:, 0]
            total_events += output[:, 0].double()
            max_mass = max(max_mass, float(diag["mass_error"].abs().max()))
            max_content_balance = max(max_content_balance, float(diag["content_balance_error"].abs().max()))
            max_content_excess = max(max_content_excess, float((state.density[:, 1:].abs()-p[:, None]).max()))
            min_probability = min(min_probability, float(p.min()))
            max_bytes = max(max_bytes, state.tensor_bytes())
            if state.tensor_bytes() != initial_bytes:
                raise AssertionError("dynamic tensor payload grew with elapsed history")
            if step+1 in CHECKPOINTS:
                if state.time_micros != (step+1)*round(model.config.dt*1_000_000):
                    raise AssertionError("integer physical clock disagrees with elapsed intervals")
                emit({"kind": "history_checkpoint", "stages": stages, "input_dtype": str(dtype),
                      "transport_dtype": str(state.density.dtype), "config": asdict(model.config),
                      "steps": step+1, "time_micros": state.time_micros,
                      "state_bytes_initial": initial_bytes, "state_bytes_max": max_bytes,
                      "state_bytes_final": state.tensor_bytes(), "expected_state_bytes": expected_bytes,
                      "max_mass_error": max_mass, "max_content_balance_error": max_content_balance,
                      "max_content_excess": max_content_excess, "minimum_probability": min_probability,
                      "end_active_mass": p[:, :model.config.bins].sum(-1).tolist(),
                      "end_phase_mass": p[:, model.config.bins:-1].sum(-1).tolist(),
                      "end_escape_mass": p[:, -1].tolist(), "total_events": total_events.tolist(),
                      "intervention_probability_l1": (p[1::2]-p[::2]).abs().sum(-1).tolist(),
                      "intervention_content_l1": (state.density[1::2, 1:]-state.density[::2, 1:]).abs().sum((-1, -2)).tolist(),
                      "intervention_output_l2": torch.linalg.vector_norm(output[1::2]-output[::2], dim=-1).tolist(),
                      "step_wall_seconds": step_wall, "step_cpu_seconds": step_cpu,
                      "host_wall_seconds": time.perf_counter()-start_wall,
                      "host_cpu_seconds": time.process_time()-start_cpu,
                      "inference_no_grad": True, "stored_output_steps": 1})


def measure(name, operation, repeats, emit, deadline):
    for _ in range(2):
        deadline_check(deadline)
        operation()
    wall, cpu = [], []
    for _ in range(repeats):
        deadline_check(deadline)
        w, c = time.perf_counter(), time.process_time()
        operation()
        wall.append(time.perf_counter()-w)
        cpu.append(time.process_time()-c)
    emit({"kind": "call_component_timing", "component": name, "repeats": repeats, "warmup": 2,
          "median_wall_seconds": statistics.median(wall), "median_cpu_seconds": statistics.median(cpu),
          "min_wall_seconds": min(wall), "max_wall_seconds": max(wall),
          "total_measured_wall_seconds": sum(wall), "total_measured_cpu_seconds": sum(cpu)})


def hx_backward(method, model, state):
    nodes = model.centers.detach().clone().requires_grad_()
    p = state.density[:, 0].detach().clone().requires_grad_()
    par = financial_parameters(HXParams(), nodes, gradient=True)
    value = (p[:, :model.config.bins]*hx_curve(nodes, par, method=method)).sum(-1)
    derivatives = torch.autograd.grad(value.sum(), (nodes, p, *[getattr(par, f.name) for f in fields(par)]))
    if not all(bool(torch.isfinite(t).all()) for t in (value, *derivatives)):
        raise FloatingPointError("nonfinite default-domain HX gradients")
    return value.detach(), tuple(t.detach() for t in derivatives)


def call_study(emit, repeats, deadline):
    model = make_model(4, torch.float64)
    with torch.no_grad():
        features, state, diag = model.step(observations(0, torch.float64))
        drift = diag["drift"]
        generator, event, _ = model._generator(drift)
        finite = policy_call(model, state, drift)
        direct = hx_active_feature(model, state)
        prepared = hx_active_feature(model, state, method="prepared")
        cache = FrozenHXCurve.build(model.centers)
        cached = cache.apply(model, state)
        for left, right in ((finite, features[:, -1]), (direct, prepared), (direct, cached)):
            torch.testing.assert_close(left, right, rtol=1e-10, atol=1e-11)
        replaced = replace_call(features, direct)
        torch.testing.assert_close(replaced[:, :-1], features[:, :-1], rtol=0, atol=0)
        context = prepare_hx_equity(HXParams(), like=model.centers)
        emit({"kind": "call_semantics", "config": asdict(model.config), "batch": BATCH,
              "finite_policy_call": finite.tolist(), "hx_active_feature": direct.tolist(),
              "hx_financial_boundary": float(context.boundary), "hx_parameters": asdict(HXParams()),
              "hx_coordinate": "V_HX=b_HX*exp(margin)", "hx_phase_escape_contribution": 0,
              "same_objective_as_finite_policy": False, "same_function_direct_prepared_cached": True,
              "maximum_direct_prepared_error": float((direct-prepared).abs().max()),
              "cached_curve_payload_bytes": sum(t.numel()*t.element_size() for t in (cache.nodes, cache.values)),
              "functional_mask_or_posthoc_substitution_skips_original_call": False,
              "timing_scope": "CPU operator components; no end-to-end training speedup"})
        operations = {
            "finite_policy_rebuild_generator_solve_apply": lambda: policy_call(model, state, drift),
            "finite_policy_reuse_generator_solve_apply": lambda: policy_call(model, state, drift, generator_event=(generator, event)),
            "hx_direct_curve_and_apply": lambda: hx_active_feature(model, state),
            "hx_prepare_curve_and_apply": lambda: hx_active_feature(model, state, method="prepared"),
            "hx_reuse_parameter_context_evaluate_apply": lambda: (state.density[:, 0, :model.config.bins]*prepared_hx_equity(model.centers, context)/context.boundary).sum(-1),
            "hx_frozen_curve_setup": lambda: FrozenHXCurve.build(model.centers),
            "hx_frozen_curve_apply": lambda: cache.apply(model, state),
            "posthoc_drop_call_only": lambda: replace_call(features, features.new_zeros(BATCH))}
        for name, operation in operations.items():
            measure(name, operation, repeats, emit, deadline)
    direct_value, direct_grads = hx_backward("direct", model, state)
    prepared_value, prepared_grads = hx_backward("prepared", model, state)
    for left, right in ((direct_value, prepared_value), *zip(direct_grads, prepared_grads)):
        torch.testing.assert_close(left, right, rtol=1e-8, atol=1e-9)
    emit({"kind": "hx_gradient_parity", "gradient_targets": ["margin_nodes", "ambient_probability", *asdict(HXParams())],
          "max_absolute_gradient_error": max(float((a-b).abs().max()) for a, b in zip(direct_grads, prepared_grads)),
          "parameters_and_graph_rebuilt_per_backward": True})
    for method in ("direct", "prepared"):
        measure("hx_"+method+"_fresh_forward_backward", lambda: hx_backward(method, model, state), repeats, emit, deadline)
    def policy_backward():
        p = state.density[:, :1].detach().clone().requires_grad_()
        variable_drift = drift.detach().clone().requires_grad_()
        variable_state = replace(state, density=torch.cat((p, state.density[:, 1:]), 1))
        value = policy_call(model, variable_state, variable_drift)
        return torch.autograd.grad(value.sum(), (p, variable_drift))
    measure("finite_policy_fresh_forward_backward", policy_backward, repeats, emit, deadline)
    try:
        from qualification.hcsn import reference
    except ImportError as exc:
        emit({"kind": "hx_independent_oracle", "status": "unavailable", "reason": str(exc)})
    else:
        deadline_check(deadline)
        par = reference.HXParams()
        expected = torch.as_tensor(reference.hx_equity(model.centers.numpy(), par)/reference.hx_boundary(par))
        actual = hx_curve(model.centers).detach()
        torch.testing.assert_close(actual, expected, rtol=1e-8, atol=1e-9)
        emit({"kind": "hx_independent_oracle", "status": "passed",
              "max_absolute_error": float((actual-expected).abs().max()), "scope": "default parameters, six declared margin nodes"})


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-seconds", type=float, default=90.0)
    parser.add_argument("--repeats", type=int, default=12)
    args = parser.parse_args(argv)
    if (not re.fullmatch(r"[a-z0-9][a-z0-9_-]{1,95}", args.experiment_id)
            or not math.isfinite(args.max_seconds) or not 1 <= args.max_seconds <= 600
            or not 1 <= args.repeats <= 100):
        parser.error("use a new plain experiment ID, 1..600 second budget and 1..100 repeats")
    args.output.mkdir(parents=True, exist_ok=False)
    torch.set_num_threads(1)
    records, status, error = [], "passed", None
    start_wall, start_cpu = time.monotonic(), time.process_time()
    with (args.output/"events.jsonl").open("x", encoding="utf-8") as stream:
        def emit(record):
            stream.write(json.dumps(record, allow_nan=False, sort_keys=True)+"\n")
            stream.flush()
            records.append(record)
        try:
            emit({"kind": "manifest", "experiment_id": args.experiment_id, "baseline": BASE,
                  "sources": source_identity(), "torch": torch.__version__, "python": sys.version,
                  "platform": platform.platform(), "torch_threads": torch.get_num_threads(),
                  "seed": SEED, "max_wall_seconds": args.max_seconds, "repeats": args.repeats,
                  "profiles": ["FP64", "FP32 weights/outputs with FP64 transport/state"],
                  "checkpoints": CHECKPOINTS, "stages": STAGES, "batch": BATCH,
                  "history_intervention": "odd sample first observation += [1,-.5,0]; paired future inputs identical",
                  "stored_history_steps": 0, "task_capacity_claim": False})
            deadline = start_wall+args.max_seconds
            for stages in STAGES:
                emit({"kind": "delay_law", **delay_law(stages, .2)})
                for dtype in (torch.float64, torch.float32):
                    history_case(stages, dtype, emit, deadline)
            call_study(emit, args.repeats, deadline)
            deadline_check(deadline)
        except Exception as exc:
            status = "budget_exhausted" if isinstance(exc, TimeoutError) else "failed"
            error = {"type": type(exc).__name__, "message": str(exc)}
            emit({"kind": "failure", "status": status, "error": error})
    summary = {"experiment_id": args.experiment_id, "status": status, "error": error,
               "total_wall_seconds": time.monotonic()-start_wall,
               "total_cpu_seconds": time.process_time()-start_cpu, "records": records,
               "state_payload_excludes": ["model weights", "temporary matrices", "Python/runtime", "autograd tapes"],
               "cost_comparisons_between_different_objectives_are_not_speedup_proofs": True}
    with (args.output/"summary.json").open("x", encoding="utf-8") as stream:
        json.dump(summary, stream, indent=2, allow_nan=False, sort_keys=True)
        stream.write("\n")
    print(json.dumps({"experiment_id": args.experiment_id, "status": status,
                      "summary": str(args.output/"summary.json"), "error": error}))
    return 0 if status == "passed" else 2 if status == "budget_exhausted" else 1


if __name__ == "__main__":
    raise SystemExit(main())
