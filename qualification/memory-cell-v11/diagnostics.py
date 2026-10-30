"""Post-hoc V10 geometry/optimization diagnosis, never a new V10 qualification.

Pinv/ridge controls ask whether the canonical feature matrix can represent its
stored targets. They make no claim about unseen wording or arbitrary memories.
Budget choices depend only on training size/loss, never held accuracy.
"""

import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

import numpy as np

V10 = Path(__file__).resolve().parents[1] / "memory-cell-v10"
sys.path.insert(0, str(V10))
from cells import Cell, SEMANTIC_OUTPUTS, PROCEDURE_OUTPUTS, objective
from corpus import targets
from reference import decode, forward, load_checkpoint


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def geometry(x):
    x = np.asarray(x, dtype=np.float64)
    result = {}
    for name, matrix in (("raw", x), ("with_bias", np.c_[x, np.ones(len(x))]),
                         ("centered", x - x.mean(axis=0))):
        singular = np.linalg.svd(matrix, compute_uv=False)
        tolerance = singular[0] * max(matrix.shape) * np.finfo(np.float64).eps
        rank = int(np.sum(singular > tolerance))
        result[name] = dict(shape=list(matrix.shape), rank=rank, row_rank_full=rank == len(x),
                            tolerance=tolerance, singular_values=singular.tolist(),
                            condition=float(singular[0] / singular[-1]) if singular[-1] > tolerance else None)
    distances = np.linalg.norm(x[:, None] - x[None, :], axis=-1)
    np.fill_diagonal(distances, np.inf)
    result["min_pairwise_l2"] = float(distances.min()) if len(x) > 1 else None
    result["duplicate_rows"] = len(x) - len(np.unique(x, axis=0))
    return result


def solve_affine(x, y, *, ridge=0.0):
    """Independent float64 SVD solution; ridge regularizes bias as well."""
    design = np.c_[np.asarray(x, np.float64), np.ones(len(x))]
    u, singular, vh = np.linalg.svd(design, full_matrices=False)
    cutoff = np.finfo(np.float64).eps * max(design.shape) * singular[0]
    factors = np.zeros_like(singular)
    if ridge == 0:
        keep = singular > cutoff
        factors[keep] = 1 / singular[keep]
    else:
        if ridge < 0:
            raise ValueError("ridge must be nonnegative")
        factors = singular / (singular * singular + ridge)
    coefficients = (vh.T * factors) @ u.T @ np.asarray(y, np.float64)
    return {"head.weight": coefficients[:-1].T, "head.bias": coefficients[-1]}


def exact(raw, values, kind):
    predictions = decode(raw, kind)
    good = [prediction["value"] == value for prediction, value in zip(predictions, values, strict=True)]
    return dict(correct=sum(good), count=len(good), accuracy=sum(good) / len(good) if good else None,
                predictions=predictions)


def fit_legacy(model, x, y, outputs, schedule, *, lr=.01, tolerance=None, check_every=100):
    """V10 float32 Adam equations; moments persist across convergence checks."""
    start, cpu = time.perf_counter(), time.process_time()
    x, y = np.asarray(x, np.float32), np.asarray(y, np.float32)
    params = model.parameters()
    first, second = ({k: np.zeros_like(v) for k, v in params.items()} for _ in range(2))
    before = model.identity()
    trace, used, converged = [], 0, False
    for used, rows in enumerate(schedule, 1):
        loss, derivative = objective(model.forward(x[rows]), y[rows], outputs)
        if not np.isfinite(loss):
            raise FloatingPointError("nonfinite loss")
        for name, gradient in model.gradients(x[rows], derivative).items():
            if not np.isfinite(gradient).all():
                raise FloatingPointError("nonfinite gradient")
            first[name] = .9 * first[name] + .1 * gradient
            second[name] = .999 * second[name] + .001 * gradient * gradient
            params[name] -= lr * (first[name] / (1 - .9 ** used)) / (np.sqrt(second[name] / (1 - .999 ** used)) + 1e-8)
        if used == 1 or used % check_every == 0 or used == len(schedule):
            full_loss = objective(model.forward(x), y, outputs)[0]
            trace.append(dict(step=used, full_training_loss=full_loss))
            if tolerance is not None and full_loss <= tolerance:
                converged = True
                break
    return dict(initial_parameter_sha256=before, final_parameter_sha256=model.identity(),
                steps=used, sample_presentations=used * schedule.shape[1],
                presentations_per_address=used * schedule.shape[1] / len(x), trace=trace,
                train_loss_threshold=tolerance, converged=converged if tolerance is not None else None,
                schedule_sha256=hashlib.sha256(schedule[:used].astype("<i8").tobytes()).hexdigest(),
                cpu_seconds=time.process_time() - cpu, wall_seconds=time.perf_counter() - start)


def run(args):
    args.output.mkdir(parents=True, exist_ok=False)
    report = dict(schema="hepta.memory.v11.v10-diagnosis.v1", retrospective=True,
                  changes_original_v10_decision=False, training_only_budget_rules=True,
                  data_root=str(args.data), seed=args.seed, capacities={})
    for capacity in args.capacities:
        directory = args.data / "data" / f"capacity-{capacity}"
        population = json.loads((directory / "sources.json").read_text())
        with np.load(directory / "canonical.npz", allow_pickle=False) as arrays:
            features = {kind: arrays[kind] for kind in args.kinds}
        # These old held inputs are used ONLY to diagnose the previously reported result.
        queries = json.loads((directory / "held-queries.json").read_text())
        with np.load(directory / "held-features.npz", allow_pickle=False) as archive:
            query_x = archive["features"]
        cell_report = {}
        for offset, kind in enumerate(args.kinds):
            rows = [row for row in population["records"] if row["kind"] == kind]
            values = [row["value"] for row in rows]
            y, x = targets(values, kind), features[kind]
            outputs = SEMANTIC_OUTPUTS if kind == "semantic" else PROCEDURE_OUTPUTS
            positions = [i for i, row in enumerate(queries) if row["role"] == ("semantic" if kind == "semantic" else "skill")]
            indices = [queries[i]["entity" if kind == "semantic" else "workflow"] for i in positions]
            worded_x, worded_values = query_x[positions], [values[i] for i in indices]
            observed = dict(geometry=geometry(x), source_sha256=hashlib.sha256((directory / "sources.json").read_bytes()).hexdigest(),
                            arms={})

            def evaluate(name, arrays, fit_receipt=None):
                storage = exact(forward(arrays, x), values, kind)
                oracle_worded = exact(forward(arrays, x[indices]), worded_values, kind)
                direct = exact(forward(arrays, worded_x), worded_values, kind)
                observed["arms"][name] = dict(canonical_storage=storage,
                    worded_with_oracle_address=oracle_worded, worded_without_oracle=direct,
                    fit=fit_receipt, float64_parameter_l2=float(np.sqrt(sum(np.square(v).sum() for v in arrays.values()))))

            # A signed margin target gives both bit and multiclass controls exact labels.
            margin_targets = (2 * y.astype(np.float64) - 1) * 8
            for ridge in (0.0, 1e-6, 1e-4, 1e-2):
                arrays = solve_affine(x, margin_targets, ridge=ridge)
                evaluate("pinv" if ridge == 0 else f"ridge-{ridge:g}", arrays)
                if ridge == 0:
                    evaluate("pinv-float32-storage", {k: v.astype(np.float32) for k, v in arrays.items()})
            legacy = args.data / "models" / f"capacity-{capacity}-seed-{args.legacy_seed}"
            for arm, rank in (("linear", 0), ("residual", 4)):
                old = legacy / f"content-{kind}-{arm}"
                if old.exists():
                    arrays, manifest = load_checkpoint(old)
                    evaluate("original-v10-" + arm, arrays, dict(checkpoint_parameter_sha256=manifest["parameter_sha256"]))
                if args.skip_training:
                    continue
                budgets = dict(fixed_total=args.steps,
                               fixed_per_address=int(np.ceil(args.steps * capacity / 32)),
                               convergence=args.max_steps)
                max_budget = max(budgets.values())
                schedule = np.random.default_rng(args.seed + offset + 70000).integers(capacity, size=(max_budget, 32), dtype=np.int64)
                for budget_name, steps in budgets.items():
                    model = Cell(x.shape[1], y.shape[1], rank, args.seed + offset)
                    receipt = fit_legacy(model, x, y, outputs, schedule[:steps], lr=args.learning_rate,
                                         tolerance=args.loss_tolerance if budget_name == "convergence" else None)
                    name = f"{arm}-{budget_name}"
                    evaluate(name, model.arrays, receipt)
                    np.savez_compressed(args.output / f"{capacity}-{kind}-{name}.npz", **model.arrays)
                    print(json.dumps(dict(capacity=capacity, kind=kind, arm=name,
                                          canonical=observed["arms"][name]["canonical_storage"]["accuracy"],
                                          steps=receipt["steps"])), flush=True)
            cell_report[kind] = observed
        report["capacities"][str(capacity)] = cell_report
        (args.output / "DIAGNOSIS.json").write_bytes(canonical(report) + b"\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True, help="verified restored V10 formal run")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--capacities", nargs="+", type=int, default=[32, 64, 128])
    parser.add_argument("--kinds", nargs="+", choices=["semantic", "procedure"], default=["semantic", "procedure"])
    parser.add_argument("--seed", type=int, default=20261030)
    parser.add_argument("--legacy-seed", type=int, default=1741)
    parser.add_argument("--steps", type=int, default=1200)
    parser.add_argument("--max-steps", type=int, default=12000)
    parser.add_argument("--learning-rate", type=float, default=.01)
    parser.add_argument("--loss-tolerance", type=float, default=.001)
    parser.add_argument("--skip-training", action="store_true")
    args = parser.parse_args()
    if args.steps < 1 or args.max_steps < 1:
        parser.error("training budgets must be positive")
    run(args)


if __name__ == "__main__":
    main()
