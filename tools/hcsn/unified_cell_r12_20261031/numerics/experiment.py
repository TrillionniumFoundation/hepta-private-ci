"""Fixed failure replay, explicit-domain numerical audit, and CPU cost study."""

import argparse
import gzip
import hashlib
import importlib.util
import json
import platform
import time
from pathlib import Path

import numpy as np
import scipy
from mpmath import mp

import stable32

ROOT, UP = Path(__file__).resolve().parent, stable32.UPSTREAM
RESULTS_ROOT = ROOT
spec = importlib.util.spec_from_file_location("r11_literal_reference", UP / "reference.py")
reference = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reference)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, obj):
    path = RESULTS_ROOT / path.name
    if path.exists():
        raise ValueError(f"Refusing to overwrite {path}")
    path.write_text(json.dumps(obj, indent=2, allow_nan=False) + "\n")


def prepare():
    index = json.loads((UP / "EVIDENCE_ARCHIVE.json").read_text())
    member = next(x for x in index["members"] if x["member"] == "FINAL_RESULTS.json")
    raw = b"".join(gzip.decompress((UP / c["path"]).read_bytes()) for c in member["chunks"])
    assert hashlib.sha256(raw).hexdigest() == member["sha256"]
    old = sorted((x for x in json.loads(raw)["rows"] if x["mode"] == "float32"),
                 key=lambda x: x["jacobian_error"], reverse=True)[:12]
    rows = [dict(name="r11_failure_" + str(i), origin=x["case"], theta=x["quantized_theta"],
                 state=x["state"], coordinate=x["coordinate"], prior_error=x["jacobian_error"])
            for i, x in enumerate(old)]
    configurations = [("baseline", {}), ("small_noise", {2: .08}),
                      ("short_maturity", {6: .01}), ("near_zero_liquidity", {5: 1e-4}),
                      ("joint_corner", {2: .08, 5: 1e-4, 6: .01}),
                      ("extension_sigma", {2: .02}), ("extension_maturity", {6: 1e-4}),
                      ("extension_liquidity", {5: 1e-8}), ("extension_zero_liquidity", {5: 0.})]
    for name, edits in configurations:
        theta = stable32.k.BASE.copy()
        for i, value in edits.items():
            theta[i] = value
        for x in (1e-8, .001, .1, 2.):
            rows.append(dict(name=f"{name}_{x}", origin="fixed_extension", theta=theta.tolist(),
                             state=x, coordinate="log_distance"))
    write(ROOT / "PROTOCOL.json", dict(schema="full-hx-r12-fp32-fixed-v1", rows=rows,
          purpose="Development failure repair, not an unseen performance holdout",
          reference_digits=80, derivative_steps=["1e-18", "5e-19"],
          gates=dict(value32=8e-7, value64=2e-8, jacobian=2e-5, reference_halving=1e-12),
          original_archive_sha256=member["sha256"],
          source_sha256={n: sha(UP / n) for n in ("kernel.py", "reference.py")},
          batch_sizes=[64, 256, 1024, 4096], benchmark_state_cycle=[.001, .1, 1., 2.],
          benchmarking="Scalar loop batches, serial CPU; no GPU/vectorization claim"))


def fields(theta, state, coordinate, zero_step="1e-30"):
    if theta[5] != 0:
        return reference.fields(theta, state, coordinate)
    # Independently continue the literal formula through its removable q=r
    # singularity by a symmetric 80-digit limit; never use candidate algebra.
    ctx = mp.clone()
    ctx.dps = 80
    a, b = list(theta), list(theta)
    a[5], b[5] = ctx.mpf(zero_step), -ctx.mpf(zero_step)
    return [(x + y) / 2 for x, y in zip(reference.fields(a, state, coordinate),
                                      reference.fields(b, state, coordinate))]


def jac(theta, state, coordinate, step):
    ctx = mp.clone()
    ctx.dps = 80
    values = [ctx.mpf(str(float(v))) for v in theta] + [ctx.mpf(str(float(state)))]
    columns = []
    for i, v in enumerate(values):
        h = ctx.mpf(step) * max(ctx.mpf(".01"), abs(v))
        plus, minus = values.copy(), values.copy()
        plus[i], minus[i] = v + h, v - h
        columns.append([float((a - b) / (2 * h)) for a, b in
                        zip(fields(plus[:9], plus[-1], coordinate), fields(minus[:9], minus[-1], coordinate))])
    return np.array(columns).T


def error(a, b):
    return float(np.max(np.abs(a - b) / np.maximum(1., np.abs(b))))


def audit(tag):
    started = time.perf_counter()
    protocol = json.loads((ROOT / "PROTOCOL.json").read_text())
    source = (ROOT / "stable32.py").read_bytes()
    (RESULTS_ROOT / f"{tag}_source.py.gz").write_bytes(gzip.compress(source, mtime=0))
    rows = []
    for fixture in protocol["rows"]:
        theta = np.asarray(fixture["theta"], np.float32).astype(float)
        state, coordinate = float(np.float32(fixture["state"])), fixture["coordinate"]
        in_box = bool(np.all(theta >= stable32.k.LOWER.astype(np.float32).astype(float))
                      and np.all(theta <= stable32.k.UPPER.astype(np.float32).astype(float)))
        expected = np.asarray(fields(theta, state, coordinate), float)
        ref_jac, half = jac(theta, state, coordinate, "1e-18"), jac(theta, state, coordinate, "5e-19")
        base = dict(**fixture, represented_theta=theta.tolist(), represented_state=state,
                    inside_unchanged_box=in_box, reference=expected.tolist(), reference_jacobian=half.tolist(),
                    reference_halving_error=error(ref_jac, half))
        if theta[5] == 0:
            base["reference_zero_limit_error"] = error(expected, np.asarray(fields(theta, state, coordinate, "1e-20"), float))
        modes = [("original32", "float32", False), ("candidate32", "float32", True),
                 ("original_mixed", "mixed32", False), ("candidate64", "float64", True)]
        measured = []
        for label, mode, candidate in modes:
            row = dict(base, mode=label)
            start = time.perf_counter()
            try:
                v, j = stable32.evaluate(theta, state, coordinate=coordinate, mode=mode,
                                         candidate=candidate, diagnostic_outside_box=True)
                if not np.all(np.isfinite(v)) or not np.all(np.isfinite(j)):
                    raise ValueError("Nonfinite value or Jacobian")
                ve, je = error(v, expected), error(j, half)
                gate = protocol["gates"]["value64" if mode == "float64" else "value32"]
                row.update(actual=v.tolist(), jacobian=j.tolist(), value_error=ve, jacobian_error=je,
                           passed=bool(ve <= gate and je <= 2e-5 and base["reference_halving_error"] <= 1e-12))
            except (ValueError, ArithmeticError) as e:
                row.update(passed=False, error=str(e))
            row["elapsed_seconds"] = time.perf_counter() - start
            rows.append(row)
            measured.append(f"{label}:{row.get('value_error',-1):.2g}/{row.get('jacobian_error',-1):.2g}")
        print(fixture["name"], " ".join(measured), flush=True)
    summary = {}
    for label in ("original32", "candidate32", "original_mixed", "candidate64"):
        for domain in (True, False):
            part = [r for r in rows if r["mode"] == label and r["inside_unchanged_box"] == domain]
            summary[f"{label}_{'box' if domain else 'extension'}"] = dict(rows=len(part),
                passed=sum(r["passed"] for r in part), nonfinite_or_rejected=sum("error" in r for r in part),
                maximum_value_error=max((r.get("value_error", 0) for r in part), default=0),
                maximum_jacobian_error=max((r.get("jacobian_error", 0) for r in part), default=0))
    result = dict(protocol_sha256=sha(ROOT / "PROTOCOL.json"), candidate_sha256=hashlib.sha256(source).hexdigest(),
                  rows=rows, summary=summary, elapsed_seconds=time.perf_counter() - started,
                  environment=dict(python=platform.python_version(), numpy=np.__version__, scipy=scipy.__version__,
                                   platform=platform.platform(), processor=platform.processor()),
                  limits="Fixed development points only; extended inputs never admitted for training")
    write(ROOT / f"{tag}_RESULTS.json", result)
    write(ROOT / f"{tag}_SUMMARY.json", {k: v for k, v in result.items() if k != "rows"})
    print(json.dumps(summary, indent=2), flush=True)


def benchmark():
    if (RESULTS_ROOT / "CPU_BENCHMARK.json").exists():
        raise ValueError("Use --destination for a fresh evidence directory")
    protocol = json.loads((ROOT / "PROTOCOL.json").read_text())
    rows = []
    for label, mode, candidate in (("original32", "float32", False),
                                  ("candidate32", "float32", True),
                                  ("original_mixed", "mixed32", False)):
        for n in protocol["batch_sizes"]:
            states = np.resize(protocol["benchmark_state_cycle"], n)
            row = dict(mode=label, batch=n)
            for need_jac in (False, True):
                stable32.evaluate(stable32.k.BASE, states[0], mode=mode, candidate=candidate, jacobian=need_jac)
                start = time.perf_counter()
                checksum = 0.
                for state in states:
                    v, j = stable32.evaluate(stable32.k.BASE, state, mode=mode, candidate=candidate, jacobian=need_jac)
                    checksum += float(v.sum()) + (float(j.sum()) if need_jac else 0.)
                elapsed = time.perf_counter() - start
                row["full_value_and_jacobian" if need_jac else "forward_only"] = dict(
                    seconds=elapsed, microseconds_per_cell=1e6 * elapsed / n, checksum=checksum)
            rows.append(row)
            print(json.dumps(row), flush=True)
    write(ROOT / "CPU_BENCHMARK.json", dict(rows=rows, protocol_sha256=sha(ROOT / "PROTOCOL.json"),
          candidate_sha256=sha(ROOT / "stable32.py"), repetitions=1,
          caveat="Serial scalar loops, whole construction/field cost; no end-to-end task training or vectorized-kernel claim"))


def fit():
    """Diagnostic numerical-AD optimization; failure gates are not waived."""
    if (RESULTS_ROOT / "FIT_TIMING.json").exists():
        raise ValueError("Use --destination for a fresh evidence directory")
    states = [.001, .05, .1]
    teacher = stable32.k.BASE.copy()
    teacher[[2, 5, 6]] = [.3, .02, 1.4]
    target = np.asarray([reference.fields(teacher, x, "log_distance") for x in states], np.float32)
    scale = np.asarray([100, 100, 1, 1, 100], np.float32)
    lo, hi = stable32.k.LOWER[[2, 5, 6]].astype(np.float32), stable32.k.UPPER[[2, 5, 6]].astype(np.float32)
    runs = []
    for label, mode, candidate in (("candidate32", "float32", True), ("original_mixed", "mixed32", False)):
        theta = stable32.k.BASE.astype(np.float32)
        ratio = (theta[[2, 5, 6]] - lo) / (hi - lo)
        raw = np.log(ratio / (1 - ratio))
        first, second = np.zeros(3, np.float32), np.zeros(3, np.float32)
        trajectory = []
        start = time.perf_counter()
        for step in range(13):
            sigmoid = 1 / (1 + np.exp(-raw))
            theta[[2, 5, 6]] = lo + (hi - lo) * sigmoid
            values, tangents = zip(*(stable32.evaluate(theta, x, mode=mode, candidate=candidate) for x in states))
            values, tangents = np.asarray(values), np.asarray(tangents)
            residual = (values - target) / scale
            loss = np.mean(residual ** 2)
            gradient = np.sum(2 * residual[:, :, None] * tangents[:, :, [2, 5, 6]] / scale[None, :, None], axis=(0, 1)) / residual.size
            gradient *= (hi - lo) * sigmoid * (1 - sigmoid)
            trajectory.append(dict(step=step, loss=float(loss), theta=theta.tolist(), gradient=gradient.tolist()))
            if step < 12:
                first, second = .9 * first + .1 * gradient, .999 * second + .001 * gradient ** 2
                raw -= .04 * (first / (1 - .9 ** (step + 1))) / (np.sqrt(second / (1 - .999 ** (step + 1))) + 1e-8)
        runs.append(dict(mode=label, seconds=time.perf_counter() - start, trajectory=trajectory,
                         optimizer_dtype=str(raw.dtype), loss_reduction=1 - trajectory[-1]["loss"] / trajectory[0]["loss"]))
    write(ROOT / "FIT_TIMING.json", dict(runs=runs, states=states, teacher=teacher.tolist(), target=target.tolist(),
          scope="12 fixed FP32 Adam updates on full-HX analytic outputs; no recurrent/task training qualification",
          candidate_sha256=sha(ROOT / "stable32.py")))
    print(json.dumps([{k: v for k, v in r.items() if k != "trajectory"} for r in runs], indent=2), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("prepare", "audit", "benchmark", "fit"))
    parser.add_argument("--tag", default="DEVELOPMENT_01")
    parser.add_argument("--destination", type=Path, default=ROOT)
    args = parser.parse_args()
    RESULTS_ROOT = args.destination
    RESULTS_ROOT.mkdir(parents=True, exist_ok=True)
    if args.action == "prepare":
        prepare()
    elif args.action == "audit":
        audit(args.tag)
    elif args.action == "fit":
        fit()
    else:
        benchmark()
