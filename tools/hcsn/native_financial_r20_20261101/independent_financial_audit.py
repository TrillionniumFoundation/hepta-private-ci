"""Independent adaptive Gaussian/B integrals and structural finite-law audit.

Does not import the project verifier, R11/R12 numerical implementation or its
high-precision quotient helper. Selected boundaries use adaptive 90-digit
Gaussian-density and derivative integrals, rather than native fixed quadrature.
"""

import argparse
import gzip
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
import time

sys.path.insert(0, "/tmp/hcsn-mpmath")
import mpmath as mp


def gaussian_tail(u):
    return mp.quad(lambda v: mp.exp(-v * v / 2), [u, u + 1, u + 4, mp.inf]) / mp.sqrt(2 * mp.pi)


def gaussian_cdf(x):
    return gaussian_tail(-x) if x < 0 else mp.mpf(".5") + mp.quad(lambda v: mp.exp(-v * v / 2), [0, x]) / mp.sqrt(2 * mp.pi)


def adaptive_boundary(theta):
    sigma, liquidity, maturity = [mp.mpf(float(x)) for x in theta]
    r, delta, alpha, tax, coupon, principal = [mp.mpf(x) for x in (".08", ".02", ".60", ".27", "6.39", "61.68")]
    variance, rate = sigma ** 2, r + liquidity
    drift = (r - delta - variance / 2) / variance
    z = mp.sqrt(drift ** 2 + 2 * r / variance)
    zt = mp.sqrt(drift ** 2 + 2 * rate / variance)
    scale = sigma * mp.sqrt(maturity)
    tail = gaussian_tail(z * scale)

    def slope(y):
        return scale * mp.exp(-(y * scale) ** 2 / 2) / mp.sqrt(2 * mp.pi) + y * scale ** 2 * mp.exp((z ** 2 - y ** 2) * scale ** 2 / 2) * tail

    def integral(y):
        return mp.quad(lambda t: slope(-z + t * (z + y)), [0, mp.mpf(".5"), 1])

    identity = []
    for y in (-zt, zt, -drift, drift, -z - mp.mpf("1e-20"), -z + mp.mpf("1e-20")):
        quotient = (gaussian_cdf(y * scale) - mp.exp((z ** 2 - y ** 2) * scale ** 2 / 2) * tail) / (z + y)
        identity.append(abs(quotient - integral(y)))
    identity.append(abs(integral(-z) - slope(-z)))
    bs = integral(-zt) + integral(zt)
    ba = integral(-drift) + integral(drift)
    c = coupon / maturity
    balance = principal / maturity - c / rate
    cost = (1 - tax) * coupon + (1 - mp.exp(-rate * maturity)) * balance
    value = (cost / (z - drift) + balance * mp.exp(-rate * maturity) * ba + c / rate * bs) / (variance * (z + drift + 1) / 2 + alpha / maturity * bs)
    return value, max(identity), abs((z - drift) * (z + drift) - 2 * r / variance)


def structural(native, theta):
    boundary = native[0]
    q = [native[1 + i * 40:1 + (i + 1) * 40] for i in range(40)]
    read = [native[1601 + i * 5:1601 + (i + 1) * 5] for i in range(40)]
    refresh = [native[1801 + i * 4:1801 + (i + 1) * 4] for i in range(40)]
    prior = native[1961:]
    assert len(native) == 2001 and all(math.isfinite(v) for v in native)
    assert all(q[i][j] >= 0 for i in range(40) for j in range(40) if i != j)
    errors = [max(abs(sum(row)) for row in q), abs(sum(prior) - 1)]
    weights = [sum(prior[4 * k:4 * k + 4]) for k in range(8)]
    support = [k for k, w in enumerate(weights) if w > 0]
    assert len(support) == 2 and support[1] == support[0] + 1 and min(prior) >= 0
    errors.append(abs(sum((k + .5) * .1 * w for k, w in enumerate(weights)) - math.log(90 / boundary)))
    diffusion, spacing = theta[0] ** 2 / 2, .1
    drift = .08 - .02 - diffusion
    up, down, absorption = diffusion / spacing ** 2 + drift / (2 * spacing), diffusion / spacing ** 2 - drift / (2 * spacing), 2 * diffusion / spacing ** 2
    for state in range(40):
        mode, phase = state % 4, state // 4
        expected = [0.] * 40
        if phase < 8:
            if phase < 7:
                expected[state + 4] = up
            expected[state - 4 if phase > 0 else 32 + mode] = down if phase > 0 else absorption
            errors += [abs(prior[state] - weights[phase] / 4)]
        elif phase == 8:
            expected[36 + mode] = 2 / .35
        else:
            for target_phase, weight in enumerate(weights):
                for label in range(4):
                    expected[4 * target_phase + label] = 2 / .35 * weight * (.875 if label == mode else .125 / 3)
        expected[state] = -sum(expected)
        errors.append(max(abs(a - b) for a, b in zip(q[state], expected)))
        errors.append(max(abs(value - (.7 if label == mode else .1) if phase < 8 and label < 4 else value - (1. if phase >= 8 and label == 4 else 0.)) for label, value in enumerate(read[state])))
        errors.append(max(abs(value - (.97 if label == mode else .01)) for label, value in enumerate(refresh[state])))
        errors += [abs(sum(read[state]) - 1), abs(sum(refresh[state]) - 1)]
    return max(errors)


def run():
    start = time.process_time()
    root = Path(__file__).resolve().parent
    frozen = json.loads((root / "SOURCE_FREEZE.json").read_text())["files"]
    assert all(hashlib.sha256((root / path).read_bytes()).hexdigest() == digest for path, digest in frozen.items())
    inherited = json.loads((root / "REFERENCE_IDENTITIES.json").read_text())["files"]
    assert all(hashlib.sha256((root.parents[2] / path).read_bytes()).hexdigest() == digest for path, digest in inherited.items())
    r12 = json.loads((root.parents[2] / "tools/hcsn/unified_cell_r12_20261031/PROTOCOL.json").read_text())
    fixed = [r12["baseline_financial_parameters"][j] for j in (0, 1, 3, 4, 7, 8)]
    assert fixed == [.08, .02, .6, .27, 6.39, 61.68]
    payload_bytes = gzip.decompress((root / "confirmation_01/RAW.json.gz").read_bytes())
    payload = json.loads(payload_bytes)
    summary = json.loads((root / "confirmation_01/SUMMARY.json").read_text())
    assert hashlib.sha256(payload_bytes).hexdigest() == summary["raw_sha256"]
    binary = root / "confirmation_01/financial"
    assert hashlib.sha256(binary.read_bytes()).hexdigest() == summary["binary_sha256"]
    indices = list(range(8)) + [8, 23, 47, 71]
    boundaries, cdf, bounds = [], [], []
    with mp.workdps(90):
        for index in indices:
            case = payload["models"][index]
            value, identity_error, factor_error = adaptive_boundary(case["theta"])
            boundaries.append(dict(index=index, theta=case["theta"], adaptive_boundary=mp.nstr(value, 85),
                native=case["native"][0], native_absolute_error=float(abs(value - case["native"][0])),
                original_mp_float=case["mp_boundary"], original_mp_absolute_error=float(abs(value - case["mp_boundary"])),
                maximum_B_identity_error=mp.nstr(identity_error, 12), eta_gamma_identity_error=mp.nstr(factor_error, 12)))
        for target in (-12., -11.75, -8., -4., -.25, 0., .25, 8., 12.):
            case = next(row for row in payload["cdf"] if row["x"] == target)
            gold = gaussian_cdf(mp.mpf(target))
            cdf.append(dict(x=target, adaptive_cdf=mp.nstr(gold, 85), native=case["native"],
                relative_error=float(abs(case["native"] - gold) / gold),
                true_complement=mp.nstr(1 - gold, 25), native_complement=1 - case["native"]))
        absolute_bound = mp.erfc(12 / mp.sqrt(2)) / 2
        for u in (0, .25, 2, 12):
            omitted = mp.erfc((12 + mp.mpf(u)) / mp.sqrt(2)) / 2
            bounds.append(dict(u=u, exact_omitted_mass=mp.nstr(omitted, 25), absolute_upper_bound=mp.nstr(absolute_bound, 25), bound_holds=bool(omitted <= absolute_bound)))
    structural_errors = [structural(row["native"], row["theta"]) for row in payload["models"]]
    guards = []
    for argument in ("-12.0001", "12.0001", "nan", "inf", "-inf"):
        call = subprocess.run([str(binary), "cdf", argument], capture_output=True)
        guards.append(dict(argument=argument, returncode=call.returncode, stdout=call.stdout.decode(), stderr=call.stderr.decode(),
                           passed=call.returncode == 2 and not call.stdout))
    # Drive a valid parameter into an actual reset knot; the formal seven
    # negatives only exercised box faces/NaN, not this interior guard.
    low, high, knot_trace = .5, 2., []
    for _ in range(60):
        maturity = (low + high) / 2
        call = subprocess.run([str(binary), ".15", ".002", repr(maturity)], capture_output=True)
        row = dict(maturity=maturity, returncode=call.returncode, stdout_sha256=hashlib.sha256(call.stdout).hexdigest(), stderr=call.stderr.decode())
        if call.returncode:
            knot_trace.append(row)
            break
        boundary = json.loads(call.stdout)[0]
        distance = math.log(90 / boundary)
        row.update(boundary=boundary, reset_distance=distance)
        knot_trace.append(row)
        if distance < .35:
            low = maturity
        else:
            high = maturity
    knot_rejected = knot_trace[-1]["returncode"] == 2 and "reset interpolation knot" in knot_trace[-1]["stderr"]
    gates = dict(selected_adaptive_boundaries=max(r["native_absolute_error"] for r in boundaries) <= 2e-11,
        selected_adaptive_cdf=max(r["relative_error"] for r in cdf) <= 2e-13,
        B_identity=max(float(r["maximum_B_identity_error"]) for r in boundaries) <= 1e-55,
        structural_all72=max(structural_errors) <= 2e-11, cdf_guards=all(r["passed"] for r in guards),
        exact_tail_bound=all(r["bound_holds"] for r in bounds), actual_interior_knot_rejection=knot_rejected)
    return dict(schema="hcsn-r20-independent-financial-review-v1", reviewed_source_checkpoint="aebb58339dda8010888569d78d29cfdb226bb712",
        source_sha256=frozen, verified_inherited_identities=inherited, six_fixed_parameters=fixed,
        audit_source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        raw_sha256=summary["raw_sha256"], binary_sha256=summary["binary_sha256"], gates=gates, passed=all(gates.values()),
        boundaries=boundaries, normal_cdf=cdf, tail_bounds=bounds, structural_maximum_error=max(structural_errors), cdf_guards=guards,
        interior_knot_trace=knot_trace,
        mathematical_findings=["N(-z)=0 and B(y)=integral_0^1 N'(-z+t(z+y))dt, including the removable y=-z limit",
            "Truncating the shifted normal integral at12 omits exactly Phi(-(u+12)), at most Phi(-12)",
            "eta=z-a and gamma=z+a; rationalized native forms use z^2-a^2=2r/sigma^2",
            "Native row generator is a synthetic eight-active/two-recovery phase, four-content extension; six other financial parameters remain fixed"],
        cost_scope="Audit inner CPU after imports through all calculations/guard calls, excluding final output serialization; outer process receipt is authoritative complete audit cost",
        inner_cpu_seconds=time.process_time() - start, mpmath_version=mp.__version__, decimal_precision=90,
        qualification="Finite selected independent adaptive calculations plus all72 native structural arrays; not all-box FP64/quadrature proof, full equity/debt, continuous financial/neural solution, full gradients or production qualification")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = run()
    with args.out.open("x") as stream:
        json.dump(result, stream, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps(dict(passed=result["passed"], gates=result["gates"], inner_cpu_seconds=result["inner_cpu_seconds"]), indent=2))
    raise SystemExit(0 if result["passed"] else 1)
