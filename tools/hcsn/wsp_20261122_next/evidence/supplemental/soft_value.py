"""True finite-DAG soft-policy value and its exact readout derivative.

The analytic editor never requests a weight derivative. Both optimizers call
the same complete own-law objective and pay for every attempted evaluation.
"""
import time
import numpy as np


class Forest:
    """Equal-world complete DAGs with reverse value and forward occupancy."""

    def __init__(self, items):
        self.worlds = len(items)
        self.H = np.concatenate([np.asarray(x['H']) for x in items])
        self.masks = np.concatenate([np.asarray(x['graph']['masks'], dtype=bool) for x in items])
        self.posterior = np.concatenate([np.asarray(x['graph']['posterior']) for x in items])
        self.terminal = np.concatenate([np.asarray(x['graph']['terminal']) for x in items])
        self.ticks = np.concatenate([[s['tick'] for s in x['graph']['states']] for x in items])
        self.world_index = np.concatenate([[i] * len(x['H']) for i, x in enumerate(items)])
        self.initial, edge_src, edge_action, edge_dst, edge_prob, edge_fee = [], [], [], [], [], []
        offset = 0
        for item in items:
            graph = item['graph']
            self.initial.append(offset + graph['initial'])
            for i, actions in enumerate(graph['edges']):
                for a, edges in enumerate(actions, 1):
                    for prob, dst, fee in edges:
                        if prob:
                            edge_src.append(offset + i)
                            edge_action.append(a)
                            edge_dst.append(offset + dst)
                            edge_prob.append(prob)
                            edge_fee.append(fee)
            offset += len(item['H'])
        self.initial = np.asarray(self.initial, dtype=np.int64)
        self.src, self.action, self.dst = (np.asarray(x, dtype=np.int64) for x in (edge_src, edge_action, edge_dst))
        self.prob, self.fee = np.asarray(edge_prob), np.asarray(edge_fee)
        self.levels = [(np.flatnonzero(self.ticks == t), np.flatnonzero(self.ticks[self.src] == t))
                       for t in sorted(set(self.ticks))]
        if np.any(self.ticks[self.dst] != self.ticks[self.src] + 1):
            raise ValueError('complete one-tick DAG required')
        if self.H.ndim != 2 or not np.isfinite(self.H).all():
            raise ValueError('finite complete features required')
        self.calls = self.gradient_calls = self.forward_rows = self.policy_DPs = 0

    def evaluate(self, rows, anchor, radius, temperature, penalty, derivative=False):
        """Count an attempted call before any computation, including failures."""
        self.calls += 1
        self.gradient_calls += int(derivative)
        self.forward_rows += len(self.H)
        self.policy_DPs += self.worlds
        logits = (self.H[:, None, :] * np.asarray(rows)[None, :, :]).sum(-1)
        p = 1 / (1 + np.exp(-np.clip(logits[:, 3], -700, 700)))
        scores = np.column_stack((np.zeros(len(p)), logits[:, :3], 1 - 2 * p, 2 * p - 1))
        scaled = np.where(self.masks, scores / temperature, -np.inf)
        differences = scaled - np.max(scaled, axis=1)[:, None]
        if not np.isfinite(scores).all() or np.any(differences[self.masks] < -700):
            raise ArithmeticError('softmax finite admitted range exceeded')
        unnormalized = np.where(self.masks, np.exp(differences), 0)
        policy = unnormalized / unnormalized.sum(1)[:, None]
        q, values = self.terminal.copy(), np.zeros(len(p))
        for indices, edges in reversed(self.levels):
            contributions = self.prob[edges] * (values[self.dst[edges]] - self.fee[edges])
            np.add.at(q, (self.src[edges], self.action[edges]), contributions)
            values[indices] = (policy[indices] * q[indices]).sum(1)
        occupancy = np.zeros(len(p))
        occupancy[self.initial] = 1 / self.worlds
        for _, edges in self.levels:
            contributions = (occupancy[self.src[edges]] * policy[self.src[edges], self.action[edges]]
                             * self.prob[edges])
            np.add.at(occupancy, self.dst[edges], contributions)
        utility = float(values[self.initial].mean())
        delta = np.asarray(rows) - anchor
        regularizer = penalty * float(np.sum(delta ** 2)) / (2 * radius ** 2)
        objective = utility - regularizer
        gradient = None
        if derivative:
            coefficient = occupancy[:, None] * policy * (q - values[:, None]) / temperature
            logit_gradient = coefficient[:, 1:4]
            belief_gradient = ((coefficient[:, 5] - coefficient[:, 4]) * 2 * p * (1 - p))
            belief_gradient *= (np.abs(logits[:, 3]) <= 700)
            raw_gradient = np.column_stack((logit_gradient, belief_gradient))
            gradient = raw_gradient.T @ self.H - penalty * delta / radius ** 2
        if not np.isfinite(objective) or (gradient is not None and not np.isfinite(gradient).all()):
            raise ArithmeticError('nonfinite complete value objective')
        return dict(objective=objective, utility=utility, regularizer=regularizer,
                    gradient=gradient, logits=logits, scores=scores, policy=policy,
                    values=values, q=q, occupancy=occupancy)

    def counters(self):
        return dict(objective_calls=self.calls, gradient_calls=self.gradient_calls,
                    readout_forward_rows=self.forward_rows, complete_policy_DPs=self.policy_DPs)


def project(anchor, candidate, radius):
    delta = np.asarray(candidate) - anchor
    norm = float(np.linalg.norm(delta))
    if norm > radius * (1 - 1e-12):
        delta *= radius * (1 - 1e-12) / norm
    return anchor + delta


def optimize(forest, anchor, family, settings, check_radius, phase_budget):
    """One frozen attempt; a failed/capped family produces no selected model."""
    started, wall = time.process_time(), time.monotonic()
    before = forest.counters()
    radius = settings['radius']
    tau, penalty = settings['temperature'], settings['penalty']
    trace, proposals, best_rows = [], [], anchor.copy()
    slots = 0

    def budget():
        phase_budget()
        if time.process_time() - started > settings['family_cpu_seconds']:
            raise TimeoutError('family CPU cap')

    def objective(rows, derivative=False):
        budget()
        check_radius(anchor, rows)
        answer = forest.evaluate(rows, anchor, radius, tau, penalty, derivative)
        budget()
        return answer

    status, error = 'COMPLETED', None
    try:
        current_rows = anchor.copy()
        current = objective(current_rows, family == 'BP')
        best = current
        if family == 'DIRECT':
            for cycle in range(settings['direct_rounds']):
                local_advantage = np.max(np.where(forest.masks, current['q'], -np.inf), axis=1) - current['values']
                priorities = current['occupancy'] * np.maximum(local_advantage, 0)
                order = np.lexsort((np.arange(len(priorities)), -priorities))[:settings['states_per_round']]
                round_best, round_rows = current, current_rows
                for index in order:
                    probability = float(np.clip(forest.posterior[index], 1e-6, 1 - 1e-6))
                    desired = np.r_[current['q'][index, 1:4], np.log(probability / (1 - probability))]
                    # Illegal continuation slots carry no target information.
                    desired[:3] = np.where(forest.masks[index, 1:4], desired[:3], current['logits'][index, :3])
                    residual = desired - current['logits'][index]
                    h = forest.H[index]
                    rank_one = residual[:, None] * h[None, :] / float(h @ h)
                    for dose in settings['proposal_doses']:
                        candidate = project(anchor, current_rows + dose * rank_one, radius)
                        result = objective(candidate)
                        slots += 1
                        proposals.append(dict(slot=slots, cycle=cycle, state=int(index),
                            world=int(forest.world_index[index]), dose=dose,
                            local_priority=float(priorities[index]), objective=result['objective'],
                            utility=result['utility'], candidate_norm=float(np.linalg.norm(candidate - anchor))))
                        if result['objective'] > round_best['objective'] + 1e-12:
                            round_best, round_rows = result, candidate
                current, current_rows = round_best, round_rows
                if current['objective'] > best['objective'] + 1e-12:
                    best, best_rows = current, current_rows.copy()
                trace.append(dict(round=cycle + 1, objective=best['objective'], utility=best['utility'],
                                  CPU_seconds=time.process_time() - started))
        elif family == 'BP':
            for step in range(settings['bp_steps']):
                gradient = current['gradient']
                norm = float(np.linalg.norm(gradient))
                rate = settings['bp_relative_step'] * radius / np.sqrt(1 + step / 16)
                candidate = current_rows.copy() if norm == 0 else project(anchor, current_rows + rate * gradient / norm, radius)
                current = objective(candidate, True)
                current_rows = candidate
                slots += 1
                proposals.append(dict(slot=slots, step=step + 1, step_size=float(rate),
                    gradient_norm=norm, objective=current['objective'], utility=current['utility'],
                    candidate_norm=float(np.linalg.norm(candidate - anchor))))
                if current['objective'] > best['objective'] + 1e-12:
                    best, best_rows = current, current_rows.copy()
                if step in (0, 15, 63, 127):
                    trace.append(dict(step=step + 1, objective=best['objective'], utility=best['utility'],
                                      CPU_seconds=time.process_time() - started))
        else:
            raise ValueError('unknown optimizer')
        if slots != settings['proposal_slots']:
            raise ArithmeticError('fixed proposal count mismatch')
    except Exception as exc:
        status, error = 'FAILED_KEEP', repr(exc)
        best_rows = None
    after = forest.counters()
    report = dict(status=status, error=error, family=family, slots_completed=slots,
        CPU_seconds=time.process_time() - started, wall_seconds=time.monotonic() - wall,
        counters={k: after[k] - before[k] for k in before}, trace=trace, proposals=proposals,
        returned_best_objective=None if best_rows is None else best['objective'],
        returned_soft_utility=None if best_rows is None else best['utility'])
    return best_rows, report
