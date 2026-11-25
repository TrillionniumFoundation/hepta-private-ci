"""Finite-horizon PFT action compression and fixed-feature quadratic solves.

Riccati recurrence adapted from hepta-private-ci/qa/stem-bakeoff/
cell_field_control.py at 32b8a11ae5d55a2e7324a8b31c5057f7b911a139.
Recursive regression follows qualification/cell-e3-encoder-transfer-20261123/
matched-edit/resident.py at 2395cf55831d480d4ca7cce2886e39ba9b04d063,
using a primal update of the same unchanged ridge objective.
This implements unconstrained linear/quadratic systems with known coefficients.
It does not invert an unknown LLM, impose coordinate boxes, or qualify learning.
"""

import numpy as np


def _finite(value):
    array = np.asarray(value, dtype=np.float64)
    if not np.isfinite(array).all():
        raise ValueError("finite numerical arrays required")
    return array


def _positive(matrix):
    matrix = _finite(matrix)
    if (matrix.ndim != 2 or matrix.shape[0] != matrix.shape[1]
            or not np.allclose(matrix, matrix.T, atol=1e-12, rtol=1e-12)):
        raise ValueError("symmetric square cost required")
    try:
        factor = np.linalg.cholesky(matrix)
    except np.linalg.LinAlgError as error:
        raise ValueError("positive definite cost required") from error
    return matrix, factor


def _system(A, E, L, targets, costs):
    A, E, L, targets, costs = ([_finite(x) for x in group]
                               for group in (A, E, L, targets, costs))
    horizon = len(A)
    if not horizon or A[0].ndim != 2:
        raise ValueError("nonempty finite horizon required")
    dim = A[0].shape[0]
    if (len(E) != horizon or len(costs) != horizon
            or len(L) != horizon + 1 or len(targets) != horizon + 1):
        raise ValueError("one transition/action cost per step and terminal charge required")
    for k, (a, e, cost) in enumerate(zip(A, E, costs, strict=True)):
        if a.shape != (dim, dim) or e.ndim != 2 or e.shape[0] != dim:
            raise ValueError("state and action dimensions differ")
        if cost.shape != (e.shape[1], e.shape[1]):
            raise ValueError("action cost dimension differs")
        costs[k] = _positive(cost)[0]
    if any(l.ndim != 2 or l.shape[1] != dim or r.shape != (len(l),)
           for l, r in zip(L, targets, strict=True)):
        raise ValueError("charged observations and targets differ")
    return A, E, L, targets, costs


def augment_terminal(charges, targets, blocks):
    """Append (linear map, target, positive weight) answer/retention blocks.

    These are quadratic penalties, not hard feasibility or nonlinear retention.
    Original arrays remain unchanged; rebuilding the action basis is necessary.
    """
    charges, targets = ([_finite(x).copy() for x in group]
                        for group in (charges, targets))
    if not charges or len(charges) != len(targets) or charges[-1].ndim != 2:
        raise ValueError("terminal observation and target required")
    for rows, target, weight in blocks:
        rows, target = _finite(rows), _finite(target)
        if (rows.ndim != 2 or rows.shape[1] != charges[-1].shape[1]
                or target.shape != (len(rows),) or not np.isfinite(weight) or weight <= 0):
            raise ValueError("compatible terminal block and positive weight required")
        charges[-1] = np.vstack((charges[-1], np.sqrt(weight) * rows))
        targets[-1] = np.r_[targets[-1], np.sqrt(weight) * target]
    return charges, targets


def solve_lq(A, E, L, targets, costs):
    """Affine Riccati solution; all stage/terminal weights are already in L.

    Costs may be non-diagonal and action dimensions may differ between steps.
    Additive control-independent zero-mean innovations do not change this policy.
    The stored initial value omits the innovation-dependent constant.
    """
    A, E, L, targets, costs = _system(A, E, L, targets, costs)
    P, ell = L[-1].T @ L[-1], -L[-1].T @ targets[-1]
    constant = float(0.5 * targets[-1] @ targets[-1])
    gains, offsets = [None] * len(A), [None] * len(A)
    for k in range(len(A) - 1, -1, -1):
        a, e, l, r = A[k], E[k], L[k], targets[k]
        W = costs[k] + e.T @ P @ e
        W = (W + W.T) / 2
        gain = np.linalg.solve(W, e.T @ P @ a)
        offset = -np.linalg.solve(W, e.T @ ell)
        new_P = l.T @ l + a.T @ P @ a - gain.T @ W @ gain
        ell = -l.T @ r + a.T @ ell + gain.T @ W @ offset
        P = (new_P + new_P.T) / 2
        constant += float(0.5 * r @ r - 0.5 * offset @ W @ offset)
        gains[k], offsets[k] = gain, offset
    return dict(A=A, E=E, L=L, targets=targets, costs=costs,
                gains=gains, offsets=offsets, P=P, ell=ell, constant=constant)


def effective_action_bases(A, E, L, costs, rtol=1e-12):
    """Preserve every charged future response using the PFT Theorem 11 space.

    For cost C C.T, u=C^{-T}v. Right singular vectors of stacked future
    responses times C^{-T} give each step's weighted action space. No fixed
    rank is assumed, and a zero-rank action is represented by an empty basis.
    """
    if not np.isfinite(rtol) or not 0 < rtol < 1:
        raise ValueError("a relative rank tolerance between zero and one is required")
    A, E, L, _, costs = _system(A, E, L, [np.zeros(len(x)) for x in L], costs)
    bases, records = [], []
    for k, (e, cost) in enumerate(zip(E, costs, strict=True)):
        factor = _positive(cost)[1]
        whiten = np.linalg.solve(factor.T, np.eye(len(cost)))
        response, rows = e.copy(), []
        for j in range(k + 1, len(L)):
            rows.append(L[j] @ response)
            if j < len(A):
                response = A[j] @ response
        D = np.vstack(rows) @ whiten
        _, singular, right = np.linalg.svd(D, full_matrices=False)
        cutoff = rtol * singular[0] if len(singular) else 0.0
        rank = int(np.count_nonzero(singular > cutoff))
        Q = right[:rank].T
        basis = whiten @ Q
        dropped = D - D @ Q @ Q.T
        records.append(dict(rank=rank, original_dim=len(cost), rows=len(D),
                            singular_values=singular.tolist(), cutoff=float(cutoff),
                            dropped_norm=float(np.linalg.norm(dropped)) if dropped.size else 0.0,
                            metric_error=float(np.linalg.norm(basis.T @ cost @ basis - np.eye(rank)))))
        bases.append(basis)
    return bases, records


def reduce_actions(A, E, L, targets, costs, bases=None):
    if bases is None:
        bases, _ = effective_action_bases(A, E, L, costs)
    if len(bases) != len(E):
        raise ValueError("one action basis per step required")
    policy = solve_lq(A, [e @ b for e, b in zip(E, bases, strict=True)], L, targets,
                      [b.T @ r @ b for b, r in zip(bases, costs, strict=True)])
    return policy, bases


def rollout(policy, initial, innovations=None):
    """Execute a causal policy; sampled future innovations are never exposed."""
    state = _finite(initial).copy()
    horizon, dim = len(policy["A"]), policy["A"][0].shape[0]
    innovations = np.zeros((horizon, dim)) if innovations is None else _finite(innovations)
    if state.shape != (dim,) or innovations.shape != (horizon, dim):
        raise ValueError("initial state or innovation path has a wrong dimension")
    states, actions, objective = [state.copy()], [], 0.0
    for k in range(horizon + 1):
        residual = policy["L"][k] @ state - policy["targets"][k]
        objective += float(0.5 * residual @ residual)
        if k == horizon:
            break
        action = -policy["gains"][k] @ state + policy["offsets"][k]
        objective += float(0.5 * action @ policy["costs"][k] @ action)
        state = policy["A"][k] @ state + policy["E"][k] @ action + innovations[k]
        states.append(state.copy())
        actions.append(action)
    return dict(states=np.asarray(states), actions=actions, objective=objective)


def condensed_kkt(A, E, L, targets, costs, initial):
    """Independent forward condensation and stationarity solve, without Riccati.

    The initial state is fixed and future innovations are zero. Supplying a
    realized future-noise path here would give a different anticipative problem.
    """
    A, E, L, targets, costs = _system(A, E, L, targets, costs)
    cuts = np.r_[0, np.cumsum([e.shape[1] for e in E])]
    state, sensitivity = _finite(initial).copy(), np.zeros((len(A[0]), cuts[-1]))
    rows, residuals, penalty = [], [], np.zeros((cuts[-1], cuts[-1]))
    for k in range(len(L)):
        rows.append(L[k] @ sensitivity)
        residuals.append(L[k] @ state - targets[k])
        if k < len(A):
            selection = slice(cuts[k], cuts[k + 1])
            penalty[selection, selection] = costs[k]
            sensitivity = A[k] @ sensitivity
            sensitivity[:, selection] += E[k]
            state = A[k] @ state
    matrix, offset = np.vstack(rows), np.concatenate(residuals)
    H, g = matrix.T @ matrix + penalty, matrix.T @ offset
    action = -np.linalg.solve(H, g)
    residual = matrix @ action + offset
    return dict(actions=[action[cuts[k]:cuts[k + 1]] for k in range(len(A))],
                objective=float(0.5 * (residual @ residual + action @ penalty @ action)),
                stationarity=float(np.linalg.norm(H @ action + g, ord=np.inf)) if len(action) else 0.0)


def solve_normal(gram, rhs, regularizer=0.2):
    """Solve pooled sum-statistics; add the regularizer exactly once globally.

    gram=sum(X.T@X), rhs=sum(X.T@y). rhs may have several output columns.
    These sums must share the feature, target, model and objective identities.
    """
    gram, rhs = _finite(gram), _finite(rhs)
    if (gram.ndim != 2 or gram.shape[0] != gram.shape[1] or not len(gram)
            or rhs.ndim not in (1, 2) or rhs.shape[0] != len(gram)
            or not np.isfinite(regularizer) or regularizer <= 0
            or not np.allclose(gram, gram.T, atol=1e-11, rtol=1e-11)):
        raise ValueError("compatible positive-regularized normal statistics required")
    if np.linalg.eigvalsh(gram).min() < -1e-10 * max(1.0, np.linalg.norm(gram, 2)):
        raise ValueError("Gram statistics must be positive semidefinite")
    return np.linalg.solve(gram + regularizer * np.eye(len(gram)), rhs)


def recursive_ridge(batches, regularizer=0.2):
    """Primal block RLS with the same ridge objective and no forgetting."""
    if not batches or not np.isfinite(regularizer) or regularizer <= 0:
        raise ValueError("nonempty batches and positive regularization required")
    first_x, first_y = (_finite(x) for x in batches[0])
    if first_x.ndim != 2 or first_y.ndim not in (1, 2):
        raise ValueError("matrix features and vector or matrix targets required")
    dim = first_x.shape[1]
    inverse = np.eye(dim) / regularizer
    weight = np.zeros((dim, *first_y.shape[1:]))
    for x, y in batches:
        x, y = _finite(x), _finite(y)
        if x.ndim != 2 or x.shape[1] != dim or not len(x) or y.shape != (len(x), *weight.shape[1:]):
            raise ValueError("fixed feature/target dimensions and nonempty batches required")
        cross = inverse @ x.T
        gain = np.linalg.solve(np.eye(len(x)) + x @ cross, cross.T).T
        weight = weight + gain @ (y - x @ weight)
        inverse = inverse - gain @ cross.T
        inverse = (inverse + inverse.T) / 2
    return _finite(weight)


if __name__ == "__main__":
    from qualification.hcsn_closure_20261124.pft_linear_tests import main
    main()
