"""Source-bound synthetic comparison; no dataset reads or optimizer calls."""

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import time


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def child(plan, case, engine, output):
    import torch

    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    source = Path(plan["kernels"][engine]["path"])
    if digest(source) != plan["kernels"][engine]["sha256"]:
        raise ValueError("kernel source mismatch")
    name = "qualification.hcsn_currentstate.differentiable"
    spec = importlib.util.spec_from_file_location(name, source)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    from qualification.hcsn_network.benchmark_models import make_model

    torch.manual_seed(plan["model_seed"])
    model = make_model("flow")
    generator = torch.Generator().manual_seed(plan["input_seed"])
    inputs = torch.randn(case["batch"], case["steps"], 2, dtype=torch.float64,
                         generator=generator, requires_grad=True)
    initial_weights = {name: value.detach().clone() for name, value in model.state_dict().items()}

    def execute(capture):
        model.capture_state = capture
        model.zero_grad(set_to_none=True)
        inputs.grad = None
        saved_bytes = 0

        def pack(tensor):
            nonlocal saved_bytes
            saved_bytes += tensor.numel() * tensor.element_size()
            return tensor

        wall, cpu = time.perf_counter(), time.process_time()
        with torch.autograd.graph.saved_tensors_hooks(pack, lambda tensor: tensor):
            logits = model(inputs)
            logits.square().mean().backward()
        elapsed, cpu_elapsed = time.perf_counter() - wall, time.process_time() - cpu
        measured = {"wall_seconds": elapsed, "cpu_seconds": cpu_elapsed,
                    "autograd_saved_payload_bytes_with_repeats": saved_bytes,
                    "actual_forward_exponentials": model.last_forward_exponentials,
                    "largest_exponential_dimension": model.last_largest_dimension,
                    "state_bytes": model.last_state_bytes}
        if not all(bool(torch.isfinite(t).all()) for t in
                   (logits, inputs.grad, *[p.grad for p in model.parameters()])):
            raise FloatingPointError("nonfinite synthetic output or gradient")
        return logits, measured

    logits, probe = execute(True)
    state = model.last_state
    torch.save({"weights": initial_weights, "inputs": inputs.detach().clone(),
                "logits": logits.detach().clone(), "input_gradient": inputs.grad.detach().clone(),
                "parameter_gradients": {name: value.grad.detach().clone()
                                        for name, value in model.named_parameters()},
                "state_tensors": [t.detach().clone() for t in state.tensors()],
                "state_time": str(state.time), "state_bytes": state.tensor_bytes(),
                "pending_schedule": [[[type(p).__name__, str(p.start), str(p.end)]
                                       for p in cell.pending] for cell in state.cells]}, output / "RAW.pt")
    execute(False)
    repetitions = [execute(False)[1] for _ in range(plan["repetitions"])]
    if digest(source) != plan["kernels"][engine]["sha256"]:
        raise ValueError("kernel source changed while executing")
    result = {"engine": engine, "case": case, "probe": probe, "repetitions": repetitions,
              "optimizer_calls": 0, "dataset_rows_read": 0,
              "process_maxrss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
              "torch": torch.__version__, "python": sys.version,
              "raw_sha256": digest(output / "RAW.pt")}
    (output / "RESULT.json").write_text(json.dumps(result, indent=2) + "\n")


def run(plan_path, output):
    plan_bytes = plan_path.read_bytes()
    plan = json.loads(plan_bytes)
    output.mkdir(parents=True, exist_ok=False)
    (output / "PLAN.json").write_bytes(plan_bytes)
    for path, wanted in plan["support_sources"].items():
        if digest(path) != wanted:
            raise ValueError("support source mismatch: " + path)
    start_wall, start_cpu = time.perf_counter(), time.process_time()
    results = []
    for index, case in enumerate(plan["cases"]):
        order = ("baseline", "candidate") if index % 2 == 0 else ("candidate", "baseline")
        for engine in order:
            case_path = output / f"{case['name']}-{engine}"
            case_path.mkdir()
            command = [sys.executable, str(Path(__file__).resolve()), "--plan", str(plan_path),
                       "--output", str(case_path), "--engine", engine, "--case", str(index)]
            before = resource.getrusage(resource.RUSAGE_CHILDREN)
            wall = time.perf_counter()

            def constrain():
                os.sched_setaffinity(0, plan["cpu_affinity"])
                resource.setrlimit(resource.RLIMIT_AS, (plan["address_space_bytes"],) * 2)

            with (case_path / "stdout").open("wb") as stdout, (case_path / "stderr").open("wb") as stderr:
                try:
                    completed = subprocess.run(command, stdout=stdout, stderr=stderr, preexec_fn=constrain,
                        timeout=plan["child_timeout_seconds"], env={**os.environ, "OMP_NUM_THREADS": "1",
                        "MKL_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1"})
                    terminal = {"exit_code": completed.returncode, "timed_out": False}
                except subprocess.TimeoutExpired:
                    terminal = {"exit_code": None, "timed_out": True}
            after = resource.getrusage(resource.RUSAGE_CHILDREN)
            terminal.update({"child_wall_seconds": time.perf_counter() - wall,
                             "child_cpu_seconds": after.ru_utime + after.ru_stime - before.ru_utime - before.ru_stime})
            (case_path / "COST.json").write_text(json.dumps(terminal, indent=2) + "\n")
            results.append({"case": case["name"], "engine": engine, **terminal})
    for path, wanted in plan["support_sources"].items():
        if digest(path) != wanted:
            raise ValueError("support source changed: " + path)
    if plan_path.read_bytes() != plan_bytes:
        raise ValueError("plan changed during run")
    (output / "CONTROLLER.json").write_text(json.dumps({"children": results,
        "wall_seconds": time.perf_counter() - start_wall, "parent_cpu_seconds": time.process_time() - start_cpu,
        "plan_sha256": hashlib.sha256(plan_bytes).hexdigest()}, indent=2) + "\n")
    print(json.dumps({"children": len(results), "successful": sum(r["exit_code"] == 0 for r in results)}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--engine", choices=("baseline", "candidate"))
    parser.add_argument("--case", type=int)
    args = parser.parse_args()
    if args.engine is None:
        run(args.plan.resolve(), args.output.resolve())
    else:
        child(json.loads(args.plan.read_text()), json.loads(args.plan.read_text())["cases"][args.case],
              args.engine, args.output)
