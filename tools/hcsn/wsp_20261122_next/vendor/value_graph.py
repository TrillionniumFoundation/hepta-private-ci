"""Complete supplied-own-law tasks, exact ordered policy expectations and gaps."""
import numpy as np
from data_contract import canonical, digest

TERMINAL = (0, 4, 5)
WORK = dict(hidden_forward_calls=0, hidden_forward_rows=0, readout_forward_calls=0,
            readout_forward_rows=0, own_graphs=0, semantic_physical_calls=0,
            semantic_complete_rows=0, complete_policy_DPs=0, own_optimal_DPs=0)


def strict_hidden(base, X):
    network = base['network']
    w1, b1 = np.asarray(network['w1']), np.asarray(network['b1'])
    X = np.asarray(X, dtype=np.float64)
    if X.ndim != 2 or X.shape[1] != 85 or not np.isfinite(X).all():
        raise ValueError('complete original input matrix required')
    WORK['hidden_forward_calls'] += 1
    WORK['hidden_forward_rows'] += len(X)
    hidden = np.ones((len(X), 49))
    for lo in range(0, len(X), 128):
        hi = min(lo + 128, len(X))
        z = (X[lo:hi, None, :] * w1[None, :, :]).sum(axis=-1) + b1
        hidden[lo:hi, :48] = np.tanh(z)
    return hidden


def strict_scores(rows, H):
    rows, H = np.asarray(rows), np.asarray(H)
    WORK['readout_forward_calls'] += 1
    WORK['readout_forward_rows'] += len(H)
    logits = np.empty((len(H), 4))
    for lo in range(0, len(H), 256):
        logits[lo:lo + 256] = (H[lo:lo + 256, None, :] * rows[None, :, :]).sum(-1)
    belief = 1 / (1 + np.exp(-np.clip(logits[:, 3], -700, 700)))
    scores = np.column_stack((np.zeros(len(H)), logits[:, :3], 1 - 2 * belief, 2 * belief - 1))
    if not np.isfinite(scores).all():
        raise ArithmeticError('nonfinite actual head scores')
    return scores, belief, logits


def semantic_inputs(ctx, public, model, states, budget):
    if model.family != 'renewal':
        raise ValueError('memoization is qualified only for the renewal model')
    cached, rows = {}, []
    for index, state in enumerate(states):
        if index % 128 == 0:
            budget()
        key = (state['tick'], tuple((r['observation_tick'], r['observation'], r['reliability'])
                                    for r in state['history']))
        if key not in cached:
            WORK['semantic_physical_calls'] += 1
            mass, bank, _ = model.represent(public, state)
            cached[key] = (mass, bank)
        mass, bank = cached[key]
        # State-sensitive features, including charges, are never memoized away.
        rows.append(np.r_[ctx.public_features(public, state), mass, bank])
    WORK['semantic_complete_rows'] += len(rows)
    return np.asarray(rows), {'physical_feature_keys': len(cached), 'complete_feature_rows': len(rows)}


def build(ctx, public, base, cap, budget):
    WORK['own_graphs'] += 1
    model = ctx.NumpyPolicy(base)
    oracle = ctx.Oracle(public, ctx.OwnTableLaw(model, ctx), model.confusion)
    pending, mapping = [ctx.initial(public)], {}
    while pending:
        state = pending.pop()
        key = canonical(state)
        if key in mapping:
            continue
        if len(mapping) >= cap:
            raise OverflowError('full-state cap; no partial-world replacement')
        mapping[key] = state
        for action, legal in enumerate(ctx.legal(public, state)):
            if not legal or action in TERMINAL:
                continue
            due = ctx.due_request(public, state, action)
            branches = [None] if due is None else [dict(failure=True, observation_tick=due)] + [
                dict(observation=y, observation_tick=due) for y in (0, 1)]
            pending.extend(ctx.successor(public, state, action, branch) for branch in branches)
    keys, states = list(mapping), list(mapping.values())
    indices = {key: index for index, key in enumerate(keys)}
    order = sorted(range(len(states)), key=lambda i: states[i]['tick'])
    masks = np.array([ctx.legal(public, s) for s in states], dtype=bool)
    posterior = np.array([oracle.posterior(s) for s in states])
    if not np.isfinite(posterior).all() or np.any(posterior < 0) or np.any(posterior > 1):
        raise ArithmeticError('invalid own-law deadline posterior')
    terminal = np.c_[np.zeros((len(states), 4)), 1 - 2 * posterior, 2 * posterior - 1]
    edges, normalization_error = [], 0.0
    for index, state in enumerate(states):
        if index % 128 == 0:
            budget()
        row = []
        for action in (1, 2, 3):
            outgoing = []
            if masks[index, action]:
                for probability, completion in ctx.outcomes(public, state, action, oracle):
                    after = ctx.successor(public, state, action, completion)
                    fee = float(after['charges'] - state['charges'])
                    if after['tick'] != state['tick'] + 1 or probability < 0 or fee < 0:
                        raise ArithmeticError('invalid DAG step')
                    if not np.isfinite(probability) or not np.isfinite(fee):
                        raise ArithmeticError('nonfinite edge')
                    outgoing.append((float(probability), indices[canonical(after)], fee))
                normalization_error = max(normalization_error, abs(sum(p for p, _, _ in outgoing) - 1))
            row.append(outgoing)
        edges.append(row)
    if normalization_error > 2e-11:
        raise ArithmeticError('outgoing probability normalization')
    qstar, optimal = terminal.copy(), np.zeros(len(states))
    WORK['own_optimal_DPs'] += 1
    for index in reversed(order):
        for offset, outgoing in enumerate(edges[index]):
            if masks[index, offset + 1]:
                total = 0.0
                for probability, after, fee in outgoing:
                    if probability:
                        total += probability * (float(optimal[after]) - fee)
                qstar[index, offset + 1] = total
        optimal[index] = float(np.where(masks[index], qstar[index], -np.inf).max())
    return dict(schema='hepta-own-law-full-task-v1', public=public, keys=keys, states=states,
                masks=masks, posterior=posterior, terminal=terminal, edges=edges,
                qstar=qstar, optimal_values=optimal, order=order,
                initial=indices[canonical(ctx.initial(public))],
                state_order_sha256=digest(canonical(keys).encode()),
                probability_error=normalization_error)


def evaluate(graph, scores, original_occupancy=None):
    WORK['complete_policy_DPs'] += 1
    masks = np.asarray(graph['masks'], dtype=bool)
    scores = np.asarray(scores, dtype=np.float64)
    qstar, terminal = np.asarray(graph['qstar']), np.asarray(graph['terminal'])
    if scores.shape != masks.shape or not np.isfinite(scores).all():
        raise ValueError('full finite score matrix required')
    actions = np.where(masks, scores, -np.inf).argmax(1)
    values, occupancy = np.zeros(len(actions)), np.zeros(len(actions))
    order, edges, initial = graph['order'], graph['edges'], graph['initial']
    for index in reversed(order):
        action = int(actions[index])
        if not masks[index, action]:
            raise ArithmeticError('illegal selected action')
        if action in TERMINAL:
            values[index] = terminal[index, action]
        else:
            total = 0.0
            for probability, after, fee in edges[index][action - 1]:
                if probability:
                    total += probability * (float(values[after]) - fee)
            values[index] = total
    occupancy[initial] = 1.0
    for index in order:
        action = int(actions[index])
        if action not in TERMINAL:
            for probability, after, _ in edges[index][action - 1]:
                if probability:
                    occupancy[after] += float(occupancy[index]) * probability
    terminal_mass = sum(float(occupancy[i]) for i in order if int(actions[i]) in TERMINAL)
    if abs(terminal_mass - 1) > 2e-10:
        raise ArithmeticError('candidate terminal probability not conserved')
    optimum = np.asarray(graph['optimal_values'])
    gap = optimum - qstar[np.arange(len(actions)), actions]
    if not np.isfinite(gap).all() or float(gap.min()) < -2e-12:
        raise ArithmeticError('invalid raw optimal action gap')
    terminal_gap = continuation_gap = reward = expense = 0.0
    for index in order:
        action = int(actions[index])
        contribution = float(occupancy[index]) * float(gap[index])
        if action in TERMINAL:
            terminal_gap += contribution
            reward += float(occupancy[index]) * float(terminal[index, action])
        else:
            continuation_gap += contribution
            for probability, _, fee in edges[index][action - 1]:
                expense += float(occupancy[index]) * probability * fee
    initial_value, initial_optimum = float(values[initial]), float(optimum[initial])
    gap_sum = terminal_gap + continuation_gap
    residual = initial_optimum - initial_value - gap_sum
    tolerance = 1e-10 * (1 + abs(initial_optimum) + abs(initial_value) + abs(gap_sum))
    if abs(residual) > tolerance or abs(initial_value - (reward - expense)) > tolerance:
        raise ArithmeticError('complete performance-difference/payoff identity failed')
    reference = occupancy if original_occupancy is None else np.asarray(original_occupancy)
    if reference.shape != occupancy.shape or not np.isfinite(reference).all() or np.any(reference < 0) or reference.sum() <= 0:
        raise ValueError('original complete-decision occupancy required')
    common_weight, actual_weight = reference / reference.sum(), occupancy / occupancy.sum()
    predicted_p = (scores[:, 5] + 1) / 2
    posterior_error = (predicted_p - np.asarray(graph['posterior'])) ** 2
    terminal_indices = np.asarray(TERMINAL)
    terminal_legal = masks[:, terminal_indices]
    predicted_terminal = terminal_indices[np.where(terminal_legal, scores[:, terminal_indices], -np.inf).argmax(1)]
    optimal_terminal = np.where(terminal_legal, terminal[:, terminal_indices], -np.inf).max(1)
    terminal_rank_gap = optimal_terminal - terminal[np.arange(len(actions)), predicted_terminal]
    report = dict(utility=initial_value, optimal_utility=initial_optimum,
                  optimal_regret=initial_optimum - initial_value, terminal_mass=terminal_mass,
                  expected_terminal_reward=reward, expected_expense=expense,
                  expected_decisions=float(occupancy.sum()),
                  terminal_gap_contribution=terminal_gap, continuation_gap_contribution=continuation_gap,
                  PDI_residual=residual, PDI_tolerance=tolerance, raw_minimum_gap=float(gap.min()),
                  belief_diagnostics=dict(
                      probability_source='(existing_score_for_action5+1)/2; no extra forward',
                      original_full_decision_occupancy_normalizer=float(reference.sum()),
                      candidate_full_decision_occupancy_normalizer=float(occupancy.sum()),
                      own_posterior_MSE_original_occupancy=float(common_weight @ posterior_error),
                      own_posterior_MSE_candidate_occupancy=float(actual_weight @ posterior_error),
                      terminal_rank_own_gap_original_occupancy=float(common_weight @ terminal_rank_gap),
                      terminal_rank_own_gap_candidate_occupancy=float(actual_weight @ terminal_rank_gap),
                      terminal_rank_own_gap_full_state_max=float(terminal_rank_gap.max()),
                      same_weights_across_candidates='original occupancy only',
                      selection_criterion=False),
                  complete_state_count=len(actions), reached_state_count=int(np.count_nonzero(occupancy)),
                  action_sha256=digest(actions.tobytes()), occupancy_sha256=digest(occupancy.tobytes()))
    return report, dict(actions=actions, values=values, occupancy=occupancy, raw_gap=gap, scores=scores)
