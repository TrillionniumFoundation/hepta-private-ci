"""Finite known-support confidence adapter for recursive entropic policy improvement.

Unknown probabilities only; rewards, durations, transitions and legal rows are
known. No reset, label or timing access is inferred. Classical binomial confidence
sets and robust Bellman bounds are engineering/theory references, not new RL.
"""
from dataclasses import dataclass
from fractions import Fraction
import math
from scipy.stats import beta


@dataclass(frozen=True)
class Atom:
    reward: float
    cost: float
    adjustment_cost: float
    duration: float
    next_state: str | None


def _finite(x):
    return isinstance(x, (float, int)) and not isinstance(x, bool) and math.isfinite(x)


def structural_support(nodes):
    """Strip probability values before passing support to the confidence layer."""
    return {s: {a: tuple(Atom(o.reward, o.cost, o.adjustment_cost, o.duration,
                             o.next_state) for o in law)
                for a, law in row.items()} for s, row in nodes.items()}


def order_support(support, root):
    if (not isinstance(support, dict) or not 1 <= len(support) <= 512
            or not isinstance(root, str) or not root or root not in support):
        raise ValueError('Nonempty support and declared root required')
    # Match the inherited finite reference's state/action/atom contract before
    # DFS or continuation lookups. In particular, '' is never a terminal marker.
    for state, actions in support.items():
        if (not isinstance(state, str) or not state or not isinstance(actions, dict)
                or not 1 <= len(actions) <= 256):
            raise ValueError('Nonempty string states and bounded legal action rows required')
        for action, atoms in actions.items():
            if (not isinstance(action, str) or not action or not isinstance(atoms, tuple)
                    or not 1 <= len(atoms) <= 4096):
                raise ValueError('Nonempty string actions and immutable atom support required')
            for atom in atoms:
                if (not isinstance(atom, Atom) or not all(_finite(x) for x in
                    (atom.reward, atom.cost, atom.adjustment_cost, atom.duration))
                    or min(atom.cost, atom.adjustment_cost, atom.duration) < 0
                    or atom.next_state is not None and (
                        not isinstance(atom.next_state, str) or not atom.next_state
                        or atom.next_state not in support)
                    or action.upper() == 'STOP' and atom.next_state is not None):
                    raise ValueError('Invalid bounded outcome or successor')
    active, done, order = set(), set(), []
    def visit(s):
        if s in active:
            raise ValueError('Acyclic finite support required')
        if s in done:
            return
        active.add(s)
        for action, atoms in support[s].items():
            for atom in atoms:
                if atom.next_state is not None:
                    visit(atom.next_state)
        active.remove(s)
        done.add(s)
        order.append(s)
    for s in sorted(support):
        visit(s)
    return order


def _normalized_row(row, actions):
    if not isinstance(row, dict) or set(row) != set(actions) or not row:
        raise ValueError('Policy row must cover exactly the legal action set')
    if any(not _finite(p) or p < 0 for p in row.values()):
        raise ValueError('Finite nonnegative policy probabilities required')
    try:
        total = math.fsum(row.values())
    except OverflowError as exc:
        raise ValueError('Invalid policy probability mass') from exc
    if not math.isclose(total, 1., abs_tol=1e-12, rel_tol=0):
        raise ValueError('Policy row probability mass must equal one')
    # The inherited core accepts rounding-only mass discrepancy, then normalizes.
    return {action: probability / total for action, probability in row.items()}


def normalize_policy(support, policy):
    """Validate BOTH fitted policies against the complete shared legal support."""
    if not isinstance(policy, dict) or set(policy) != set(support):
        raise ValueError('Policy must cover all and only declared states')
    return {s: _normalized_row(policy[s], support[s]) for s in support}


def _centered_mix(row, values):
    anchor = values[next(iter(row))]
    value = anchor + math.fsum(row[a] * (values[a] - anchor) for a in row)
    if not math.isfinite(value):
        raise ArithmeticError('Nonfinite centered policy mixture')
    return value


def _lower_float(value):
    result = float(value)
    if not math.isfinite(result):
        raise ArithmeticError('Advantage outside the supported numeric range')
    return math.nextafter(result, -math.inf) if Fraction(result) > value else result


def probability_boxes(support, counts, alpha=.05, families=1):
    """Clopper-Pearson intervals, Bonferroni over non-singleton coordinates.

    Counts are iid within each reset row at a fixed predeclared n. Different rows
    need not be independent for the union bound. No optional stopping coverage is
    claimed. Candidate/baseline fitting may reuse these counts because the event
    covers the model, hence every fixed policy, simultaneously.
    """
    if not _finite(alpha) or not 0 < alpha < 1 or type(families) is not int or families < 1:
        raise ValueError('Valid familywise error budget and family count required')
    if not isinstance(support, dict) or not support:
        raise ValueError('Nonempty known support required')
    order_support(support, next(iter(support)))
    if not isinstance(counts, dict) or set(support) != set(counts):
        raise ValueError('Complete count states required')
    coordinates = sum(len(law) for row in support.values() for law in row.values()
                      if len(law) > 1)
    alpha_atom = alpha / max(1, coordinates * families)
    boxes = {}
    for s, row in support.items():
        if not isinstance(counts[s], dict) or set(row) != set(counts[s]):
            raise ValueError('Complete count action rows required')
        boxes[s] = {}
        for a, law in row.items():
            c = counts[s][a]
            if (not isinstance(c, (list, tuple)) or len(c) != len(law)
                or any(type(n) is not int or n < 0 for n in c)
                or sum(c) < 1):
                raise ValueError('Positive fixed-sample complete integer counts required')
            n = sum(c)
            if len(c) == 1:
                boxes[s][a] = ((1., 1.),)
            else:
                boxes[s][a] = tuple((0. if k == 0 else float(beta.ppf(alpha_atom / 2, k, n-k+1)),
                    1. if k == n else float(beta.ppf(1-alpha_atom / 2, k+1, n-k)))
                    for k in c)
    return boxes, {'alpha':alpha,'families':families,'unknown_coordinates':coordinates,
        'per_coordinate_two_sided_alpha':alpha_atom,
        'coverage':'fixed-sample simultaneous model event; ordinary floating-point endpoints'}


def box_expectation(weights, bounds, maximize):
    """Exact greedy linear program on a box intersected with the simplex."""
    if not weights or len(weights) != len(bounds) or any(not math.isfinite(w) for w in weights):
        raise ValueError('Finite aligned weights required')
    if any(not (0 <= lo <= hi <= 1) for lo, hi in bounds):
        raise ValueError('Ordered probability endpoints required')
    lower = math.fsum(lo for lo, _ in bounds)
    upper = math.fsum(hi for _, hi in bounds)
    if lower > 1 + 1e-12 or upper < 1 - 1e-12:
        raise ValueError('Empty probability confidence set')
    probs = [lo for lo, _ in bounds]
    remaining = max(0., 1-lower)
    for i in sorted(range(len(weights)), key=lambda i: weights[i], reverse=maximize):
        added = min(remaining, bounds[i][1] - probs[i])
        probs[i] += added
        remaining -= added
    if remaining > 1e-10:
        raise ValueError('Probability box cannot hold unit mass')
    return math.fsum(p*w for p,w in zip(probs, weights))


def ce_bound(atoms, bounds, values, eta, rho, lower):
    x = [o.reward-o.cost-o.adjustment_cost + (math.exp(-rho*o.duration)*values[o.next_state]
         if o.next_state is not None else 0.) for o in atoms]
    anchor = min(x)
    weights = [math.exp(-eta*(v-anchor)) for v in x]
    moment = box_expectation(weights, bounds, maximize=lower)
    if moment <= 0:
        raise ArithmeticError('Entropic moment underflow')
    return anchor - math.log(moment)/eta


def policy_intervals(support, root, policy, boxes, eta=2., rho=.17):
    if not _finite(eta) or eta <= 0 or not _finite(rho) or rho < 0:
        raise ValueError('eta > 0 and rho >= 0 required')
    order = order_support(support, root)
    policy = normalize_policy(support, policy)
    if not isinstance(boxes, dict) or set(boxes) != set(support):
        raise ValueError('Complete confidence boxes required')
    vlow, vhigh, qb = {}, {}, {}
    for s in order:
        if not isinstance(boxes[s], dict) or set(boxes[s]) != set(support[s]):
            raise ValueError('Exact legal action coverage required')
        qb[s] = {a: (ce_bound(atoms, boxes[s][a], vlow, eta, rho, True),
                     ce_bound(atoms, boxes[s][a], vhigh, eta, rho, False))
                 for a, atoms in support[s].items()}
        vlow[s] = _centered_mix(policy[s], {a: q[0] for a, q in qb[s].items()})
        vhigh[s] = _centered_mix(policy[s], {a: q[1] for a, q in qb[s].items()})
    return {'root':(vlow[root],vhigh[root]),'vlow':vlow,'vhigh':vhigh,'q':qb,
            'order':order,'policy':policy}


def signed_advantage_lower(old, new, qbounds):
    if not isinstance(qbounds, dict) or not qbounds:
        raise ValueError('Complete action-value bounds required')
    old = _normalized_row(old, qbounds)
    new = _normalized_row(new, qbounds)
    for bound in qbounds.values():
        if (not isinstance(bound, tuple) or len(bound) != 2
                or not all(_finite(x) for x in bound) or bound[0] > bound[1]):
            raise ValueError('Finite ordered action-value bounds required')
    if old == new:
        return 0.
    # Signed differences sum exactly to zero on the accepted binary-float
    # weights after rational normalization. Center by ONE row reference before
    # multiplication; a large common currency offset cannot invent advantage.
    old_total = sum(map(Fraction, old.values()))
    new_total = sum(map(Fraction, new.values()))
    anchor = Fraction(qbounds[next(iter(qbounds))][0])
    terms = []
    for a in old:
        difference = Fraction(new[a]) / new_total - Fraction(old[a]) / old_total
        endpoint = Fraction(qbounds[a][0 if difference >= 0 else 1])
        terms.append(difference * (endpoint - anchor))
    return _lower_float(sum(terms, Fraction(0)))


def local_safe_policy(baseline, proposed, qbounds, tolerance=1e-12):
    if (not isinstance(qbounds, dict) or not qbounds or not _finite(tolerance)
            or tolerance < 0):
        raise ValueError('Complete action-value bounds and nonnegative tolerance required')
    baseline = normalize_policy(qbounds, baseline)
    proposed = normalize_policy(qbounds, proposed)
    effective, local, changed = {}, {}, 0
    for s, row in baseline.items():
        advantage = signed_advantage_lower(row, proposed[s], qbounds[s])
        if row != proposed[s] and advantage > tolerance:
            effective[s], local[s] = dict(proposed[s]), advantage
            changed += 1
        else:
            effective[s], local[s] = dict(row), 0.
    return effective, local, changed


def propagated_gain_lower(support, root, baseline_bounds, policy, boxes, local, eta=2., rho=.17):
    """Propagate certified local improvements through unchanged ancestor rows.

    Baseline risk-tilted mass lower bounds use known-support probability boxes
    and full recursive baseline value intervals. This needs local >= 0 at every
    row; it is not a bound for an arbitrary ungated candidate.
    """
    order = order_support(support, root)
    policy = normalize_policy(support, policy)
    if not _finite(eta) or eta <= 0 or not _finite(rho) or rho < 0:
        raise ValueError('eta > 0 and rho >= 0 required')
    if baseline_bounds['order'] != order:
        raise ValueError('Baseline bounds must use the same complete support order')
    if (not isinstance(local, dict) or set(local) != set(support)
            or any(not _finite(x) or x < 0 for x in local.values())):
        raise ValueError('All local advantage lower bounds must be nonnegative')
    gain, tilt_records = {}, {}
    for s in order:
        increments = {}
        tilt_records[s] = {}
        for a, atoms in support[s].items():
            xl, xu = [], []
            for atom in atoms:
                reward=atom.reward-atom.cost-atom.adjustment_cost
                d=math.exp(-rho*atom.duration)
                xl.append(reward+(d*baseline_bounds['vlow'][atom.next_state]
                                  if atom.next_state is not None else 0.))
                xu.append(reward+(d*baseline_bounds['vhigh'][atom.next_state]
                                  if atom.next_state is not None else 0.))
            anchor=min(xl)
            denominator=box_expectation([math.exp(-eta*(x-anchor)) for x in xl],boxes[s][a],True)
            tilt_lo=[p[0]*math.exp(-eta*(x-anchor))/denominator for p,x in zip(boxes[s][a],xu)]
            if math.fsum(tilt_lo)>1+1e-10:
                raise ArithmeticError('Invalid tilted mass bound')
            improvement_terms=[w*(-math.expm1(-eta*math.exp(-rho*atom.duration)*gain[atom.next_state]))
                for w,atom in zip(tilt_lo,atoms) if atom.next_state is not None]
            improvement_mass=max(0.,min(1.-1e-15,math.fsum(improvement_terms)))
            increments[a]=-math.log1p(-improvement_mass)/eta
            tilt_records[s][a]=tilt_lo
        gain[s]=local[s]+_centered_mix(policy[s], increments)
    return {'root_gain_lower':gain[root],'state_gain_lower':gain,'tilted_mass_lower':tilt_records}


def certified_update(support, root, baseline, proposed, boxes, eta=2.,rho=.17,fee=0.):
    if not _finite(fee) or fee<0:
        raise ValueError('Finite nonnegative fee required')
    order_support(support, root)
    baseline = normalize_policy(support, baseline)
    proposed = normalize_policy(support, proposed)
    bounds=policy_intervals(support,root,baseline,boxes,eta,rho)
    baseline = bounds['policy']
    effective, local, changed=local_safe_policy(baseline,proposed,bounds['q'])
    propagated=propagated_gain_lower(support,root,bounds,effective,boxes,local,eta,rho)
    lower=propagated['root_gain_lower']
    adopt=lower>fee+1e-12
    return {'decision':'adopt' if adopt else 'no-update','policy':effective if adopt else baseline,
            'baseline_bounds':bounds,'local_advantage_lower':local,'safe_rows_changed':changed,
            'root_local_advantage_lower':local[root],'proposed_gain_lower':lower,
            'proposed_net_lower':lower-fee,'paid_fee':fee,
            'returned_net_lower':lower-fee if adopt else -fee,'propagation':propagated}
