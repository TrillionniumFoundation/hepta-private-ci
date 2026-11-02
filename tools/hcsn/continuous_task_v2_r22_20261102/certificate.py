"""Outward interval residual bounds and strict fixed-policy admission.

The target is the fixed-grid real equations with the supplied binary64 input
coefficients and nodes. No input normalization or probability floor is added.
Unknown ties reject qualification; the one explicit binary-rational task tie
has a separate algebraic witness. This is not a continuum certificate.
"""

import math
import numpy as np
from .dependency import mpmath as mp


def certify(tape, digits=50, error_tolerance=1e-10):
    mp.iv.dps = digits
    p = mp.iv.mpf
    c, d, x = tape["config"], tape["direction"], tape["x"]
    dt, dx, lag = p(tape["dt"]), p(tape["dx"]), tape["lag"]
    n, _, count = tape["values"].shape
    if (lag != round(c["recovery"] / tape["dt"]) or n != round(c["horizon"] / tape["dt"]) + 1
            or count != round((c["upper"] - c["lower"]) / tape["dx"]) + 1
            or not np.array_equal(x, np.linspace(c["lower"], c["upper"], count))):
        raise ValueError("Tape geometry does not match its fixed task")
    for key in ("values", "left_values", "tangent", "left_tangent"):
        if tape[key].shape != (n, 2, count) or not np.isfinite(tape[key]).all():
            raise ValueError("Malformed numeric tape")
    minimum = lambda values: p([min(v.a for v in values), min(v.b for v in values)])
    maximum = lambda values: p([max(v.a for v in values), max(v.b for v in values)])
    hull = lambda values: p([min(v.a for v in values), max(v.b for v in values)])
    bound = lambda values: max(abs(v).b for v in values)
    box = lambda center, radius: p([(p(center) - radius).a, (p(center) + radius).b])
    a = 1 + dt * p(c["sigma"]) ** 2 / dx ** 2
    off = -dt * p(c["sigma"]) ** 2 / (2 * dx ** 2)
    g, dg = [], []
    for mode in range(2):
        sigmoid = [1 / (1 + mp.iv.exp(-p(c["reward_slope"]) * p(at))) for at in x]
        g.append([p(c["reward_base"][mode]) + p(c["reward_amplitude"][mode]) * s for s in sigmoid])
        dg.append([p(d[8 + mode]) + p(d[10 + mode]) * s + p(c["reward_amplitude"][mode]) * p(at) * s * (1 - s) * p(d[12]) for at, s in zip(x, sigmoid)])
    v, lv, z, lz = [([None] * n) for _ in range(4)]
    v[0], lv[0], z[0], lz[0] = g, g, dg, dg
    expressions = {}

    def tag(expression):
        if expression not in expressions:
            expressions[expression] = len(expressions) + 1
        return expressions[expression]

    g_ids = [[tag(("reward", mode, j)) for j in range(count)] for mode in range(2)]
    v_ids, lv_ids = [None] * n, [None] * n
    v_ids[0], lv_ids[0] = g_ids, g_ids
    cell = int(np.searchsorted(x, c["reset_x"], side="right") - 1)
    if c["reset_x"] == x[cell] and d[3] < 0:
        cell -= 1
    width = p(x[cell + 1]) - p(x[cell])
    weight = (p(c["reset_x"]) - p(x[cell])) / width
    matrix = [[p(value) for value in row] for row in c["content_transition"]]
    dm = [[p(d[6]), -p(d[6])], [-p(d[7]), p(d[7])]]
    fee = [p(c["reset_fee"][j]) + p(c["recovery_cost"]) * p(c["recovery"]) for j in range(2)]
    dfee = [p(d[4 + j]) + p(d[2]) * p(c["recovery"]) for j in range(2)]

    def reset(source, derivative):
        future = [(1 - weight) * row[cell] + weight * row[cell + 1] for row in source]
        df = [(1 - weight) * row[cell] + weight * row[cell + 1] + p(d[3]) * (source[j][cell + 1] - source[j][cell]) / width for j, row in enumerate(derivative)]
        return ([sum(matrix[j][k] * future[k] for k in range(2)) - fee[j] for j in range(2)],
                [sum(matrix[j][k] * df[k] + dm[j][k] * future[k] for k in range(2)) - dfee[j] for j in range(2)])

    def reset_ids(source):
        inputs = tuple(source[mode][j] for mode in range(2) for j in (cell, cell + 1))
        return [tag(("reset", mode, cell, inputs)) for mode in range(2)]

    def apply(row):
        return [a * row[j] + (off * row[j - 1] * (2 if j == count - 1 else 1) if j else 0)
                + (off * row[j + 1] * (2 if j == 0 else 1) if j < count - 1 else 0) for j in range(count)]

    # Binary-rational witness: g(0)=(5/8,3/8), B1=(1/4)(5/8)+(3/4)(3/8)-1/16=3/8.
    expected = dict(lower=-4., upper=4., sigma=1., reset_x=0., wait_cost=2., recovery_cost=0.,
        recovery=.25, horizon=.25, reward_base=[.25, .125], reward_amplitude=[.75, .5],
        reward_slope=1., reset_fee=[.125, .0625], content_transition=[[.75, .25], [.25, .75]])
    witness = (all(c[key] == value for key, value in expected.items()) and
        (tape["dx"], tape["dt"]) in ((.5, .125), (.25, .0625)) and np.count_nonzero(d) == 1 and d[5] != 0)
    left_plan = np.full(tape["actions"].shape, -1, dtype=np.int8)
    outer_plan = np.zeros(tape["outer"].shape, dtype=np.int8)
    unresolved, known_ties, aliases, mismatch, margins = [], [], [], [], []
    primal_error = bound([p(tape[key][0, j, i]) - g[j][i] for key in ("values", "left_values") for j in range(2) for i in range(count)])
    derivative_error = bound([p(tape[key][0, j, i]) - dg[j][i] for key in ("tangent", "left_tangent") for j in range(2) for i in range(count)])
    affine = all(d[j] == 0 for j in (0, 3, 6, 7, 12))
    radius, radius_witness = None, None

    def record_limit(slack, slope, identity):
        nonlocal radius, radius_witness
        if affine and slack.a > 0 and slope.a < 0:
            candidate = slack.a / (-slope.a)
            if radius is None or candidate.a < radius.a:
                radius, radius_witness = candidate, identity

    for k in range(1, n):
        rb, drb, lb, dlb = None, None, None, None
        rb_ids, lb_ids = None, None
        if k >= lag:
            rb, drb = reset(v[k - lag], z[k - lag])
            rb_ids = reset_ids(v_ids[k - lag])
            if k != lag:
                lb, dlb = reset(lv[k - lag], lz[k - lag]) if k % lag == 0 else (rb, drb)
                lb_ids = reset_ids(lv_ids[k - lag]) if k % lag == 0 else rb_ids
        lv[k], lz[k] = [], []
        lv_ids[k] = [[], []]
        for mode in range(2):
            rhs = [value - p(c["wait_cost"]) * dt for value in v[k - 1][mode]]
            av = apply([p(value) for value in tape["left_values"][k, mode]])
            residuals = []
            for j, value in enumerate(tape["left_values"][k, mode]):
                choices = [p(value) - g[mode][j], av[j] - rhs[j]]
                if lb is not None:
                    choices.append(p(value) - lb[mode])
                residuals.append(minimum(choices))
            error = bound(residuals)  # A1=1; obstacle/WAIT residual comparison constant is exactly1.
            lv[k].append([box(value, error) for value in tape["left_values"][k, mode]])
            q = [value - target for value, target in zip(apply(lv[k][mode]), rhs)]
            for j in range(count):
                stop, reset_gap = lv[k][mode][j] - g[mode][j], None if lb is None else lv[k][mode][j] - lb[mode]
                candidates = []
                if stop.a > 0 and (reset_gap is None or reset_gap.a > 0):
                    candidates.append((0, [stop] + ([] if reset_gap is None else [reset_gap])))
                if q[j].a > 0 and (lb is None or (g[mode][j] - lb[mode]).a > 0):
                    candidates.append((1, [q[j]] + ([] if lb is None else [g[mode][j] - lb[mode]])))
                if lb is not None and q[j].a > 0 and (lb[mode] - g[mode][j]).a > 0:
                    candidates.append((2, [q[j], lb[mode] - g[mode][j]]))
                if len(candidates) == 1:
                    action, gaps = candidates[0]
                    left_plan[k, mode, j] = action
                    if action == 1:
                        lv[k][mode][j] = g[mode][j]
                    elif action == 2:
                        lv[k][mode][j] = lb[mode]
                    margins += [gap.a for gap in gaps]
                    if action != tape["actions"][k, mode, j]:
                        mismatch.append([k, mode, j])
                else:
                    unresolved.append(["left", k, mode, j])
                    left_plan[k, mode, j] = tape["actions"][k, mode, j]
            curvature = [2 * (lv[k][mode][1] - lv[k][mode][0]) if j == 0 else
                2 * (lv[k][mode][-2] - lv[k][mode][-1]) if j == count - 1 else
                lv[k][mode][j - 1] - 2 * lv[k][mode][j] + lv[k][mode][j + 1] for j in range(count)]
            dAv = [-dt * p(c["sigma"]) / dx ** 2 * p(d[0]) * value for value in curvature]
            drhs = [z[k - 1][mode][j] - p(d[1]) * dt - dAv[j] for j in range(count)]
            az = apply([p(value) for value in tape["left_tangent"][k, mode]])
            targets = [drhs[j] if left_plan[k, mode, j] == 0 else dg[mode][j]
                       if left_plan[k, mode, j] == 1 else dlb[mode] for j in range(count)]
            residual = [az[j] - targets[j] if left_plan[k, mode, j] == 0 else p(tape["left_tangent"][k, mode, j]) - targets[j] for j in range(count)]
            error_z = bound(residual)
            lz[k].append([box(value, error_z) for value in tape["left_tangent"][k, mode]])
            for j, action in enumerate(left_plan[k, mode]):
                if action == 1 and ["left", k, mode, j] not in unresolved:
                    lz[k][mode][j] = dg[mode][j]
                elif action == 2 and ["left", k, mode, j] not in unresolved:
                    lz[k][mode][j] = dlb[mode]
            primal_error = max(primal_error, bound([p(tape["left_values"][k, mode, j]) - lv[k][mode][j] for j in range(count)]))
            derivative_error = max(derivative_error, bound([p(tape["left_tangent"][k, mode, j]) - lz[k][mode][j] for j in range(count)]))
            dq = [value + dAv[j] - z[k - 1][mode][j] + p(d[1]) * dt for j, value in enumerate(apply(lz[k][mode]))]
            for j, action in enumerate(left_plan[k, mode]):
                if action != 0:
                    record_limit(q[j], dq[j], ["wait", k, mode, j])
                if action != 1:
                    record_limit(lv[k][mode][j] - g[mode][j], lz[k][mode][j] - dg[mode][j], ["stop", k, mode, j])
                if lb is not None and action != 2:
                    record_limit(lv[k][mode][j] - lb[mode], lz[k][mode][j] - dlb[mode], ["reset", k, mode, j])
            boundaries = tuple(g_ids[mode][j] if action == 1 else lb_ids[mode] if action == 2 else 0 for j, action in enumerate(left_plan[k, mode]))
            system_id = tag(("implicit", mode, tuple(v_ids[k - 1][mode]), tuple(map(int, left_plan[k, mode])), boundaries))
            for j, action in enumerate(left_plan[k, mode]):
                lv_ids[k][mode].append(tag(("unknown", k, mode, j)) if ["left", k, mode, j] in unresolved else
                    g_ids[mode][j] if action == 1 else lb_ids[mode] if action == 2 else tag(("implicit_node", system_id, j)))
        if k % lag == 0:
            v[k], z[k] = [[], []], [[], []]
            v_ids[k] = [[], []]
            for mode in range(2):
                for j in range(count):
                    gap = lv[k][mode][j] - rb[mode]
                    identical = lv_ids[k][mode][j] == rb_ids[mode]
                    if identical and (gap.a > 0 or gap.b < 0):
                        raise RuntimeError("Structural equality contradicts interval enclosures")
                    if gap.a > 0:
                        choose = 0
                        margins.append(gap.a)
                    elif gap.b < 0:
                        choose = 1
                        margins.append((-gap).a)
                    elif identical:
                        choose = 0
                        aliases.append([k, mode, j])
                    elif witness and k == lag and mode == 1 and x[j] == 0:
                        choose = int(d[5] < 0)
                        known_ties.append([k, mode, j])
                    else:
                        choose = int(tape["outer"][k, mode, j])
                        unresolved.append(["outer", k, mode, j])
                    outer_plan[k, mode, j] = choose
                    if choose != tape["outer"][k, mode, j]:
                        mismatch.append(["outer", k, mode, j])
                    v[k][mode].append(lv[k][mode][j] if identical else maximum([lv[k][mode][j], rb[mode]]))
                    if witness and [k, mode, j] in known_ties:
                        z[k][mode].append(maximum([lz[k][mode][j], drb[mode]]))
                    elif ["outer", k, mode, j] in unresolved:
                        z[k][mode].append(hull([lz[k][mode][j], drb[mode]]))
                    else:
                        z[k][mode].append(drb[mode] if choose else lz[k][mode][j])
                    v_ids[k][mode].append(tag(("unknown_max", k, mode, j)) if ["outer", k, mode, j] in unresolved else
                        tag(("true_max", lv_ids[k][mode][j], rb_ids[mode])) if [k, mode, j] in known_ties else rb_ids[mode] if choose else lv_ids[k][mode][j])
                    if not identical:
                        record_limit(-gap if choose else gap, drb[mode] - lz[k][mode][j] if choose else lz[k][mode][j] - drb[mode], ["outer", k, mode, j])
        else:
            v[k], z[k] = lv[k], lz[k]
            v_ids[k] = lv_ids[k]
        primal_error = max(primal_error, bound([p(tape["values"][k, j, i]) - v[k][j][i] for j in range(2) for i in range(count)]))
        derivative_error = max(derivative_error, bound([p(tape["tangent"][k, j, i]) - z[k][j][i] for j in range(2) for i in range(count)]))
    for mode in range(2):
        for value, slope in ((c["reward_base"][mode], d[8 + mode]), (c["reward_amplitude"][mode], d[10 + mode]), (c["reset_fee"][mode], d[4 + mode])):
            record_limit(p(value), p(slope), ["domain", mode, value, slope])
        record_limit(1 - p(c["reward_base"][mode]) - p(c["reward_amplitude"][mode]), -p(d[8 + mode]) - p(d[10 + mode]), ["reward_upper", mode])
    for key, index in (("wait_cost", 1), ("recovery_cost", 2)):
        record_limit(p(c[key]), p(d[index]), ["domain", key])
    branch_certified = not unresolved
    primal_accurate = bool(primal_error.b <= p(error_tolerance))
    accurate = bool(derivative_error.b <= p(error_tolerance))
    upper_float = lambda value: 0. if value.b == 0 else math.nextafter(float(value.b), math.inf)
    return dict(qualified=branch_certified and primal_accurate and accurate and not mismatch, branch_certified=branch_certified,
        primal_error_bound_passed=primal_accurate,
        derivative_error_bound_passed=accurate, derivative_error_tolerance=error_tolerance,
        unresolved=unresolved, policy_mismatches=mismatch,
        known_nonconstant_ties=known_ties, interval_decimal_precision=digits,
        identical_expression_ties=aliases,
        maximum_primal_enclosure_error=upper_float(primal_error), maximum_derivative_enclosure_error=upper_float(derivative_error),
        minimum_strict_slack_lower_bound=math.nextafter(float(min(margins)), 0.) if margins else None,
        affine_direction=affine, affine_radius_certified=affine and branch_certified and primal_accurate and accurate and not mismatch and not known_ties,
        safe_affine_step_radius=math.nextafter(float(radius.a), 0.) if radius is not None else None,
        radius_witness=radius_witness, plan=dict(left=left_plan, outer=outer_plan),
        scope="Fixed binary-input real equations. Trusted mpmath interval arithmetic; no continuum or all-input machine formal proof.")
