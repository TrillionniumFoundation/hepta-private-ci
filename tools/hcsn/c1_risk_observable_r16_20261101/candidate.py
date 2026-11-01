"""Independent C1 boundary observable candidate; no frozen kernel or gate changes."""
import json
import math


def observables(v, b, alpha):
    """Return (E, R, dE/d(V,b,alpha), dR/d(V,b,alpha))."""
    if b <= 0 or alpha <= 0:
        raise ValueError("The example requires b>0 and alpha>0")
    if v <= b:
        return 0.0, 1.0, (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)
    x = (v - b) / b
    log_ratio = math.log1p(x)
    f = math.exp(-alpha * log_ratio)
    survival = -math.expm1(-alpha * log_ratio)
    e = (v - b) - b * survival / alpha
    r = f * (2.0 - f)
    df = (-alpha * f / v, alpha * f / b, -log_ratio * f)
    de = (
        -math.expm1(-(alpha + 1.0) * log_ratio),
        -(1.0 + 1.0 / alpha) * survival,
        b * (survival / alpha**2 - f * log_ratio / alpha),
    )
    dr = tuple(2.0 * survival * d for d in df)
    return e, r, de, dr


def centered_difference(point, coordinate, output, h):
    high, low = list(point), list(point)
    high[coordinate] += h
    low[coordinate] -= h
    return (observables(*high)[output] - observables(*low)[output]) / (2.0 * h)


def verify():
    errors = []
    for point in [(2.0, 1.3, 1.7), (3.2, 0.8, 0.6), (1.9, 1.2, 3.0)]:
        result = observables(*point)
        for output, gradient in [(0, result[2]), (1, result[3])]:
            for coordinate, expected in enumerate(gradient):
                actual = centered_difference(point, coordinate, output, 1e-5)
                errors.append(abs(actual - expected))
    assert max(errors) < 2e-8, errors

    b, alpha = 1.3, 1.7
    assert observables(b, b, alpha) == (
        0.0, 1.0, (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)
    )
    assert observables(b - 0.2, b, alpha) == (
        0.0, 1.0, (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)
    )
    boundary_rows = []
    for distance in [1e-2, 1e-3, 1e-4, 1e-5]:
        e, r, de, dr = observables(b + distance, b, alpha)
        norm = max(abs(t) for t in de + dr)
        assert norm < 5.0 * distance
        boundary_rows.append({
            "distance": distance,
            "max_joint_gradient": norm,
            "risk_gap": 1.0 - r,
            "equity": e,
        })
    boundary_difference = max(
        abs(centered_difference((b, b, alpha), c, output, 1e-5))
        for c in [0, 1, 2] for output in [0, 1]
    )
    assert boundary_difference < 3e-5

    sigma = 0.4
    mu = 0.5 * sigma**2 * (alpha + 1.0)
    pde_errors = []
    for v in [1.4, 2.0, 4.0]:
        f = (b / v)**alpha
        fv = -alpha * f / v
        fvv = alpha * (alpha + 1.0) * f / v**2
        rv = 2.0 * (1.0 - f) * fv
        rvv = -2.0 * fv**2 + 2.0 * (1.0 - f) * fvv
        lf = mu * v * fv + 0.5 * sigma**2 * v**2 * fvv
        lr = mu * v * rv + 0.5 * sigma**2 * v**2 * rvv
        pde_errors.append(abs(lf))
        pde_errors.append(abs(lr + sigma**2 * v**2 * fv**2))
    assert max(pde_errors) < 1e-14

    return {
        "candidate_only": True,
        "not_original_put_or_default_operator": True,
        "frozen_kernel_or_gates_changed": False,
        "max_interior_gradient_absolute_error": max(errors),
        "max_boundary_centered_difference_at_h_1e_5": boundary_difference,
        "boundary_approach": boundary_rows,
        "max_generator_identity_absolute_error": max(pde_errors),
        "scope": "Floating-point illustrative checks of the proved C1 wrapper and changed PDE; no network, quality, performance, energy or genuine-spike claim.",
    }


if __name__ == "__main__":
    print(json.dumps(verify(), indent=2))
