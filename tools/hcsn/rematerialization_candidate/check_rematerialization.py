"""Compare isolated B rematerialization with the frozen original implementation.

Run from the baseline repository root, or supply --repo-root explicitly.
This is a one-update correctness fixture, not any of the 170 full-budget runs.
"""

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import platform
import sys
import time
import traceback


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def compare(torch, left, right, *, atol, rtol):
    if not bool(torch.isfinite(left).all()) or not bool(torch.isfinite(right).all()):
        raise AssertionError("nonfinite values in parity comparison")
    torch.testing.assert_close(left, right, atol=atol, rtol=rtol)
    delta = (left.detach()-right.detach()).double()
    return {"exact": torch.equal(left, right),
            "maximum_absolute_error": float(delta.abs().max()),
            "rms_error": float(delta.square().mean().sqrt())}


def run_case(torch, encoder_class, args, *, dtype_name, recovery,
             segment_steps, input_grad):
    from qualification.hcsn.baselines import PopulationFluxEncoder
    from qualification.hcsn.benchmark import make_dataset

    dtype = getattr(torch, dtype_name)
    atol, rtol = ((1e-12, 1e-10) if dtype == torch.float64 else (1e-6, 1e-5))
    task = "delayed_recall" if recovery else "adding"
    case = dict(dtype=dtype_name, recovery=recovery, segment_steps=segment_steps,
                input_requires_grad=input_grad, task=task, atol=atol, rtol=rtol)
    started = time.perf_counter()

    class Regressor(torch.nn.Module):
        def __init__(self, encoder):
            super().__init__()
            self.encoder = encoder
            self.readout = torch.nn.Linear(args.hidden_size, 1)

        def forward(self, inputs):
            traces = self.encoder(inputs, dt=0.1)
            return traces, self.readout(traces[:, -1])

    torch.manual_seed(0)
    baseline = Regressor(PopulationFluxEncoder(
        2, args.hidden_size, recovery=recovery)).to(device=args.device, dtype=dtype)
    candidate = Regressor(encoder_class(
        2, args.hidden_size, recovery=recovery,
        segment_steps=segment_steps)).to(device=args.device, dtype=dtype)
    candidate.load_state_dict(baseline.state_dict(), strict=True)
    baseline.train()
    candidate.train()
    x, y = make_dataset(task, args.batch_size, args.length, 271828)
    target = torch.from_numpy(y).to(device=args.device, dtype=dtype)
    original_x = torch.from_numpy(x).to(device=args.device, dtype=dtype).requires_grad_(input_grad)
    replay_x = original_x.detach().clone().requires_grad_(input_grad)
    baseline_optimizer = torch.optim.Adam(baseline.parameters(), lr=0.001)
    candidate_optimizer = torch.optim.Adam(candidate.parameters(), lr=0.001)
    baseline_optimizer.zero_grad(set_to_none=True)
    candidate_optimizer.zero_grad(set_to_none=True)

    original_trace, original_prediction = baseline(original_x)
    replay_trace, replay_prediction = candidate(replay_x)
    # Storage/rematerialization adds no arithmetic to forward values.
    case["trace"] = compare(torch, original_trace, replay_trace, atol=0, rtol=0)
    case["prediction"] = compare(torch, original_prediction, replay_prediction, atol=0, rtol=0)
    original_loss = (original_prediction-target).square().mean()
    replay_loss = (replay_prediction-target).square().mean()
    case["loss"] = compare(torch, original_loss, replay_loss, atol=0, rtol=0)
    original_loss.backward()
    replay_loss.backward()
    case["parameter_gradients"] = {}
    for (name, left), (other_name, right) in zip(
            baseline.named_parameters(), candidate.named_parameters(), strict=True):
        if name != other_name or left.grad is None or right.grad is None:
            raise AssertionError(f"missing or mismatched parameter gradient: {name}")
        case["parameter_gradients"][name] = compare(
            torch, left.grad, right.grad, atol=atol, rtol=rtol)
    if input_grad:
        if original_x.grad is None or replay_x.grad is None:
            raise AssertionError("input gradients were lost")
        case["input_gradients"] = compare(
            torch, original_x.grad, replay_x.grad, atol=atol, rtol=rtol)
    else:
        if original_x.grad is not None or replay_x.grad is not None:
            raise AssertionError("fixture unexpectedly created input gradients")
        case["input_gradients"] = None
    left_norm = torch.nn.utils.clip_grad_norm_(baseline.parameters(), 1.0)
    right_norm = torch.nn.utils.clip_grad_norm_(candidate.parameters(), 1.0)
    case["gradient_norm_before_clip"] = compare(
        torch, left_norm, right_norm, atol=atol, rtol=rtol)
    baseline_optimizer.step()
    candidate_optimizer.step()
    case["parameters_after_adam"] = {}
    case["optimizer_state_after_adam"] = {}
    for (name, left), (_, right) in zip(
            baseline.named_parameters(), candidate.named_parameters(), strict=True):
        case["parameters_after_adam"][name] = compare(
            torch, left, right, atol=atol, rtol=rtol)
        left_state, right_state = baseline_optimizer.state[left], candidate_optimizer.state[right]
        if set(left_state) != set(right_state):
            raise AssertionError(f"optimizer state mismatch: {name}")
        case["optimizer_state_after_adam"][name] = {
            key: compare(torch, left_state[key], right_state[key], atol=atol, rtol=rtol)
            for key in left_state}
    baseline.eval()
    candidate.eval()
    with torch.no_grad():
        left_trace, left_prediction = baseline(original_x)
        right_trace, right_prediction = candidate(replay_x)
    case["no_grad_trace_after_adam"] = compare(
        torch, left_trace, right_trace, atol=atol, rtol=rtol)
    case["no_grad_prediction_after_adam"] = compare(
        torch, left_prediction, right_prediction, atol=atol, rtol=rtol)
    case.update(status="passed", elapsed_seconds=time.perf_counter()-started)
    return case


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--batch-size", type=int, default=2)
    parser.add_argument("--length", type=int, default=9)
    parser.add_argument("--hidden-size", type=int, default=3)
    parser.add_argument("--segments", type=int, nargs="+", default=[1, 4])
    parser.add_argument("--dtypes", nargs="+", choices=["float32", "float64"],
                        default=["float32", "float64"])
    args = parser.parse_args()
    root = args.repo_root.resolve()
    here = Path(__file__).resolve().parent
    manifest = json.loads((here/"CANDIDATE.json").read_text())
    module_path = here/"qualification/hcsn/rematerialization.py"
    report = dict(scope="one-update parity fixture; not full-budget qualification",
                  shape=[args.batch_size, args.length, 2], hidden_size=args.hidden_size,
                  bins=32, device=args.device, records=[],
                  manifest_sha256=sha256(here/"CANDIDATE.json"),
                  candidate_module_sha256=sha256(module_path),
                  checker_sha256=sha256(__file__))
    try:
        report["baseline_source_sha256"] = {
            name: sha256(root/name) for name in manifest["baseline_source_sha256"]}
        if report["baseline_source_sha256"] != manifest["baseline_source_sha256"]:
            raise ValueError("baseline source differs from the frozen candidate manifest")
        if report["candidate_module_sha256"] != manifest["candidate_module_sha256"]:
            raise ValueError("candidate module differs from the frozen candidate manifest")
        sys.path.insert(0, str(root))
        import torch
        torch.set_num_threads(2)
        if torch.device(args.device).type == "cuda" and not torch.cuda.is_available():
            raise RuntimeError("requested CUDA device is unavailable; no CPU fallback")
        report["software"] = dict(python=platform.python_version(), torch=torch.__version__,
                                  cuda=torch.version.cuda)
        spec = importlib.util.spec_from_file_location("qualification.hcsn.rematerialization", module_path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        for dtype_name in args.dtypes:
            for recovery in (True, False):
                for segment_steps in args.segments:
                    for input_grad in (False, True):
                        try:
                            row = run_case(torch, module.RematerializedPopulationFluxEncoder, args,
                                           dtype_name=dtype_name, recovery=recovery,
                                           segment_steps=segment_steps, input_grad=input_grad)
                        except Exception:
                            row = dict(status="failed", dtype=dtype_name, recovery=recovery,
                                       segment_steps=segment_steps, input_requires_grad=input_grad,
                                       error=traceback.format_exc())
                        report["records"].append(row)
                        print(json.dumps({key: row[key] for key in (
                            "status", "dtype", "recovery", "segment_steps", "input_requires_grad")}), flush=True)
        report["status"] = "passed" if all(r["status"] == "passed" for r in report["records"]) else "failed"
        code = 0 if report["status"] == "passed" else 1
    except ImportError:
        report.update(status="unavailable", error=traceback.format_exc())
        code = 2
    except Exception:
        report.update(status="failed", error=traceback.format_exc())
        code = 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    # Refuse to overwrite evidence from a prior execution.
    with args.output.open("x") as stream:
        json.dump(report, stream, indent=2, allow_nan=False)
        stream.write("\n")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
