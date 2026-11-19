"""One fresh-process, predeclared equal-time PenDigits training fit."""

import argparse
import copy
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import resource
import time
import traceback

import numpy as np
import torch

from .benchmark_data import training_data
from .benchmark_models import make_model


def verify_sources(protocol):
    root = Path(__file__).resolve().parents[2]
    for name, expected in protocol["sources"].items():
        if hashlib.sha256((root/name).read_bytes()).hexdigest() != expected:
            raise ValueError("frozen source mismatch: "+name)
    expected = protocol["runtime"]
    actual = {"python": platform.python_version(),
              **{name: importlib.metadata.version(name) for name in ("torch", "numpy", "scipy", "ncps")}}
    if actual != expected["versions"]:
        raise ValueError("frozen runtime package versions changed")
    for package, files in expected["package_files"].items():
        distribution = importlib.metadata.distribution(package)
        for name, wanted in files.items():
            if hashlib.sha256(Path(distribution.locate_file(name)).read_bytes()).hexdigest() != wanted:
                raise ValueError("frozen package source/RECORD changed")


def metrics(logits, labels):
    predicted = logits.argmax(1)
    return {"accuracy": float((predicted == labels).double().mean()),
            "cross_entropy": float(torch.nn.functional.cross_entropy(logits, labels))}


def evaluate(model, x, y, batch=250):
    model.eval()
    with torch.no_grad():
        logits = torch.cat([model(x[i:i+batch]) for i in range(0, len(x), batch)])
    if not bool(torch.isfinite(logits).all()):
        raise FloatingPointError("nonfinite evaluation output")
    return metrics(logits, y), logits


def run(args):
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=False)
    protocol = json.loads(Path(args.protocol).read_text())
    verify_sources(protocol)
    if args.arm not in protocol["arms"] or args.seed not in protocol["seeds"]:
        raise ValueError("fit outside frozen roster")
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    torch.manual_seed(args.seed)
    np.random.seed(args.seed)
    generator = np.random.default_rng(args.seed)
    x, y, vx, vy, train_rows, validation_rows = training_data(args.data)
    np.savez_compressed(out/"split.npz", training=train_rows, validation=validation_rows)
    # Imports/source/data checks are whole-process setup, separately charged
    # by the parent. Model construction starts the equal-time comparison.
    start_wall, start_cpu = time.perf_counter(), time.process_time()
    model = make_model(args.arm)
    optimizer = torch.optim.Adam(model.parameters(), lr=protocol["learning_rate"])
    deadline = protocol["budget_seconds"]
    best, best_order, journal, updates = None, None, [], 0
    next_validation = 0.
    with (out/"training.jsonl").open("x") as trace:
        while time.perf_counter()-start_wall < deadline:
            elapsed = time.perf_counter()-start_wall
            if elapsed >= next_validation:
                measured, logits = evaluate(model, vx, vy)
                ordinal = len(journal)
                np.savez_compressed(out/f"validation-{ordinal:03}.npz",
                                    logits=logits.numpy(), labels=vy.numpy())
                order = (measured["accuracy"], -measured["cross_entropy"])
                improved = best_order is None or order > best_order
                snapshot = None
                if improved:
                    snapshot = {"model": copy.deepcopy(model.state_dict()),
                                "optimizer": copy.deepcopy(optimizer.state_dict()),
                                "torch_rng": torch.get_rng_state().clone(),
                                "numpy_rng": copy.deepcopy(generator.bit_generator.state),
                                "updates": updates, "validation_index": ordinal}
                completed = time.perf_counter()-start_wall
                eligible = completed <= deadline
                row = {"updates": updates, "completed_seconds": completed,
                       "eligible": eligible, **measured}
                journal.append(row)
                if improved and eligible:
                    best_order, best = order, snapshot
                trace.write(json.dumps({"validation": row})+"\n")
                trace.flush()
                next_validation = (int(completed/protocol["validation_interval"])+1)*protocol["validation_interval"]
                if completed >= deadline:
                    break
            model.train()
            chosen = generator.integers(0, len(x), protocol["batch_size"])
            optimizer.zero_grad(set_to_none=True)
            loss = torch.nn.functional.cross_entropy(model(x[chosen]), y[chosen])
            if not bool(torch.isfinite(loss)):
                raise FloatingPointError("nonfinite training loss")
            loss.backward()
            norm = torch.nn.utils.clip_grad_norm_(model.parameters(), 1., error_if_nonfinite=True)
            optimizer.step()
            updates += 1
            trace.write(json.dumps({"update": updates, "loss": float(loss.detach()),
                                    "gradient_norm": float(norm),
                                    "completed_seconds": time.perf_counter()-start_wall})+"\n")
            trace.flush()
    training_wall = time.perf_counter()-start_wall
    training_cpu = time.process_time()-start_cpu
    if best is None:
        raise RuntimeError("no validation and snapshot finished within the declared budget")
    torch.save(best, out/"selected.pt")
    torch.save({"model": model.state_dict(), "optimizer": optimizer.state_dict(),
                "torch_rng": torch.get_rng_state(), "numpy_rng": generator.bit_generator.state,
                "updates": updates}, out/"last.pt")
    verify_sources(protocol)
    selected = journal[best["validation_index"]]
    first_target = next((r["completed_seconds"] for r in journal if r["eligible"]
                         and r["accuracy"] >= protocol["accuracy_target"]), None)
    result = {"status": "COMPLETED_WALL_BUDGET", "arm": args.arm, "seed": args.seed,
              "updates": updates, "selected_updates": best["updates"], "selected": selected,
              "validations": journal, "budget_seconds": deadline,
              "training_wall_seconds": training_wall, "training_cpu_seconds": training_cpu,
              "time_to_validation_target_first_observed": first_target,
              "target_not_observed_is_censored": first_target is None,
              "parameter_count": sum(p.numel() for p in model.parameters()),
              "training_rows": len(x), "validation_rows": len(vx), "test_rows_read": 0,
              "dtype": "float64", "python": platform.python_version(), "torch": torch.__version__,
              "process_maxrss_kib_at_training_end": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
              "adequate_training_or_global_optimum_proven": False}
    (out/"RESULT.json").write_text(json.dumps(result, indent=2)+"\n")
    print(json.dumps({"arm": args.arm, "seed": args.seed, "updates": updates,
                      "validation_accuracy": selected["accuracy"], "test_rows_read": 0}), flush=True)


def main():
    parser = argparse.ArgumentParser()
    for name in ("arm", "data", "output", "protocol"):
        parser.add_argument("--"+name, required=True)
    parser.add_argument("--seed", type=int, required=True)
    args = parser.parse_args()
    try:
        run(args)
    except Exception:
        failure = {"status": "FAILED", "traceback": traceback.format_exc()}
        output = Path(args.output)
        if output.is_dir():
            (output/"FAILURE.json").write_text(json.dumps(failure, indent=2)+"\n")
        raise


if __name__ == "__main__":
    main()
