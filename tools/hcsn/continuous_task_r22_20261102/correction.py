"""Admit only certified local derivatives; repair rounded branch selection."""

import math

from .certificate import certify
from .solver import solve


def evaluate(config, direction, dx, dt, planned_step=None, digits=50, tolerance=1e-10):
    if planned_step is not None and (not math.isfinite(planned_step) or planned_step < 0):
        raise ValueError("A finite nonnegative planned step is required")
    first = solve(config, direction, dx, dt)
    first_certificate = certify(first, digits, tolerance)
    tape, certificate = first, first_certificate
    corrected = False
    if not certificate["qualified"] and certificate["branch_certified"]:
        tape = solve(config, direction, dx, dt, certificate["plan"])
        certificate = certify(tape, digits, tolerance)
        corrected = True
    radius = certificate["safe_affine_step_radius"]
    safe_update = (planned_step is not None and planned_step >= 0 and certificate["qualified"]
        and certificate["affine_radius_certified"] and (radius is None or planned_step < radius))
    metadata = dict(certified_policy_correction_used=corrected,
        first_derivative_error_bound=first_certificate["maximum_derivative_enclosure_error"],
        first_policy_mismatches=first_certificate["policy_mismatches"],
        planned_step=planned_step, certified_affine_update=safe_update,
        scope="Local real-equation derivative. A finite step outside the certified affine radius is not admitted as a Jacobian prediction.")
    return tape, certificate, metadata
