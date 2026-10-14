"""Eight shared learned corner probabilities on an explicitly given read-once tree.

The operator's answer table is NOT a training target. Only original root labels
fit the eight probabilities. The optional original-law guard concerns the same
independent-leaf f=0 model as belief_bsde; it is not a semantic truth certificate
or a nonlinear coupled FBSDE. No production policy/authority is introduced.
"""
import math
from four_gate_common import require

PROFILE = 'independent_targets_composition_v3'


def compile_formula(formula):
    """Bounded public syntax only. Repeated leaves would invalidate the product law."""
    nodes, seen = [], set()
    def visit(f, depth):
        require(depth <= 4 and len(nodes) < 15, 'bounded read-once formula')
        if type(f) is int:
            require(0 <= f < 4 and f not in seen, 'repeated or invalid leaf')
            seen.add(f)
            return -1-f
        require(type(f) in (tuple, list) and len(f) == 3 and f[0] in ('and', 'or'),
                'explicit AND/OR syntax required')
        left, right = visit(f[1], depth+1), visit(f[2], depth+1)
        nodes.append((int(f[0] == 'or'), left, right))
        return len(nodes)-1
    root = visit(formula, 0)
    return tuple(nodes), root


def _check_tables(tables):
    require(type(tables) in (tuple, list) and len(tables) == 2 and
            all(type(row) in (tuple, list) and len(row) == 4 for row in tables),
            'two complete stochastic corner tables')
    require(all(type(p) in (float, int) and math.isfinite(p) and 0 <= p <= 1
                for row in tables for p in row), 'finite corner probabilities')


def evaluate(formula, probabilities, tables, *, correct=False):
    """Fast scalar deployment of frozen eight-parameter cell, not Torch per node.

    The error bound uses the original AND/OR maps, both 1-Lipschitz in EACH
    child on [0,1]. With local defect d, E_parent <= E_left+E_right+d.
    Floating arithmetic is NOT rigorously enclosed: decision_margin is only
    a conservative engineering cushion, not an interval theorem certificate.
    """
    require(type(correct) is bool, 'explicit correction mode')
    _check_tables(tables)
    require(type(probabilities) in (tuple, list) and 1 <= len(probabilities) <= 4 and
            all(type(p) in (float, int) and math.isfinite(p) and 0 <= p <= 1
                for p in probabilities), 'finite semantic probabilities')
    nodes, root = compile_formula(formula)
    values, errors, depths = [], [], []
    def read(i, field):
        if i >= 0:
            return field[i]
        require(-1-i < len(probabilities), 'missing semantic leaf')
        return probabilities[-1-i] if field is values else 0.
    for op, left, right in nodes:
        a, b = read(left, values), read(right, values)
        weights = ((1-a)*(1-b), (1-a)*b, a*(1-b), a*b)
        prediction = math.fsum(w*p for w, p in zip(weights, tables[op]))
        prediction = min(1., max(0., prediction))  # finite convex sum, roundoff only
        values.append(prediction)
        depths.append(1+max(depths[left] if left >= 0 else 0, depths[right] if right >= 0 else 0))
        if correct:
            original = a+b-a*b if op else a*b
            errors.append(min(1., read(left, errors)+read(right, errors)+abs(prediction-original)))
        else:
            errors.append(0.)
    proposal = read(root, values)
    error = read(root, errors) if correct else None
    lower = max(0., proposal-error) if correct else None
    upper = min(1., proposal+error) if correct else None
    stable = correct and (lower > .5+1e-12 or upper < .5-1e-12)
    fallback = correct and not stable
    prediction = proposal
    if fallback:
        exact = []
        for op, left, right in nodes:
            a = exact[left] if left >= 0 else probabilities[-1-left]
            b = exact[right] if right >= 0 else probabilities[-1-right]
            exact.append(a+b-a*b if op else a*b)
        prediction = exact[root] if root >= 0 else probabilities[-1-root]
    return {'probability': min(1., max(0., prediction)), 'proposal_probability': proposal,
            'root_error_bound_exact_arithmetic': error, 'lower': lower, 'upper': upper,
            'decision_stable_under_model': bool(stable), 'exact_fallback': bool(fallback),
            'learned_operator_calls': len(nodes), 'learned_operator_depth': depths[root] if root >= 0 else 0,
            'guard_operator_calls': len(nodes) if correct else 0,
            'fallback_operator_calls': len(nodes) if fallback else 0,
            'float_roundoff_rigorously_enclosed': False, 'semantic_truth_certified': False}


def make_cell(torch):
    """All nodes share eight trainable scalars; initial tables carry no operator truth."""
    class CompositionCell(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.corners = torch.nn.Parameter(torch.full((2, 4), .5, dtype=torch.float32))

        def forward(self, probabilities, groups):
            result = probabilities.new_zeros(len(probabilities))
            for indices, nodes, root in groups:
                ps = probabilities[indices]
                values = []
                for op, left, right in nodes:
                    a = values[left] if left >= 0 else ps[:, -1-left]
                    b = values[right] if right >= 0 else ps[:, -1-right]
                    basis = torch.stack(((1-a)*(1-b), (1-a)*b, a*(1-b), a*b), -1)
                    values.append((basis*self.corners[op]).sum(-1))
                y = values[root] if root >= 0 else ps[:, -1-root]
                result = result.index_copy(0, indices, y)
            return result

        def project(self):
            with torch.no_grad():
                self.corners.clamp_(1e-6, 1-1e-6)

    return CompositionCell()


def compile_batch(torch, public):
    """Reuse a syntax plan across actual same-formula cases; no labels accepted."""
    grouped = {}
    for i, row in enumerate(public):
        require(set(row) == {'case_id', 'utterance_ids', 'target_intents', 'formula'},
                'public model inputs only')
        grouped.setdefault(compile_formula(row['formula']), []).append(i)
    return [(torch.tensor(ids, dtype=torch.long), nodes, root)
            for (nodes, root), ids in grouped.items()]
