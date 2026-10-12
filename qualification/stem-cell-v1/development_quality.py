"""Independent group-risk calibration of an already frozen stopping portfolio.

Research-only Learn-then-Test special case: bound the probability that a NEW
IID source group contains any baseline-correct/candidate-wrong answer. This is
not an absolute accuracy guarantee, a distribution-shift guarantee, an authority
service, or proof of independent provenance. Correlated rows count as ONE group.
"""

from dataclasses import asdict, dataclass
import hashlib
import json
import math
import statistics


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def is_digest(value):
    return type(value) is str and len(value) == 64 and all(c in '0123456789abcdef' for c in value)


def bounded_name(value):
    return type(value) is str and 0 < len(value) <= 128


@dataclass(frozen=True)
class Census:
    scope: str
    fold: str
    sample_ids: tuple[str, ...]
    input_digests: tuple[str, ...]
    groups: tuple[str, ...]
    strata: tuple[str, ...]
    observed_at: tuple[int, ...]

    def validate(self):
        n = len(self.sample_ids) if type(self.sample_ids) is tuple else 0
        columns = (self.input_digests, self.groups, self.strata, self.observed_at)
        if (not bounded_name(self.scope) or not bounded_name(self.fold) or not 1 <= n <= 4096
                or any(type(v) is not tuple or len(v) != n for v in columns)
                or not all(bounded_name(v) for v in self.sample_ids + self.groups + self.strata)
                or len(set(self.sample_ids)) != n or not all(map(is_digest, self.input_digests))
                or any(type(v) is not int or not 0 <= v <= 2**63-1 for v in self.observed_at)):
            raise ValueError('invalid complete source census')
        content_groups, group_strata = {}, {}
        for content, group, stratum in zip(self.input_digests, self.groups, self.strata):
            if content_groups.setdefault(content, group) != group or group_strata.setdefault(group, stratum) != stratum:
                raise ValueError('same input split into independent groups or mixed group stratum')

    def identity(self):
        self.validate()
        return digest(asdict(self))


def require_disjoint_history(priors, later):
    """Metadata conformance, not authentication of logical times or group names."""
    if (type(priors) is not tuple or not 1 <= len(priors) <= 8 or type(later) is not Census
            or any(type(v) is not Census for v in priors)):
        raise ValueError('bounded source history required')
    all_folds = priors + (later,)
    for census in all_folds:
        census.validate()
    for i, first in enumerate(all_folds):
        for second in all_folds[i+1:]:
            if (first.scope != second.scope or max(first.observed_at) >= min(second.observed_at)
                    or set(first.sample_ids) & set(second.sample_ids)
                    or set(first.groups) & set(second.groups)
                    or set(first.input_digests) & set(second.input_digests)):
                raise ValueError('scope, input, source-group or time leakage')


@dataclass(frozen=True)
class BoundPolicy:
    mode: str
    depth: int
    threshold: float
    model_digest: str
    critic_digest: str | None
    source_digest: str

    def validate(self):
        if (self.mode not in ('fixed', 'confidence', 'learned') or type(self.depth) is not int
                or not 1 <= self.depth <= 32 or type(self.threshold) not in (int, float)
                or not math.isfinite(self.threshold) or not -1 <= self.threshold <= 1
                or not is_digest(self.model_digest) or not is_digest(self.source_digest)
                or (self.mode == 'fixed' and self.threshold != 0)
                or (self.mode == 'confidence' and self.threshold < 0)
                or (not is_digest(self.critic_digest) if self.mode == 'learned' else self.critic_digest is not None)):
            raise ValueError('invalid frozen stopping policy')

    def identity(self):
        self.validate()
        return digest(asdict(self))


@dataclass(frozen=True)
class RiskPlan:
    baseline: BoundPolicy
    candidates: tuple[BoundPolicy, ...]
    strata: tuple[str, ...]
    alpha: float = .05
    maximum_harm: float = .02
    minimum_groups: int = 64
    minimum_wall_saving: float = .05
    classes: int = 2

    def validate(self):
        if (type(self.baseline) is not BoundPolicy or type(self.candidates) is not tuple
                or not 1 <= len(self.candidates) <= 16 or any(type(v) is not BoundPolicy for v in self.candidates)
                or type(self.strata) is not tuple or not 1 <= len(self.strata) <= 8
                or not all(bounded_name(v) and v != '__all__' for v in self.strata)
                or len(set(self.strata)) != len(self.strata)
                or type(self.minimum_groups) is not int or not 1 <= self.minimum_groups <= 4096
                or type(self.classes) is not int or not 2 <= self.classes <= 128
                or any(type(v) not in (int, float) or not math.isfinite(v)
                       for v in (self.alpha, self.maximum_harm, self.minimum_wall_saving))
                or not 0 < self.alpha < 1 or not 0 <= self.maximum_harm < 1
                or not 0 <= self.minimum_wall_saving < 1):
            raise ValueError('invalid preregistered risk plan')
        policies = (self.baseline,) + self.candidates
        ids = tuple(p.identity() for p in policies)
        if (len(set(ids)) != len(ids) or len({p.model_digest for p in policies}) != 1
                or len({p.source_digest for p in policies}) != 1):
            raise ValueError('duplicate or incompatible policy portfolio')

    def identity(self):
        self.validate()
        return digest(asdict(self))


@dataclass(frozen=True)
class Observation:
    policy_digest: str
    census_digest: str
    predictions: tuple[int, ...]
    depths: tuple[int, ...]
    wall_ns: tuple[int, ...]
    cpu_ns: tuple[int, ...]

    def validate(self, census, policy, classes):
        n = len(census.sample_ids)
        if (self.policy_digest != policy.identity() or self.census_digest != census.identity()
                or type(self.predictions) is not tuple or len(self.predictions) != n
                or type(self.depths) is not tuple or len(self.depths) != n
                or any(type(p) is not int or not 0 <= p < classes for p in self.predictions)
                or any(type(d) is not int or not 1 <= d <= policy.depth for d in self.depths)
                or (policy.mode == 'fixed' and any(d != policy.depth for d in self.depths))
                or type(self.wall_ns) is not tuple or not 3 <= len(self.wall_ns) <= 9
                or type(self.cpu_ns) is not tuple or len(self.cpu_ns) != len(self.wall_ns)
                or any(type(t) is not int or not 0 < t < 2**63 for t in self.wall_ns + self.cpu_ns)):
            raise ValueError('incomplete, reordered, drifting or invalid paired execution evidence')


def binomial_upper(failures, groups, alpha):
    """One-sided Clopper-Pearson bound; no normal approximation/zero-risk shortcut.

    CDF is evaluated in log space; bisection returns the conservative upper
    bracket, with a small outward numerical margin. n=0 is unavailable -> 1.
    """
    if (type(groups) is not int or not 0 <= groups <= 4096 or type(failures) is not int
            or not 0 <= failures <= groups or type(alpha) not in (int, float)
            or not math.isfinite(alpha) or not 0 < alpha < 1):
        raise ValueError('invalid binomial confidence input')
    if failures == groups:
        return 1.0
    if failures == 0:
        return min(1., -math.expm1(math.log(alpha) / groups) + 1e-12)
    terms = [math.lgamma(groups+1) - math.lgamma(j+1) - math.lgamma(groups-j+1)
             for j in range(failures+1)]
    low, high, target = failures/groups, 1., math.log(alpha)
    for _ in range(60):
        p = (low + high) / 2
        if not low < p < high:
            break
        logs = [c + j*math.log(p) + (groups-j)*math.log1p(-p) for j,c in enumerate(terms)]
        peak = max(logs)
        log_cdf = peak + math.log(math.fsum(math.exp(v-peak) for v in logs))
        if log_cdf > target:
            low = p
        else:
            high = p
    return min(1., high + 1e-12)


@dataclass(frozen=True)
class Selection:
    plan_digest: str
    history_digests: tuple[str, ...]
    risk_digest: str
    selected_policy_digest: str


def select_guarded(plan, priors, census, gold, observations):
    """Test ALL preregistered policies/slices; then select only a faster safe one.

    Improvements elsewhere never cancel a baseline-correct answer made wrong.
    Timing thresholds are empirical conditions, NOT statistical speed guarantees.
    A Python Selection is not a signed production artifact or independent review.
    """
    if type(plan) is not RiskPlan:
        raise ValueError('typed risk plan required')
    plan.validate()
    require_disjoint_history(priors, census)
    if (tuple(p.fold for p in priors) != ('model_fit', 'critic_fit', 'calibration')
            or census.fold != 'risk' or not set(census.strata) <= set(plan.strata)
            or type(gold) is not tuple or len(gold) != len(census.sample_ids)
            or any(type(y) is not int or not 0 <= y < plan.classes for y in gold)
            or type(observations) is not tuple or len(observations) != len(plan.candidates)+1
            or any(type(o) is not Observation for o in observations)):
        raise ValueError('risk-only complete evidence required')
    policies = (plan.baseline,) + plan.candidates
    for policy, observed in zip(policies, observations):
        observed.validate(census, policy, plan.classes)
    if len({len(o.wall_ns) for o in observations}) != 1:
        raise ValueError('unmatched timing repetitions')
    baseline, candidates = observations[0], observations[1:]
    count = len(plan.candidates) * (len(plan.strata)+1)
    adjusted_alpha = plan.alpha / count
    summaries = []
    for policy, observed in zip(plan.candidates, candidates):
        groups = {}
        for i, group in enumerate(census.groups):
            harm = baseline.predictions[i] == gold[i] and observed.predictions[i] != gold[i]
            previous = groups.get(group, (census.strata[i], False))
            groups[group] = (previous[0], previous[1] or harm)
        slices = {}
        for stratum in ('__all__',) + plan.strata:
            events = [harm for tag,harm in groups.values() if stratum == '__all__' or tag == stratum]
            upper = binomial_upper(sum(events), len(events), adjusted_alpha)
            slices[stratum] = {'groups': len(events), 'harmful_groups': sum(events), 'upper': upper,
                               'passed': len(events) >= plan.minimum_groups and upper <= plan.maximum_harm}
        median_wall = statistics.median(observed.wall_ns)
        saving = 1 - median_wall/statistics.median(baseline.wall_ns)
        no_slower_round = all(a < b for a,b in zip(observed.wall_ns, baseline.wall_ns))
        quality = all(s['passed'] for s in slices.values())
        empirical_cost = no_slower_round and saving >= plan.minimum_wall_saving
        summaries.append({'policy_digest': policy.identity(), 'slices': slices, 'quality_passed': quality,
                          'median_wall_ns': median_wall, 'median_wall_saving': saving,
                          'empirical_cost_passed': empirical_cost, 'eligible': quality and empirical_cost})
    eligible = [s for s in summaries if s['eligible']]
    selected = (min(eligible, key=lambda s: (s['median_wall_ns'], s['policy_digest']))['policy_digest']
                if eligible else plan.baseline.identity())
    selection = Selection(plan.identity(), tuple(p.identity() for p in priors), census.identity(), selected)
    return selection, {'selected': selected, 'baseline': plan.baseline.identity(), 'candidates': summaries,
                       'family_tests': count, 'alpha_per_test': adjusted_alpha,
                       'zero_harm_groups_needed': (math.ceil(math.log(adjusted_alpha)/math.log1p(-plan.maximum_harm))
                                                  if plan.maximum_harm > 0 else None),
                       'fallback': not eligible, 'iid_group_assumption_verified': False,
                       'outcome_attestation_verified': False, 'statistical_speedup_established': False,
                       'production_authorized': False}
