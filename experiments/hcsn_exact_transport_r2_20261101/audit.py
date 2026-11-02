"""Fixed-gate development and source-frozen confirmation for exact adapters."""

import argparse
import copy
import hashlib
import json
from pathlib import Path
import platform
import random
import statistics
import time
import traceback

import numpy as np
import scipy
import torch
from torch.nn import functional as F

from experiments.hcsn_addressed_flow_20261101 import addressed_models, data, typed_retention
from experiments.hcsn_propagation_perf_20261101 import audit as prior_audit
from . import adapter


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
PLAN = json.loads((HERE / "PROTOCOL.json").read_text())
SOURCES = [HERE / "adapter.py", HERE / "audit.py", HERE / "PROTOCOL.json",
           Path(typed_retention.__file__), *prior_audit.DEPENDENCIES]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    with Path(path).open("x") as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write("\n")


def journal(path, value):
    with Path(path).open("a") as stream:
        stream.write(json.dumps(value, allow_nan=False) + "\n")


def sources():
    return {str(p.relative_to(ROOT)): digest(p) for p in SOURCES}


def checkpoint(task):
    return prior_audit.checkpoint(task)


def model_for(task):
    model = addressed_models.AddressedModel("flow").eval()
    model.load_state_dict(torch.load(checkpoint(task), weights_only=True, map_location="cpu"))
    return model


def numerical(model, candidate, arrays):
    outputs, gradients, diagnostics = {}, {}, {}
    for name, call in (("dense", model), ("adapter", candidate)):
        x = torch.from_numpy(arrays["x"]).clone().requires_grad_()
        dt = torch.from_numpy(arrays["dt"]).clone().requires_grad_()
        observed, labels = torch.from_numpy(arrays["observed"]), torch.from_numpy(arrays["y"])
        model.zero_grad(set_to_none=True)
        result = call(x, dt, observed)
        F.cross_entropy(result.flatten(0, 1), labels.flatten()).backward()
        outputs[name] = result.detach().numpy()
        gradients[name] = {key: p.grad.detach().numpy().copy() for key, p in model.named_parameters()
                           if p.grad is not None}
        gradients[name]["INPUT/x"] = x.grad.detach().numpy().copy()
        gradients[name]["INPUT/dt"] = dt.grad.detach().numpy().copy()
        diagnostics[name] = copy.deepcopy(model.last_diagnostics)
    keys_equal = set(gradients["dense"]) == set(gradients["adapter"])
    errors = {key: float(np.max(np.abs(value - gradients["adapter"][key])))
              for key, value in gradients["dense"].items()} if keys_equal else {}
    output_error = float(np.max(np.abs(outputs["dense"] - outputs["adapter"])))
    parameter_error = max((v for k, v in errors.items() if not k.startswith("INPUT/")), default=0)
    scored = arrays["y"] >= 0
    argmax_equal = bool(np.array_equal(outputs["dense"].argmax(-1)[scored],
                                      outputs["adapter"].argmax(-1)[scored]))
    passed = (keys_equal and output_error <= PLAN["max_output_absolute_error"]
              and parameter_error <= PLAN["max_parameter_gradient_absolute_error"]
              and errors.get("INPUT/x", float("inf")) <= PLAN["max_input_gradient_absolute_error"]
              and errors.get("INPUT/dt", float("inf")) <= PLAN["max_time_gradient_absolute_error"]
              and argmax_equal and diagnostics["dense"] == diagnostics["adapter"])
    return dict(passed=passed, max_output_error=output_error, max_parameter_gradient_error=parameter_error,
                gradient_errors=errors, gradient_keys_equal=keys_equal, scored_argmax_identical=argmax_equal,
                all_argmax_identical=bool(np.array_equal(outputs["dense"].argmax(-1), outputs["adapter"].argmax(-1))),
                diagnostics_identical=diagnostics["dense"] == diagnostics["adapter"])


def engineering(task, backend):
    model = model_for(task)
    candidate = adapter.ExactAddressedAdapter(model, backend)
    checks = []
    for condition in ("missing", "all_unobserved", "zero_time", "no_marks", "unnormalized_occupancy", "resample"):
        arrays = data.batch(task, 3, PLAN["development_seed"] + 17, "dev",
                            condition if condition in ("missing", "resample") else "base")
        model.intervention = "no_marks" if condition == "no_marks" else None
        model.normalize_occupancy = condition != "unnormalized_occupancy"
        if condition == "all_unobserved":
            arrays["observed"][:] = False
        if condition == "zero_time":
            arrays["dt"][:] = 0
        row = numerical(model, candidate, arrays)
        checks.append(dict(name=condition, **row))
    typed = typed_retention.install(model_for(task))
    typed_candidate = adapter.ExactAddressedAdapter(typed, backend)
    checks.append(dict(name="typed_eligibility", **numerical(typed, typed_candidate,
                  data.batch(task, 3, PLAN["development_seed"] + 31, "dev", "long_tokens_128"))))
    model = model_for(task)
    candidate = adapter.ExactAddressedAdapter(model, backend)
    checks.append(dict(name="live_parameter_identity", passed=all(a is b for a, b in
                      zip(model.parameters(), candidate.parameters(), strict=True))))
    arrays = data.batch(task, 3, PLAN["development_seed"] + 29, "dev")
    x, dt, observed = [torch.from_numpy(arrays[k]) for k in ("x", "dt", "observed")]
    with torch.no_grad():
        full = candidate(x, dt, observed)
        cut = x.shape[1] // 2
        prefix = candidate(x[:, :cut], dt[:, :cut], observed[:, :cut])
        error = float((prefix - full[:, :cut]).abs().max())
        checks.append(dict(name="prefix_causality", passed=error <= PLAN["max_output_absolute_error"], error=error))
    invalids = [dict(name="invalid_negative_time", x=x, dt=-dt, observed=observed),
                dict(name="invalid_nonfinite_input", x=x * float("nan"), dt=dt, observed=observed),
                dict(name="invalid_nonboolean_observation", x=x, dt=dt, observed=observed.float()),
                dict(name="invalid_empty_sequence", x=x[:, :0], dt=dt[:, :0], observed=observed[:, :0])]
    for case in invalids:
        names = []
        for call in (model, candidate):
            try:
                call(case["x"], case["dt"], case["observed"])
                names.append("accepted")
            except Exception as error:
                names.append(type(error).__name__)
        checks.append(dict(name=case["name"], observed=names, passed=names == ["ValueError", "ValueError"]))
    unsupported = model_for(task)
    unsupported.read = torch.nn.Sequential(torch.nn.Linear(97, 64), torch.nn.Dropout(.1), torch.nn.Linear(64, 8))
    try:
        adapter.ExactAddressedAdapter(unsupported, backend)
        checks.append(dict(name="unsupported_stateful_decoder", passed=False))
    except ValueError:
        checks.append(dict(name="unsupported_stateful_decoder", passed=True))
    hooked = model_for(task)
    handle = hooked.read.register_forward_hook(lambda module, inputs, output: output)
    try:
        adapter.ExactAddressedAdapter(hooked, backend)
        checks.append(dict(name="unsupported_original_hooks", passed=False))
    except ValueError:
        checks.append(dict(name="unsupported_original_hooks", passed=True))
    finally:
        handle.remove()
    # A real optimizer update is checked on separate copies, never on the
    # fixed timing candidates or their source checkpoints.
    reference, updated = model_for(task), model_for(task)
    wrapped = adapter.ExactAddressedAdapter(updated, backend)
    labels = torch.from_numpy(arrays["y"])
    for call, physical_model in ((reference, reference), (wrapped, updated)):
        optimizer = torch.optim.SGD(physical_model.parameters(), lr=.01)
        optimizer.zero_grad(set_to_none=True)
        F.cross_entropy(call(x, dt, observed).flatten(0, 1), labels.flatten()).backward()
        optimizer.step()
    update_error = max(float((a - b).abs().max()) for a, b in
                       zip(reference.parameters(), updated.parameters(), strict=True))
    checks.append(dict(name="real_sgd_update", error=update_error, passed=update_error <= 2e-6))
    return checks


def benchmark(calls, model, arrays, backward, seed, phase):
    x, dt, observed, labels = [torch.from_numpy(arrays[k]) for k in ("x", "dt", "observed", "y")]
    samples, warmups, order = {k: [] for k in calls}, {k: [] for k in calls}, []
    rng = random.Random(seed)
    warmup_count, repeats = PLAN[phase + "_warmups"], PLAN[phase + "_repeats"]
    for iteration in range(warmup_count + repeats):
        names = rng.sample(list(calls), len(calls))
        order.append(names)
        for name in names:
            model.zero_grad(set_to_none=True)
            started = time.perf_counter_ns()
            with torch.set_grad_enabled(backward):
                output = calls[name](x, dt, observed)
                if backward:
                    F.cross_entropy(output.flatten(0, 1), labels.flatten()).backward()
            elapsed = (time.perf_counter_ns() - started) * 1e-9
            (warmups if iteration < warmup_count else samples)[name].append(elapsed)
    medians = {key: statistics.median(values) for key, values in samples.items()}
    return dict(backward=backward, raw_seconds=samples, raw_warmup_seconds=warmups,
                order=order, median_seconds=medians,
                dense_over_adapter={key: medians["dense"] / value for key, value in medians.items() if key != "dense"})


def run(phase, out):
    torch.set_num_threads(1)
    out.mkdir(parents=True, exist_ok=False)
    identity = sources()
    frozen = json.loads((HERE / "CANDIDATE_FREEZE.json").read_text()) if phase == "confirmation" else None
    if frozen and (identity != frozen["source"] or any(digest(checkpoint(t)) != frozen["checkpoints"][t] for t in PLAN["tasks"])):
        raise ValueError("Frozen source or checkpoint changed")
    backends = [frozen["selected_backend"]] if frozen else PLAN["development_candidates"]
    write(out / "START_IDENTITY.json", dict(phase=phase, seed=PLAN[phase + "_seed"],
        started_unix_ns=time.time_ns(), source=identity,
        checkpoints={t: digest(checkpoint(t)) for t in PLAN["tasks"]},
        candidate_freeze_sha256=digest(HERE / "CANDIDATE_FREEZE.json") if frozen else None))
    cpu, wall = time.process_time(), time.perf_counter()
    construction, checks, rows = [], [], []
    for task_index, task in enumerate(PLAN["tasks"]):
        model = model_for(task)
        candidates = {}
        for backend in backends:
            try:
                candidate = adapter.ExactAddressedAdapter(model, backend)
                candidates[backend] = candidate
                construction.append(dict(task=task, backend=backend, stage="construct", passed=True,
                    compiled_here=candidate.compiled_here,
                    compile_cpu_seconds=candidate.compile_cpu_seconds,
                    compile_wall_seconds=candidate.compile_wall_seconds))
                journal(out / "CONSTRUCTION.jsonl", construction[-1])
                tests = engineering(task, backend)
                checks += [dict(task=task, backend=backend, **test) for test in tests]
                for check in checks[-len(tests):]:
                    journal(out / "CHECKS.jsonl", check)
                complete = len(tests) == PLAN["engineering_checks_per_task_backend"] and all(test["passed"] for test in tests)
                construction.append(dict(task=task, backend=backend, stage="engineering_complete", passed=complete, checks=len(tests)))
                journal(out / "CONSTRUCTION.jsonl", construction[-1])
                if not complete:
                    del candidates[backend]
            except Exception as error:
                candidates.pop(backend, None)
                construction.append(dict(task=task, backend=backend, stage="failed", passed=False, error=repr(error), traceback=traceback.format_exc()))
                journal(out / "CONSTRUCTION.jsonl", construction[-1])
        for index, (batch_size, condition) in enumerate(PLAN["workloads"]):
            arrays = data.batch(task, batch_size, PLAN[phase + "_seed"], "dev", condition)
            for backend, candidate in candidates.items():
                checks.append(dict(task=task, backend=backend, name=f"{condition}/B{batch_size}",
                                   **numerical(model, candidate, arrays)))
                journal(out / "CHECKS.jsonl", checks[-1])
            calls = dict(dense=model, **candidates)
            for backward in (False, True):
                row = benchmark(calls, model, arrays, backward, PLAN[phase + "_seed"] + task_index * 100 + index, phase)
                row.update(task=task, batch=batch_size, condition=condition, steps=arrays["x"].shape[1])
                rows.append(row)
                journal(out / "TIMINGS.jsonl", row)
            print(json.dumps(dict(task=task, batch=batch_size, condition=condition,
                                 ratios=[r["dense_over_adapter"] for r in rows[-2:]])), flush=True)
    eligible = []
    for backend in backends:
        qualified = (all(r["passed"] for r in checks if r["backend"] == backend)
                     and all(r["passed"] for r in construction if r["backend"] == backend)
                     and {r["task"] for r in construction if r["backend"] == backend} == set(PLAN["tasks"])
                     and all(sum(r["task"] == task and r["backend"] == backend for r in checks)
                             == PLAN["engineering_checks_per_task_backend"] + PLAN["numerical_workloads_per_task_backend"]
                             for task in PLAN["tasks"])
                     and all(backend in row["dense_over_adapter"] for row in rows))
        minimum_ratio = min((row["dense_over_adapter"].get(backend, 0) for row in rows), default=0)
        eligible.append(dict(backend=backend, numerical_eligible=qualified, minimum_ratio=minimum_ratio,
                             stable_speed_gate=qualified and minimum_ratio >= 1.05))
    valid = [item for item in eligible if item["numerical_eligible"]]
    selected = max(valid, key=lambda item: (item["minimum_ratio"], item["backend"] == "eager"))["backend"] if valid else None
    result = dict(schema="hcsn.exact-addressed-r2.result.v1", phase=phase, source=identity,
                  source_unchanged=identity == sources(), construction=construction, checks=checks, rows=rows,
                  candidates=eligible, selected_backend=selected, body_cpu_seconds=time.process_time() - cpu,
                  body_wall_seconds=time.perf_counter() - wall,
                  runtime=dict(python=platform.python_version(), torch=torch.__version__, numpy=np.__version__, scipy=scipy.__version__),
                  threads=torch.get_num_threads(), production_activation=False,
                  original_default_modified=False, energy_joules=None, scope=PLAN["scope"])
    write(out / "SUMMARY.json", result)
    return result


def freeze(development):
    result = json.loads((development / "SUMMARY.json").read_text())
    if result["selected_backend"] is None or not result["source_unchanged"] or result["source"] != sources():
        raise ValueError("No valid fixed development candidate")
    record = dict(schema="hcsn.exact-addressed-r2.candidate-freeze.v1", source=sources(),
                  selected_backend=result["selected_backend"], selected_by=PLAN["candidate_selection"],
                  checkpoints={t: digest(checkpoint(t)) for t in PLAN["tasks"]},
                  development_summary_sha256=digest(development / "SUMMARY.json"),
                  created_unix_ns=time.time_ns())
    write(HERE / "CANDIDATE_FREEZE.json", record)
    return record


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("development", "freeze", "confirmation"))
    parser.add_argument("--out", type=Path)
    parser.add_argument("--development", type=Path)
    args = parser.parse_args()
    if args.phase == "freeze":
        if args.development is None:
            parser.error("--development is required")
        print(json.dumps(freeze(args.development), indent=2))
    else:
        if args.out is None:
            parser.error("--out is required")
        result = run(args.phase, args.out)
        print(json.dumps(dict(selected=result["selected_backend"], candidates=result["candidates"]), indent=2))
