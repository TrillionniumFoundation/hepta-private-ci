"""Independent selected-point audit of the nine-coordinate finite financial law.

No candidate, verifier, or reference imports.  The boundary uses an unbounded
Laplace/Mills-ratio integral, adaptive tanh-sinh quadrature, and complex steps.
The complete output law is differentiated as a whole, without hand-coded array
derivatives.  Formal indices are fixed here before their points are opened.
"""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import resource
import subprocess
import time

import mpmath as mp


PARAMETERS = ("r", "delta", "alpha", "tax", "coupon", "principal", "sigma",
              "liquidity", "maturity")
FORMAL_INDICES = (0, 127, 255, 383, 511, 512, 543, 575, 594)
OLD_POINTS = (
    (.08, .02, .6, .27, 6.39, 61.68, .15, .002, .5),
    (.08, .02, .6, .27, 6.39, 61.68, .4, .04, 2.),
    (.08, .02, .6, .27, 6.39, 61.68, .3, .02, 1.3),
)
VALUE_ATOL, VALUE_RTOL = 2e-10, 2e-12
JACOBIAN_ATOL, JACOBIAN_RTOL = 2e-9, 2e-11
HIGH_PRECISION_CONSISTENCY = mp.mpf("1e-40")


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def b_laplace(z, scale, y):
    """B = s phi(ys) integral u exp(-u²/2-zsu) exprel((z+y)su) du.

    This follows by representing both Gaussian probabilities with the Mills
    integral, subtracting the two exponentials analytically, then using exprel.
    It needs neither normal probabilities nor a divided difference of them.
    """
    def integrand(u):
        w = (z + y) * scale * u
        exprel = mp.expm1(w) / w if w else mp.mpf(1)
        return u * mp.exp(-u*u/2 - z*scale*u) * exprel

    integral = mp.quad(integrand, [0, 1, 2, 4, 8, mp.inf], method="tanh-sinh")
    return scale * mp.exp(-(y*scale)**2/2) * integral / mp.sqrt(2*mp.pi)


def independent_boundary(theta):
    r, delta, alpha, tax, coupon, principal, sigma, liquidity, maturity = theta
    variance = sigma**2
    total_rate = r + liquidity
    drift_ratio = (r - delta) / variance - mp.mpf(1)/2
    root = mp.sqrt(drift_ratio**2 + 2*r/variance)
    liquid_root = mp.sqrt(drift_ratio**2 + 2*total_rate/variance)
    eta, gamma = root - drift_ratio, root + drift_ratio
    scale = sigma * mp.sqrt(maturity)
    coupon_rate = coupon / maturity
    debt_rate = principal / maturity - coupon_rate / total_rate
    discount = mp.exp(-total_rate*maturity)
    after_tax_cost = (1-tax)*coupon + (1-discount)*debt_rate
    liquid_B = sum(b_laplace(root, scale, sign*liquid_root) for sign in (-1, 1))
    drift_B = sum(b_laplace(root, scale, sign*drift_ratio) for sign in (-1, 1))
    numerator = (after_tax_cost/eta + debt_rate*discount*drift_B
                 + coupon_rate/total_rate*liquid_B)
    denominator = variance*(gamma+1)/2 + alpha/maturity*liquid_B
    return numerator / denominator


def independent_law(theta, lower=None):
    """Construct every value by row formulas and negative row sums.

    The interpolation interval is selected at the real point and held fixed
    for a complex perturbation, as required for a local ordinary derivative.
    """
    boundary = independent_boundary(theta)
    reset = mp.log(90/boundary)
    if lower is None:
        centers = [mp.mpf(2*k+1)/20 for k in range(8)]
        lower = sum(center < reset for center in centers)-1
        if not 0 <= lower <= 6 or any(abs(reset-x) < mp.mpf("1e-25") for x in centers):
            raise ValueError("Independent real reset is outside a smooth interval")
    fraction = 10*reset - mp.mpf(2*lower+1)/2
    weights = [mp.mpf(0) for _ in range(8)]
    weights[lower], weights[lower+1] = 1-fraction, fraction
    r, delta, _, _, _, _, sigma, _, _ = theta
    variance = sigma**2
    right_rate = (mp.mpf(95)*variance + 10*(r-delta))/2
    left_rate = (mp.mpf(105)*variance - 10*(r-delta))/2
    killing_rate = 100*variance
    recovery = mp.mpf(40)/7
    generator = []
    for state in range(40):
        row = [mp.mpf(0) for _ in range(40)]
        phase, label = divmod(state, 4)
        if phase < 8:
            if phase < 7:
                row[state+4] = right_rate
            row[state-4 if phase else 32+label] = left_rate if phase else killing_rate
        elif phase == 8:
            row[36+label] = recovery
        else:
            for destination in range(32):
                target_phase, target_label = divmod(destination, 4)
                retention = mp.mpf(7)/8 if target_label == label else mp.mpf(1)/24
                row[destination] = recovery * retention * weights[target_phase]
        row[state] = -sum(row)
        generator.extend(row)
    read = [mp.mpf(int(observation == 4)) if state >= 32 else
            (mp.mpf(0) if observation == 4 else
             (mp.mpf(7)/10 if observation == state % 4 else mp.mpf(1)/10))
            for state in range(40) for observation in range(5)]
    refresh = [mp.mpf(97)/100 if observation == state % 4 else mp.mpf(1)/100
               for state in range(40) for observation in range(4)]
    prior = [weights[state//4]/4 if state < 32 else mp.mpf(0) for state in range(40)]
    return [boundary] + generator + read + refresh + prior, lower


def complex_step_law(theta, digits, step_text):
    with mp.workdps(digits):
        point = [mp.mpf(float(value)) for value in theta]
        values, lower = independent_law(point)
        step = mp.mpf(step_text)
        jacobian = []
        for coordinate in range(9):
            perturbed = point.copy()
            perturbed[coordinate] += mp.j*step
            complex_values, _ = independent_law(perturbed, lower)
            jacobian.append([mp.im(value)/step for value in complex_values])
        return values, jacobian, lower


def compare(actual, expected, atol, rtol):
    if len(actual) != len(expected):
        raise ValueError("Independent comparison length mismatch")
    errors = [abs(mp.mpf(a)-b)/(atol+rtol*abs(b)) for a, b in zip(actual, expected)]
    index = max(range(len(errors)), key=errors.__getitem__)
    return dict(maximum_normalized_error=float(errors[index]), index=index,
                maximum_absolute_error=float(max(abs(mp.mpf(a)-b) for a, b in zip(actual, expected))))


def audit_case(index, theta, native, original_reference=None):
    low_values, low_jacobian, low_lower = complex_step_law(theta, 80, "1e-25")
    values, jacobian, lower = complex_step_law(theta, 90, "1e-35")
    with mp.workdps(90):
        precision_error = max([abs(a-b)/(1+abs(b)) for a, b in zip(low_values, values)] +
                              [abs(a-b)/(1+abs(b)) for arow, brow in zip(low_jacobian, jacobian)
                               for a, b in zip(arow, brow)])
        vm = compare(native["values"], values, VALUE_ATOL, VALUE_RTOL)
        if len(native["jacobian"]) != 9:
            raise ValueError("Expected all nine Jacobian rows")
        jm = [compare(actual, gold, JACOBIAN_ATOL, JACOBIAN_RTOL)
              for actual, gold in zip(native["jacobian"], jacobian)]
        result = dict(index=index, theta=theta, lower=lower, value_comparison=vm,
                      jacobian_comparisons=jm,
                      precision_consistency_normalized=mp.nstr(precision_error, 20),
                      boundary_decimal=mp.nstr(values[0], 85),
                      boundary_derivatives_decimal=[mp.nstr(row[0], 85) for row in jacobian])
        if original_reference is not None:
            result["original_reference_values"] = compare(original_reference["values"], values,
                                                          VALUE_ATOL, VALUE_RTOL)
            result["original_reference_jacobian"] = [
                compare(actual, gold, JACOBIAN_ATOL, JACOBIAN_RTOL)
                for actual, gold in zip(original_reference["jacobian"], jacobian)]
        result["passed"] = (len(values) == 2001 and native["lower"] == lower == low_lower
                            and vm["maximum_normalized_error"] <= 1
                            and all(row["maximum_normalized_error"] <= 1 for row in jm)
                            and precision_error <= HIGH_PRECISION_CONSISTENCY)
        if original_reference is not None:
            result["passed"] = (result["passed"] and
                result["original_reference_values"]["maximum_normalized_error"] <= 1 and
                all(row["maximum_normalized_error"] <= 1 for row in result["original_reference_jacobian"]))
        return result


def load_formal(directory):
    """Validate frozen registration before reading any formal raw row."""
    here = Path(__file__).resolve().parent
    protocol = json.loads((here/"PROTOCOL.json").read_text())
    if protocol["independent_math_selected_indices"] != list(FORMAL_INDICES):
        raise ValueError("Formal independent selection does not match preregistration")
    publication = json.loads((here/"PUBLICATION.json").read_text())
    summary = json.loads((directory/"SUMMARY.json").read_text())
    identities = {name: sha256(here/name) for name in protocol["sources"]}
    if (not publication["readback_verified"] or publication["source_sha256"] != identities
            or summary["source_sha256"] != identities or not summary["passed"]):
        raise ValueError("Formal publication/source/campaign gate failed before raw access")
    if identities.get("independent_math.py") != sha256(Path(__file__).resolve()):
        raise ValueError("Independent math script was not included in the source freeze")
    selected = []
    seen = 0
    with gzip.open(directory/"RAW.jsonl.gz", "rt") as stream:
        for index, line in enumerate(stream):
            seen += 1
            if index in FORMAL_INDICES:
                row = json.loads(line)
                if "failure" in row:
                    raise ValueError("Selected campaign point failed")
                selected.append((index, row["theta"], row["native"], row["reference"]))
    if seen != 595 or [row[0] for row in selected] != list(FORMAL_INDICES):
        raise ValueError("Formal roster count or fixed selection mismatch")
    return selected, dict(raw_gzip_sha256=sha256(directory/"RAW.jsonl.gz"),
                          source_sha256=identities, mode="formal_fixed_selected_raw")


def main():
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--binary", type=Path, help="Development: run only the three fixed OLD points")
    group.add_argument("--raw", type=Path, help="Formal: fixed preregistered raw indices after publication")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    start_wall, start_cpu = time.monotonic(), time.process_time()
    child_start = resource.getrusage(resource.RUSAGE_CHILDREN)
    if args.raw:
        selected, provenance = load_formal(args.raw)
    else:
        points = [list(row) for row in OLD_POINTS]
        call = subprocess.run([str(args.binary.resolve())], capture_output=True, text=True,
                              input="".join(" ".join(map(repr, point))+"\n" for point in points))
        call.check_returncode()
        native_rows = [json.loads(line) for line in call.stdout.splitlines()]
        if len(native_rows) != len(points):
            raise ValueError("Development native row count mismatch")
        selected = [(index, point, native, None) for index, (point, native) in enumerate(zip(points, native_rows))]
        provenance = dict(mode="development_old_points_only", binary_sha256=sha256(args.binary))
    cases = []
    for index, theta, native, reference in selected:
        result = audit_case(index, theta, native, reference)
        cases.append(result)
        print(json.dumps(dict(index=index, passed=result["passed"],
                              value=result["value_comparison"]["maximum_normalized_error"],
                              jacobian=max(x["maximum_normalized_error"] for x in result["jacobian_comparisons"])),
                         sort_keys=True), flush=True)
    child_end = resource.getrusage(resource.RUSAGE_CHILDREN)
    report = dict(passed=all(row["passed"] for row in cases), cases=cases, provenance=provenance,
                  parameter_order=PARAMETERS, preregistered_formal_indices=FORMAL_INDICES,
                  script_sha256=sha256(Path(__file__).resolve()), mpmath_version=mp.__version__,
                  precision_pairs=[dict(dps=80, imaginary_step="1e-25"), dict(dps=90, imaginary_step="1e-35")],
                  precision_consistency_tolerance="1e-40", value_positions=len(cases)*2001,
                  jacobian_positions=len(cases)*9*2001,
                  timing=dict(body_wall_seconds=time.monotonic()-start_wall,
                              body_parent_cpu_seconds=time.process_time()-start_cpu,
                              child_cpu_seconds=child_end.ru_utime+child_end.ru_stime-child_start.ru_utime-child_start.ru_stime),
                  cost_scope="Body after imports; full external process receipt must be retained separately.",
                  scope="Selected local finite-law Jacobians; no uniform box proof, PDE/neural training, full financial channels, or production qualification.")
    with args.output.open("x") as stream:
        json.dump(report, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    print(json.dumps(dict(passed=report["passed"], cases=len(cases), script_sha256=report["script_sha256"])), flush=True)
    raise SystemExit(not report["passed"])


if __name__ == "__main__":
    main()
