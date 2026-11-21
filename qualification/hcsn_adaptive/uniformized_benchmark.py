"""Development kernel comparison: complete sequence forward AND backward.

Synthetic inputs only; this is not a task-quality/holdout benchmark. Same model
parameters, inputs, controls, FP64 outputs, loss and strict error checks for both
backends. Every attempted timing remains in the output, including failures.
Process peak RSS includes both arms and is NOT an attributable per-arm peak.
No warmup is silently discarded: first invocation and subsequent repeats are
reported separately, with model construction time outside the timed invocation.
"""

import argparse
import hashlib
import json
from pathlib import Path
import platform
import resource
import time

import torch

from .batched_flow import BatchedFlow, FlowConfig
from .uniformized_flow import UniformizedFlow


def measure(model, inputs):
    model.zero_grad(set_to_none=True)
    start = time.perf_counter()
    features, state = model(inputs)
    forward = time.perf_counter()
    loss = features.square().mean() + state.density.square().mean()
    loss.backward()
    finished = time.perf_counter()
    gradient = torch.cat([p.grad.flatten() for p in model.parameters()])
    return {"forward_seconds": forward-start, "backward_seconds": finished-forward,
            "total_seconds": finished-start}, features.detach(), state.density.detach(), gradient.detach()


def run(output, repetitions):
    if not 1 <= repetitions <= 7:
        raise ValueError("one to seven retained repeats required")
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    # Reserve before any numerical work; interrupted files cannot be overwritten.
    with output.open("x") as handle:
        handle.write('{"status":"started","results":[]}\n')
    campaign_start = time.perf_counter()
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    torch.use_deterministic_algorithms(True)
    source = Path(__file__).parent
    report = {"kind": "development_kernel_comparison", "torch": torch.__version__,
              "python": platform.python_version(), "platform": platform.platform(),
              "threads": [torch.get_num_threads(), torch.get_num_interop_threads()],
              "torch_config": torch.__config__.show(), "repetitions": repetitions,
              "sources": {name: hashlib.sha256((source/name).read_bytes()).hexdigest()
                          for name in ("batched_flow.py", "finite_control.py", "uniformized_flow.py", Path(__file__).name)},
              "claims": "FP64 synthetic kernel timings; no task/scaling superiority", "cases": []}
    for case_index, (batch, bins, stages) in enumerate(((8, 6, 3), (16, 24, 8), (8, 48, 12))):
        case = {"batch": batch, "bins": bins, "stages": stages, "length": 4, "arms": {}}
        report["cases"].append(case)
        try:
            torch.manual_seed(74119 + case_index)
            config = FlowConfig(input_size=4, content_size=4, bins=bins, stages=stages, dt=.05)
            construction_start = time.perf_counter()
            dense, sparse = BatchedFlow(config), UniformizedFlow(config)
            sparse.load_state_dict(dense.state_dict())
            case["pair_construction_seconds"] = time.perf_counter() - construction_start
            inputs = torch.randn(4, batch, 4, dtype=torch.float64) * .2
            reference = None
            # Alternate order over repetitions; both arms' first call is retained.
            for repeat in range(repetitions):
                order = (("dense", dense), ("action", sparse))
                if repeat % 2:
                    order = order[::-1]
                for name, model in order:
                    timing, values, density, gradient = measure(model, inputs)
                    timing["repeat"] = repeat
                    case["arms"].setdefault(name, []).append(timing)
                    if reference is None:
                        reference = values, density, gradient
                    errors = [float((a-b).abs().max()) for a, b in zip((values, density, gradient), reference, strict=True)]
                    timing["max_abs_output_state_gradient"] = errors
                    for actual, expected in zip((values, density, gradient), reference, strict=True):
                        torch.testing.assert_close(actual, expected, rtol=1e-8, atol=2e-10)
            case["action"] = sparse.last_action_report
            case["status"] = "passed_numerical_comparison"
        except Exception as error:
            case["status"], case["error"] = "failed", repr(error)
        report["process_maxrss_kib_linux_or_bytes_macos"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        report["campaign_wall_seconds"] = time.perf_counter() - campaign_start
        output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"artifact": str(output), "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
                      "statuses": [c["status"] for c in report["cases"]]}, sort_keys=True))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    parser.add_argument("--repetitions", type=int, default=3)
    args = parser.parse_args()
    run(args.output, args.repetitions)
