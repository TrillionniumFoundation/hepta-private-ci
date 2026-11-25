#!/usr/bin/env python3
"""PFT6 measured synthetic costs; fixed-readout BP/ridge/RLS are primary peers.
Full BP and rank-two adapter BP are explicitly different-scope comparators.
No remote-network, Hepta-runtime adoption, hardware energy or real-user claim.
"""
import argparse
import hashlib
import json
import os
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["OMP_NUM_THREADS"] = "1"
import numpy as np

METHODS = ("readout_bp", "ridge", "rls", "adapter_bp", "full_bp")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def dump(path, value):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def timed(stages, key, fn):
    start = time.perf_counter()
    value = fn()
    stages[key] = stages.get(key, 0.) + time.perf_counter() - start
    return value


def predict(method, p, x, h, y0):
    if method == "full_bp":
        return np.tanh(x @ p["U"]) @ p["V"]
    if method == "adapter_bp":
        return y0 + h @ p["A"] @ p["B"]
    return y0 + h @ p["D"]


def loss_grads(method, p, x, y, h, y0, parent, lam):
    n = len(x)
    if method == "full_bp":
        hidden = np.tanh(x @ p["U"])
        e = hidden @ p["V"] - y
        du, dv = p["U"] - parent["U"], p["V"] - parent["V"]
        grads = {"V": hidden.T @ e / n + lam * dv,
                 "U": x.T @ ((e @ p["V"].T) * (1 - hidden ** 2)) / n + lam * du}
        penalty = np.sum(du ** 2) + np.sum(dv ** 2)
    else:
        d = p["A"] @ p["B"] if method == "adapter_bp" else p["D"]
        e = y0 + h @ d - y
        g = h.T @ e / n + lam * d
        grads = {"A": g @ p["B"].T, "B": p["A"].T @ g} if method == "adapter_bp" else {"D": g}
        penalty = np.sum(d ** 2)
    return float(np.sum(e ** 2) / (2 * n) + lam * penalty / 2), grads


def gradient_check():
    rng = np.random.default_rng(991)
    x, y = rng.normal(size=(7, 3)), rng.normal(size=(7, 2))
    parent = {"U": rng.normal(size=(3, 4)) * .2, "V": rng.normal(size=(4, 2)) * .2}
    h = np.tanh(x @ parent["U"])
    y0 = h @ parent["V"]
    rows = []
    for method in ("readout_bp", "adapter_bp", "full_bp"):
        if method == "full_bp":
            p = {k: v + rng.normal(size=v.shape) * .03 for k, v in parent.items()}
        elif method == "adapter_bp":
            p = {"A": rng.normal(size=(4, 2)) * .1, "B": rng.normal(size=(2, 2)) * .1}
        else:
            p = {"D": rng.normal(size=(4, 2)) * .1}
        _, grads = loss_grads(method, p, x, y, h, y0, parent, .013)
        errors = []
        for key in p:
            for idx in np.ndindex(p[key].shape):
                original, eps = p[key][idx], 1e-6
                p[key][idx] = original + eps
                plus = loss_grads(method, p, x, y, h, y0, parent, .013)[0]
                p[key][idx] = original - eps
                minus = loss_grads(method, p, x, y, h, y0, parent, .013)[0]
                p[key][idx] = original
                fd = (plus - minus) / (2 * eps)
                errors.append(abs(fd - grads[key][idx]) / max(1., abs(fd), abs(grads[key][idx])))
        rows.append({"method": method, "coordinates_checked": len(errors),
                     "max_scaled_error": float(max(errors)), "pass": bool(max(errors) < 1e-7)})
    if not all(r["pass"] for r in rows):
        raise AssertionError(rows)
    return rows


def fixture(root, width, seed):
    rng = np.random.default_rng(seed)
    din, q = min(width, 16), 4
    u = rng.normal(size=(din, width)) / np.sqrt(din)
    v = rng.normal(size=(width, q)) * .3 / np.sqrt(width)
    delta = rng.normal(size=(width, 2)) / np.sqrt(width) @ (rng.normal(size=(2, q)) * .15)
    arrays = {"U": u, "V": v}
    for split, n in (("train", 256), ("dev", 192), ("test", 384)):
        x = rng.normal(size=(n, din))
        y = np.tanh(x @ u) @ (v + delta) + rng.normal(size=(n, q)) * .01
        arrays[split + "_x"], arrays[split + "_y"] = x, y
    root.mkdir(parents=True, exist_ok=True)
    path = root / "fixture.npz"
    np.savez(path, **arrays)
    return path


def fit(method, p, data, parent, lam, budget, step_cap, mode, threshold, stages):
    x, y, h, y0 = (data[k] for k in ("train_x", "train_y", "htrain", "y0train"))
    start = time.perf_counter()
    checks, steps, first_quality = 0, 0, None
    dev_mse = None
    def check():
        pred = predict(method, p, data["dev_x"], data["hdev"], data["y0dev"])
        return float(np.mean((pred - data["dev_y"]) ** 2))
    if method == "ridge":
        def solve():
            p["D"] = np.linalg.solve(h.T @ h + len(h) * lam * np.eye(h.shape[1]), h.T @ (y - y0))
        timed(stages, "solve_s", solve)
        steps = 1
    elif method == "rls":
        def rls():
            precision_inverse = np.eye(h.shape[1]) / (len(h) * lam)
            d = p["D"]
            for phi, target in zip(h, y - y0):
                z = precision_inverse @ phi
                gain = z / (1 + phi @ z)
                d += np.outer(gain, target - phi @ d)
                precision_inverse -= np.outer(gain, phi @ precision_inverse)
            p["D"] = d
        timed(stages, "solve_s", rls)
        steps = len(h)
    else:
        m, v = {k: np.zeros_like(a) for k, a in p.items()}, {k: np.zeros_like(a) for k, a in p.items()}
        lr = .025 if method == "readout_bp" else .015
        for step in range(1, step_cap + 1):
            def update():
                _, grads = loss_grads(method, p, x, y, h, y0, parent, lam)
                for key, g in grads.items():
                    m[key] = .9 * m[key] + .1 * g
                    v[key] = .999 * v[key] + .001 * g * g
                    p[key] -= lr * (m[key] / (1 - .9 ** step)) / (np.sqrt(v[key] / (1 - .999 ** step)) + 1e-8)
            timed(stages, "solve_s", update)
            steps = step
            if step % 10 == 0:
                dev_mse = timed(stages, "validation_s", check)
                checks += 1
                if dev_mse <= threshold and first_quality is None:
                    first_quality = time.perf_counter() - start
                if mode == "time_to_quality" and first_quality is not None:
                    break
            if time.perf_counter() - start >= budget:
                break
    dev_mse = timed(stages, "validation_s", check)
    checks += 1
    if dev_mse <= threshold and first_quality is None:
        first_quality = time.perf_counter() - start
    elapsed = time.perf_counter() - start
    return {"steps": steps, "dev_checks": checks, "dev_mse": dev_mse,
            "fit_wall_s": elapsed, "fit_budget_exceeded": elapsed > budget,
            "first_validated_dev_quality_s": first_quality,
            "dev_quality_reached": dev_mse <= threshold,
            "stopped_at_step_cap": steps >= step_cap if method.endswith("bp") else False}


def measure(path, out, width, seed, method, mode, args):
    out.mkdir(parents=True, exist_ok=True)
    stages, start, cpu = {}, time.perf_counter(), time.process_time()
    def load():
        with np.load(path, allow_pickle=False) as z:
            return {k: z[k].copy() for k in z.files}
    data = timed(stages, "data_and_parent_load_s", load)
    parent = {k: data[k] for k in ("U", "V")}
    def features():
        for split in ("train", "dev"):
            data["h" + split] = np.tanh(data[split + "_x"] @ parent["U"])
            data["y0" + split] = data["h" + split] @ parent["V"]
    timed(stages, "feature_s", features)
    def diagnostic():
        if not all(np.isfinite(v).all() for v in data.values()):
            raise ValueError("Nonfinite fixture")
        h = data["htrain"]
        return float(np.linalg.cond(h.T @ h / len(h) + args.ridge * np.eye(width)))
    condition = timed(stages, "diagnostic_s", diagnostic)
    rng = np.random.default_rng(seed + 700)
    if method == "full_bp":
        p = {k: v.copy() for k, v in parent.items()}
    elif method == "adapter_bp":
        p = {"A": rng.normal(size=(width, 2)) * .1, "B": np.zeros((2, 4))}
    else:
        p = {"D": np.zeros((width, 4))}
    fitted = fit(method, p, data, parent, args.ridge, args.budget, args.steps,
                 mode, args.quality_mse, stages)
    candidate = out / "candidate.npz"
    timed(stages, "serialize_s", lambda: np.savez(candidate, **p))
    def readback():
        digest = sha(candidate)
        with np.load(candidate, allow_pickle=False) as z:
            restored = {k: z[k].copy() for k in z.files}
        if any(not np.array_equal(p[k], restored[k]) for k in p):
            raise AssertionError("Candidate serialization mismatch")
        return digest, restored
    digest, restored = timed(stages, "readback_s", readback)
    def validation():
        ht = np.tanh(data["test_x"] @ parent["U"])
        yt = ht @ parent["V"]
        pred = predict(method, restored, data["test_x"], ht, yt)
        return float(np.mean((pred - data["test_y"]) ** 2)), float(np.mean((yt - data["test_y"]) ** 2))
    mse, baseline = timed(stages, "validation_s", validation)
    passed = mse <= args.quality_mse and fitted["dev_quality_reached"]
    if passed:
        def adopt():
            target = out / "local_peer_active.npz"
            shutil.copyfile(candidate, target)
            if sha(target) != digest:
                raise AssertionError("Local peer copy mismatch")
            dump(out / "local_peer_current.json", {"sha256": digest, "path": str(target.resolve())})
        timed(stages, "adoption_s", adopt)
    else:
        stages["adoption_s"] = None
    total = time.perf_counter() - start
    return {"method": method, "width": width, "seed": seed, "mode": mode, **fitted,
            "scope": "full_parent_parameters" if method == "full_bp" else
            "rank_two_bilinear_readout_adapter" if method == "adapter_bp" else "identical_fixed_feature_readout",
            "trainable_parameters": sum(v.size for v in p.values()), "stages": stages,
            "local_end_to_end_s": total, "process_cpu_s": time.process_time() - cpu,
            "unattributed_local_overhead_s": total - sum(v for v in stages.values() if v is not None),
            "quality_gate": "PASS" if passed else "FAIL", "test_mse": mse,
            "parent_test_mse": baseline, "quality_threshold_mse": args.quality_mse,
            "regularized_gram_condition": condition, "candidate_sha256": digest,
            "candidate_bytes": candidate.stat().st_size,
            "parent_parameter_sha256": hashlib.sha256(parent["U"].tobytes() + parent["V"].tobytes()).hexdigest(),
            "fixture_sha256": sha(path), "adoption_scope": "local_filesystem_mock_only",
            "remote_transfer_s": None, "remote_transfer_status": "NOT_MEASURED",
            "actual_hepta_runtime_adoption": False, "energy_joules": None}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--widths", default="8,16,32,64")
    parser.add_argument("--seeds", default="0,1,2")
    parser.add_argument("--budget", type=float, default=.25)
    parser.add_argument("--steps", type=int, default=4000)
    parser.add_argument("--ridge", type=float, default=.001)
    parser.add_argument("--quality-mse", type=float, default=.0008)
    args = parser.parse_args()
    root, rows = Path(args.root).resolve(), []
    checked = gradient_check()
    prereg = {"schema": "pft6.preregister.v1", "created_utc": datetime.now(timezone.utc).isoformat(),
              "arguments": vars(args), "methods": METHODS, "gradient_checks": checked,
              "source_sha256": sha(__file__),
              "dataset_kind": "synthetic_control", "timing_clock": "perf_counter",
              "fixture_generation_excluded": True, "os_page_cache_not_flushed": True,
              "equal_budget_definition": "same maximum fit wall budget and step cap; one-pass algorithms finish naturally",
              "quality_definition": "dev stopping threshold plus independent final test MSE threshold",
              "timing_limit": "single-host millisecond microbenchmark; no statistical speedup guarantee",
              "method_order_randomized_per_seed_width_mode": True}
    dump(root / "preregistered_protocol.json", prereg)
    for width in map(int, args.widths.split(",")):
        for seed in map(int, args.seeds.split(",")):
            case = root / f"w{width}_s{seed}"
            path = fixture(case, width, seed)
            for mode_idx, mode in enumerate(("equal_budget", "time_to_quality")):
                order = np.random.default_rng(seed + width + mode_idx * 71).permutation(METHODS)
                for method in order:
                    row = measure(path, case / mode / method, width, seed, str(method), mode, args)
                    rows.append(row)
                    dump(case / mode / method / "timing.json", row)
    summary = []
    for mode in ("equal_budget", "time_to_quality"):
        for method in METHODS:
            group = [r for r in rows if r["mode"] == mode and r["method"] == method]
            summary.append({"mode": mode, "method": method, "cases": len(group),
                            "quality_passes": sum(r["quality_gate"] == "PASS" for r in group),
                            "median_local_end_to_end_s": float(np.median([r["local_end_to_end_s"] for r in group])),
                            "median_test_mse": float(np.median([r["test_mse"] for r in group]))})
    result = {"experiment": "PFT6", "schema": "pft6.costs.v1", "protocol": prereg,
              "results": rows, "summary": summary,
              "real_distributed_cost_gate": "BLOCKED_REMOTE_TRANSFER_AND_RUNTIME_ADOPTION_UNMEASURED",
              "conclusion": "Local synthetic microbenchmark; retain all quality failures; no remote or foundation-model speed claim."}
    dump(args.out, result)
    print(json.dumps({"gradient_checks": checked, "summary": summary}, indent=2))


if __name__ == "__main__":
    main()
