"""Fixed-label soft proposals: bounded conic editing and matched PG reference.

This is teacher-guided parameter optimization, not a label-free WSP replica.
No function here opens task, teacher, SELECT, AUDIT, or confirmation files.
"""
import math
import time
import numpy as np
from scipy import sparse
import clarabel
from data_contract import exact_radius, digest
from value_graph import strict_scores

RHO = 0.001
INNER_FACTOR = 0.99999999
WORK = dict(conic_attempts=0, conic_solve_calls=0, gradient_trajectories=0,
            gradient_updates=0, fixed_gradient_checkpoints_reached=0)


def screen(H, masks, qstar, original_scores, original_occupancy, initials, row_ids):
    masks = np.asarray(masks, dtype=bool)
    qstar, occupancy = np.asarray(qstar), np.asarray(original_occupancy)
    target = np.where(masks, qstar, -np.inf).argmax(1)
    original_actions = np.where(masks, original_scores, -np.inf).argmax(1)
    gap = qstar[np.arange(len(H)), target] - qstar[np.arange(len(H)), original_actions]
    if not np.isfinite(gap).all() or gap.min() < -2e-12 or np.any(occupancy < 0):
        raise ArithmeticError('invalid GEN screening quantities')
    mass = occupancy * np.maximum(gap, 0)
    opportunity = sorted(np.flatnonzero(mass > 0), key=lambda i: (-float(mass[i]), int(row_ids[i])))[:128]
    retained = sorted(np.flatnonzero((occupancy > 0) & (gap == 0)),
                      key=lambda i: (-float(occupancy[i]), int(row_ids[i])))[:64]
    selected = sorted(set(opportunity) | set(retained) | set(initials), key=lambda i: int(row_ids[i]))
    if not selected or len(selected) > 224:
        raise ValueError('screened GEN state count')
    selected = np.asarray(selected, dtype=np.int64)
    target = target[selected]
    margins = np.maximum(0, qstar[selected, target, None] - qstar[selected])
    margins += 1e-6 * (np.arange(6)[None, :] < target[:, None])
    chosen_mass = float(mass[selected].sum())
    report = dict(selected_rows=len(selected), opportunity_rows=len(opportunity),
                  retention_rows=len(retained), initial_rows=len(initials),
                  GEN_rows=len(H), positive_original_occupancy_rows=int(np.count_nonzero(occupancy)),
                  zero_original_occupancy_rows=int(np.count_nonzero(occupancy == 0)),
                  total_old_occupancy_gap=float(mass.sum()), selected_old_occupancy_gap=chosen_mass,
                  omitted_old_occupancy_gap=float(mass.sum()) - chosen_mass,
                  global_row_ids=np.asarray(row_ids)[selected].tolist(),
                  selected_H_sha256=digest(np.asarray(H)[selected].tobytes()),
                  loss_weighting='uniform selected states; old occupancy*gap only screens',
                  candidate_utility_bound=False)
    return dict(H=np.asarray(H)[selected], masks=masks[selected], targets=target,
                margins=margins), report


def terminal_slopes(logits, beliefs):
    slope = 2 * beliefs * (1 - beliefs)
    return np.where((logits[:, 3] > -700) & (logits[:, 3] < 700), slope, 0.0)


def exact_loss_gradient(rows, anchor, problem, radius):
    H, masks, targets = (problem[k] for k in ('H', 'masks', 'targets'))
    scores, belief, logits = strict_scores(rows, H)
    loss = scores - scores[np.arange(len(H)), targets, None] + problem['margins']
    valid = masks.copy()
    valid[np.arange(len(H)), targets] = False
    loss = np.where(valid, loss, -np.inf)
    competitor = loss.argmax(1)
    maximum = loss[np.arange(len(H)), competitor]
    active = maximum > 0
    scale = active.astype(float) / len(H)
    gradient = np.zeros((4, 49))
    for action in (1, 2, 3):
        coefficient = scale * ((competitor == action).astype(float) - (targets == action))
        gradient[action - 1] = (coefficient[:, None] * H).sum(0)
    signs = np.array([0, 0, 0, 0, -1, 1])
    coefficient = scale * (signs[competitor] - signs[targets]) * terminal_slopes(logits, belief)
    gradient[3] = (coefficient[:, None] * H).sum(0)
    delta = rows - anchor
    gradient += (RHO / radius ** 2) * delta
    objective = float(np.maximum(0, maximum).mean() + RHO / (2 * radius ** 2) * np.sum(delta ** 2))
    if not math.isfinite(objective) or not np.isfinite(gradient).all():
        raise ArithmeticError('nonfinite exact nonlinear loss/gradient')
    return objective, gradient


def jacobian(action, H, slope):
    result = np.zeros((4, 49))
    if action in (1, 2, 3):
        result[action - 1] = H
    elif action in (4, 5):
        result[3] = (-slope if action == 4 else slope) * H
    return result.reshape(-1)


def conic_subproblem(anchor, center, problem, family, radius, remaining, budget):
    WORK['conic_attempts'] += 1
    started, wall = time.process_time(), time.perf_counter()
    H, masks, target = (problem[k] for k in ('H', 'masks', 'targets'))
    active = np.arange(147) if family == 'Q' else (np.arange(147, 196) if family == 'B' else np.arange(196))
    n, states = len(active), len(H)
    scores, belief, logits = strict_scores(center, H)
    slopes = terminal_slopes(logits, belief)
    center_delta = (center - anchor).reshape(-1)
    matrix, rhs = [], []
    for i in range(states):
        for action in range(6):
            if not masks[i, action] or action == target[i]:
                continue
            difference = jacobian(action, H[i], slopes[i]) - jacobian(int(target[i]), H[i], slopes[i])
            constant = scores[i, action] - scores[i, target[i]] + problem['margins'][i, action]
            constant -= float(np.sum(difference * center_delta))
            row = np.zeros(n + states)
            row[:n], row[n + i] = difference[active], -1
            matrix.append(row)
            rhs.append(-float(constant))
        row = np.zeros(n + states)
        row[n + i] = -1
        matrix.append(row)
        rhs.append(0.0)
    if family != 'Q':
        for i in range(states):
            complete = np.zeros(196)
            complete[147:] = H[i]
            displacement = float(np.sum(complete * center_delta))
            for sign in (1, -1):
                row = np.zeros(n + states)
                row[:n] = sign * complete[active]
                matrix.append(row)
                rhs.append(0.5 + sign * displacement)
    A_linear = np.asarray(matrix)
    b_linear = np.asarray(rhs)
    A_soc = np.zeros((n + 1, n + states))
    A_soc[1:, :n] = -np.eye(n)
    A = sparse.csc_matrix(np.vstack((A_linear, A_soc)))
    b = np.r_[b_linear, radius * INNER_FACTOR, np.zeros(n)]
    P = sparse.diags(np.r_[np.full(n, RHO / radius ** 2), np.zeros(states)], format='csc')
    q = np.r_[np.zeros(n), np.full(states, 1 / states)]
    settings = clarabel.DefaultSettings()
    settings.verbose = False
    settings.max_threads = 1
    settings.max_iter = 60
    settings.direct_solve_method = 'qdldl'
    available = remaining - (time.process_time() - started)
    if available <= 0.02:
        return None, dict(status='SKIPPED_SETUP_BUDGET', CPU_seconds=time.process_time() - started), {}
    settings.time_limit = min(1.4, available - 0.01)
    settings.tol_feas = settings.tol_gap_abs = settings.tol_gap_rel = 1e-8
    budget()
    solver = clarabel.DefaultSolver(P, q, A, b,
              [clarabel.NonnegativeConeT(len(b_linear)), clarabel.SecondOrderConeT(n + 1)], settings)
    WORK['conic_solve_calls'] += 1
    solution = solver.solve()
    x, z = np.asarray(solution.x), np.asarray(solution.z)
    primal, dual = float(solution.r_prim), float(solution.r_dual)
    finite = np.isfinite(x).all() and np.isfinite(z).all() and np.isfinite([primal, dual]).all()
    violation = float(max(0, np.max(A_linear @ x - b_linear))) if finite else None
    report = dict(status=str(solution.status), iterations=int(solution.iterations),
                  requested_solver_time_limit=settings.time_limit,
                  CPU_seconds=time.process_time() - started, wall_seconds=time.perf_counter() - wall,
                  primal_residual=primal if math.isfinite(primal) else None,
                  dual_residual=dual if math.isfinite(dual) else None,
                  independently_recomputed_linear_violation=violation,
                  active_coordinates=n, selected_states=states, linear_constraints=len(b_linear))
    accepted = (report['status'] in ('Solved', 'AlmostSolved') and finite and
                violation <= 1e-7 * (1 + float(np.abs(b_linear).max())) and primal <= 1e-7 and dual <= 1e-6)
    proposal = None
    if accepted:
        proposal = anchor.copy()
        proposed_flat = proposal.reshape(-1)
        proposed_flat[active] = anchor.reshape(-1)[active] + x[:n]
        norm = exact_radius(anchor, proposal)
        accepted = norm['within_shared_ball']
        report['exact_norm'] = norm
    report['accepted_numeric_proposal'] = bool(accepted)
    return proposal if accepted else None, report, {'primal': x, 'dual': z}


def structured_family(anchor, problem, family, budget):
    if family not in ('Q', 'B', 'G'):
        raise ValueError('unregistered structured family')
    started, wall = time.process_time(), time.perf_counter()
    cap, count = (1.5, 1) if family == 'Q' else (3.0, 2)
    radius = exact_radius(anchor)['numeric_radius']
    if radius <= 0:
        raise ValueError('positive original radius required')
    center, candidates, records, payloads = anchor.copy(), {}, {}, {}
    for iteration in range(1, count + 1):
        name = family + '_' + str(iteration)
        if iteration > 1 and not candidates:
            records[name] = dict(status='SKIPPED_FAILED_DEPENDENCY')
            continue
        remaining = cap - (time.process_time() - started)
        if remaining <= 0:
            records[name] = dict(status='UNKNOWN_FAMILY_CPU_BUDGET')
            continue
        proposed, report, payload = conic_subproblem(anchor, center, problem, family, radius, remaining, budget)
        if proposed is not None:
            report['actual_nonlinear_loss'] = exact_loss_gradient(proposed, anchor, problem, radius)[0]
            prepared_checkpoint = proposed.copy()
        observed = time.process_time() - started
        report['family_CPU_through_checkpoint'] = observed
        report['family_nominal_CPU_cap'] = cap
        report['family_CPU_overshoot'] = max(0.0, observed - cap)
        if observed > cap:
            proposed = None
            report['accepted_numeric_proposal'] = False
            report['budget_disposition'] = 'UNKNOWN_OVER_NOMINAL_CAP'
        if proposed is not None:
            candidates[name] = prepared_checkpoint
            center = prepared_checkpoint
        records[name], payloads[name] = report, payload
    return candidates, dict(checkpoints=records, CPU_seconds=time.process_time() - started,
                            wall_seconds=time.perf_counter() - wall, nominal_CPU_cap=cap), payloads


def gradient_reference(anchor, problem, budget):
    WORK['gradient_trajectories'] += 1
    started, wall = time.process_time(), time.perf_counter()
    cap = 3.0
    radius = exact_radius(anchor)['numeric_radius']
    inner = radius * INNER_FACTOR
    if inner <= 0:
        raise ValueError('positive original radius required')
    bound = 2 * float(np.linalg.norm(problem['H'], axis=1).max()) + RHO / inner
    rows, candidates, records = anchor.copy(), {}, {}
    completed = 0
    for step in range(1, 1025):
        budget()
        if time.process_time() - started >= cap:
            break
        _, gradient = exact_loss_gradient(rows, anchor, problem, radius)
        delta = rows - anchor - (inner / (bound * math.sqrt(step))) * gradient
        length = float(np.linalg.norm(delta))
        if length > inner:
            delta *= inner / length
        rows = anchor + delta
        WORK['gradient_updates'] += 1
        completed = step
        if step in (256, 1024):
            name = 'T_' + str(step)
            norm = exact_radius(anchor, rows)
            actual_loss = exact_loss_gradient(rows, anchor, problem, radius)[0]
            prepared_checkpoint = rows.copy()
            finite = bool(np.isfinite(prepared_checkpoint).all())
            WORK['fixed_gradient_checkpoints_reached'] += 1
            elapsed = time.process_time() - started
            valid = norm['within_shared_ball'] and elapsed <= cap and finite
            records[name] = dict(status='COMPLETED' if valid else 'UNKNOWN_INVALID_OR_BUDGET',
                step=step, family_CPU_through_checkpoint=elapsed, nominal_CPU_cap=cap,
                CPU_overshoot=max(0.0, elapsed - cap), exact_norm=norm,
                actual_nonlinear_loss=actual_loss)
            if valid:
                candidates[name] = prepared_checkpoint
    for step in (256, 1024):
        records.setdefault('T_' + str(step), dict(status='UNKNOWN_CHECKPOINT_NOT_REACHED', step=step))
    return candidates, dict(checkpoints=records, steps_completed=completed,
                            CPU_seconds=time.process_time() - started,
                            wall_seconds=time.perf_counter() - wall, nominal_CPU_cap=cap,
                            training_is_196_only=True)
