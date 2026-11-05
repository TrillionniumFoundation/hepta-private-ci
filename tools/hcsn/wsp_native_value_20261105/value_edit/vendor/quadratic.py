"""Two independently budgeted convex head groups, with matched PGD precision.

The continuation group has three different Hessian blocks and one shared
trust-region multiplier. Diagnostics are numerical; only stored-vector norm
membership is checked with exact rational arithmetic.
"""
from fractions import Fraction
import time
import numpy as np

LAMBDA = 1e-4
FW_TOLERANCE = 1e-8
MAX_STEPS = 100000


def fraction_sum(values):
    return sum((Fraction.from_float(float(v)) ** 2 for v in np.ravel(values)), Fraction(0))


def norm_certificate(candidate, original, radius):
    differences = [Fraction.from_float(float(a)) - Fraction.from_float(float(b))
                   for a, b in zip(np.ravel(candidate), np.ravel(original))]
    actual = sum((d * d for d in differences), Fraction(0))
    original_bound, safe_bound = fraction_sum(original) / 4, Fraction.from_float(float(radius)) ** 2
    def record(value):
        return {"numerator": str(value.numerator), "denominator": str(value.denominator)}
    return dict(actual_squared=record(actual), declared_squared=record(original_bound), safe_squared=record(safe_bound),
                within_declared=actual <= original_bound, within_safe=actual <= safe_bound)


def stored_point(original, delta, radius):
    candidate = np.asarray(original + delta, dtype=np.float64)
    proof = norm_certificate(candidate, original, radius)
    inward = False
    if not proof["within_safe"]:
        candidate = original + (candidate - original) * (1 - 1e-12)
        proof, inward = norm_certificate(candidate, original, radius), True
    if not proof["within_safe"] or not proof["within_declared"]:
        raise ArithmeticError("stored F64 candidate exceeds exact group budget")
    return candidate, proof, inward


def prepare(H, Y, W, original, mm):
    start, wall = time.process_time(), time.perf_counter()
    H, Y, W, original = map(lambda a: np.asarray(a, dtype=np.float64), (H, Y, W, original))
    if (H.ndim != 2 or H.shape[1] != 49 or original.shape[1] != 49
            or Y.shape != W.shape or Y.shape != (len(H), len(original))
            or np.any(W < 0) or not all(np.isfinite(a).all() for a in (H, Y, W, original))):
        raise ValueError("invalid fixed-feature grouped quadratic")
    matrices, rhs = [], []
    for j in range(len(original)):
        matrix = mm(H.T, W[:, j, None] * H) + LAMBDA * np.eye(49)
        matrices.append((matrix + matrix.T) * .5)
        rhs.append(mm(H.T, W[:, j] * (Y[:, j] - mm(H, original[j]))))
    matrices, rhs = np.asarray(matrices), np.asarray(rhs)
    spectral = [np.linalg.eigh(matrix) for matrix in matrices]
    values, vectors = np.asarray([x[0] for x in spectral]), np.asarray([x[1] for x in spectral])
    if values.min() <= 0 or not np.isfinite(values).all():
        raise ArithmeticError("quadratic not numerically SPD")
    radius = .5 * float(np.linalg.norm(original)) * (1 - 1e-8)
    if radius <= 0 or Fraction.from_float(radius) ** 2 > fraction_sum(original) / 4:
        raise ArithmeticError("invalid inward group radius")
    return dict(H=H, Y=Y, W=W, original=original, matrices=matrices, rhs=rhs, values=values,
                vectors=vectors, radius=radius, L=2 * float(values.max()),
                setup_cpu_seconds=time.process_time() - start, setup_wall_seconds=time.perf_counter() - wall)


def diagnostics(problem, candidate, mm):
    H, Y, W, original = [problem[k] for k in ("H", "Y", "W", "original")]
    delta = candidate - original
    residual = mm(H, candidate.T) - Y
    gradient = 2 * mm(H.T, W * residual).T + 2 * LAMBDA * delta
    gram_gradient = 2 * np.array([mm(a, d) - g for a, d, g in zip(problem["matrices"], delta, problem["rhs"])])
    data_loss = float(np.sum(W * residual ** 2))
    penalty = LAMBDA * float(np.sum(delta ** 2))
    gap = float(np.sum(gradient * delta) + problem["radius"] * np.linalg.norm(gradient))
    return dict(objective=data_loss + penalty, weighted_target_loss=data_loss, penalty=penalty,
                numerical_fw_gap=gap, gradient=gradient.tolist(), delta_norm=float(np.linalg.norm(delta)),
                gradient_original_data_vs_gram_linf=float(np.max(abs(gradient - gram_gradient))),
                certificate=norm_certificate(candidate, original, problem["radius"]),
                converged=bool(-1e-12 <= gap <= FW_TOLERANCE))


def direct(problem, mm, budget):
    start, wall = time.process_time(), time.perf_counter()
    values, vectors, rhs, radius = [problem[k] for k in ("values", "vectors", "rhs", "radius")]
    projected = [mm(v.T, g) for v, g in zip(vectors, rhs)]
    def point(mu):
        return np.asarray([mm(v, p / (e + mu)) for v, p, e in zip(vectors, projected, values)])
    delta = point(0.)
    mu, bisections = 0., 0
    if np.linalg.norm(delta) > radius:
        low, high = 0., max(1., float(np.linalg.norm(rhs)) / radius)
        if np.linalg.norm(point(high)) > radius:
            raise ArithmeticError("analytical multiplier bracket failed")
        for _ in range(160):
            middle = .5 * (low + high)
            if middle in (low, high):
                break
            if np.linalg.norm(point(middle)) > radius:
                low = middle
            else:
                high = middle
            bisections += 1
        mu, delta = high, point(high)
    candidate, _, inward = stored_point(problem["original"], delta, radius)
    report = diagnostics(problem, candidate, mm)
    actual = candidate - problem["original"]
    independent = []
    for matrix, g in zip(problem["matrices"], rhs):
        chol = np.linalg.cholesky(matrix + mu * np.eye(49))
        independent.append(np.linalg.solve(chol.T, np.linalg.solve(chol, g)))
    kkt = np.asarray(report["gradient"]) + 2 * mu * actual
    report.update(solver="block_spectral_secular_root", shared_multiplier=float(mu), bisections=bisections,
                  independent_cholesky_l2_difference=float(np.linalg.norm(np.asarray(independent) - actual)),
                  kkt_stationarity_linf=float(np.max(abs(kkt))),
                  complementarity_absolute=float(abs(mu * (np.sum(actual ** 2) - radius ** 2))),
                  storage_inward_applied=inward, gradient_steps=0,
                  cpu_seconds=time.process_time() - start, wall_seconds=time.perf_counter() - wall)
    budget()
    return candidate, report


def pgd(problem, mm, budget):
    start, wall = time.process_time(), time.perf_counter()
    matrices, rhs, radius = [problem[k] for k in ("matrices", "rhs", "radius")]
    delta, trace, repairs = np.zeros_like(rhs), [], 0
    for steps in range(MAX_STEPS + 1):
        if steps % 100 == 0:
            budget()
        gradient = 2 * np.array([mm(a, d) - g for a, d, g in zip(matrices, delta, rhs)])
        gap = float(np.sum(gradient * delta) + radius * np.linalg.norm(gradient))
        if steps % 1000 == 0 or gap <= FW_TOLERANCE or steps == MAX_STEPS:
            trace.append(dict(step=steps, numerical_gram_fw_gap=gap))
        if gap <= FW_TOLERANCE or steps == MAX_STEPS:
            candidate, _, inward = stored_point(problem["original"], delta, radius)
            repairs += int(inward)
            report = diagnostics(problem, candidate, mm)
            if report["converged"] or steps == MAX_STEPS:
                break
            delta = candidate - problem["original"]
            gradient = 2 * np.array([mm(a, d) - g for a, d, g in zip(matrices, delta, rhs)])
        delta -= gradient / problem["L"]
        length = float(np.linalg.norm(delta))
        if length > radius:
            delta *= radius / length
    report.update(solver="projected_gradient_1_over_L", steps=steps, maximum_steps=MAX_STEPS,
                  step_size=1 / problem["L"], L=problem["L"], storage_inward_count=repairs, trace=trace,
                  stop_reason="own_stored_FW_gap" if report["converged"] else "fixed_max_steps",
                  cpu_seconds=time.process_time() - start, wall_seconds=time.perf_counter() - wall)
    budget()
    return candidate, report
