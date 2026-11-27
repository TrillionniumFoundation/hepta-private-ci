"""Use a frozen paired-data critic in the existing two-round System2 loop.

The estimate bounds a BIN-AVERAGE net gain under unverified cohort exchangeability,
not a pointwise value or a deterministic scenario support. Resource envelopes are
predeclared, not learned maxima; realized violations are fenced by the executor.
Callback object identity prevents accidental substitution, not hostile Python or
truthful owner provenance. This path never certifies learned-critic efficacy.
"""
from __future__ import annotations

import copy
from dataclasses import asdict, dataclass

from next_round_matrix import _digest
from paired_execution import _integer, _sha
from paired_critic import COEFFICIENTS, _number, bucket, validate_artifact


def case_fingerprint(task, candidate, feedback):
    # Exclude timestamps so relabeling a duplicated problem does not create a
    # fresh case. Source authenticity and semantic near-duplicates remain external.
    return _digest([task.prompt, [text for text, _ in task.observations], candidate, feedback])


@dataclass(frozen=True)
class EmpiricalEstimate:
    context_id: str
    critic_sha256: str
    protocol_id: str
    support_sha256: str
    observed_through_ns: int
    valid_until_ns: int
    bucket_id: str
    net_gain_lower: float
    fit_groups: int
    calibration_groups: int
    calibration_radius: float
    duration_upper_ns: int
    formula_work_upper: int

    def validate(self):
        for v in (self.context_id,self.critic_sha256,self.protocol_id,self.support_sha256):
            _sha(v, 'empirical estimate identity')
        for v in (self.observed_through_ns,self.valid_until_ns,self.duration_upper_ns):
            _integer(v,'estimate time',1)
        if self.valid_until_ns <= self.observed_through_ns or self.duration_upper_ns > 3_600_000_000_000:
            raise ValueError('invalid estimate validity or segment duration')
        for n in (self.fit_groups,self.calibration_groups):
            _integer(n,'independent group count',2)
            if n > 4096: raise ValueError('group count above protocol bound')
        _integer(self.formula_work_upper,'segment work envelope')
        if self.formula_work_upper > 10**18: raise ValueError('segment work envelope too large')
        _number(self.net_gain_lower,'net gain lower',-1_000_001.,1.)
        _number(self.calibration_radius,'group radius',0.,1e8)
        if self.bucket_id not in {f'{i}:{j}' for i in range(4) for j in range(4)}:
            raise ValueError('unknown public length bucket')


class FrozenPairedCritic:
    """No fit at invocation: immutable copy of data summaries, exact callable pair."""
    def __init__(self, artifact, *, expected_id, callback_profile_sha256, propose, verify):
        validate_artifact(artifact, expected_id)
        if callback_profile_sha256 != artifact['protocol']['callback_profile_sha256']:
            raise ValueError('unmatched generator/verifier owner profile')
        if not callable(propose) or not callable(verify):
            raise ValueError('callable bound adapters required')
        self._artifact = copy.deepcopy(artifact)
        self._id, self._propose, self._verify = expected_id, propose, verify

    def validate_binding(self, policy, propose, verify):
        validate_artifact(self._artifact,self._id)
        p = self._artifact['protocol']
        if propose is not self._propose or verify is not self._verify:
            raise ValueError('generator/verifier callback substituted after critic binding')
        if (policy.get('empirical_protocol_id') != p['protocol_id'] or policy['critic_sha256'] != self._id
                or policy['objective_sha256'] != p['objective_sha256'] or policy['subject_id'] != p['subject_id']
                or policy['critic_cutoff_ns'] != p['cutoff_ns'] or policy['expires_at_ns'] > p['expires_at_ns']
                or _digest({k:policy[k] for k in COEFFICIENTS}) != _digest(p['coefficients'])
                or policy['execution']['max_rounds'] != 2 or policy['execution']['max_calls'] != 5):
            raise ValueError('empirical critic requires its fixed objective, units and two-round policy')
        if self._artifact.get('capture_binding') is not None:
            from aten_work import PROFILE as base_profile
            profile = policy['execution']['meter_policy'].get('arithmetic_profile', base_profile)
            if profile != self._artifact['capture_binding']['arithmetic_profile']:
                raise ValueError('runtime arithmetic profile differs from measured critic data')
        self._policy_id = policy['policy_id']

    def __call__(self, task, candidate, feedback, context):
        if not hasattr(self,'_policy_id') or context.policy_id != self._policy_id:
            raise ValueError('critic must be bound by the execution owner first')
        if (_digest(asdict(task)) != context.task_sha256 or _digest(candidate) != context.candidate_sha256
                or _digest(feedback) != context.feedback_sha256):
            raise ValueError('critic input differs from the bound decision context')
        p = self._artifact['protocol']
        if context.rounds_left != 1 or context.calls_left != 3:
            return None  # One additional segment only; no pretend multistep value.
        if not p['cutoff_ns'] < task.as_of_ns <= context.as_of_ns < p['expires_at_ns']:
            return None
        if case_fingerprint(task,candidate,feedback) in {q['case_sha256'] for q in p['pairs']}:
            return None  # No training/calibration case may be recycled as fresh.
        b = bucket(p,len(candidate.encode()),len(feedback.encode()))
        entry = self._artifact['table'][b]
        if not entry['supported']:
            return None
        return EmpiricalEstimate(context.context_id,self._id,p['protocol_id'],_digest([self._id,b,entry]),
                                 p['cutoff_ns'],p['expires_at_ns'],b,entry['net_gain_lower'],
                                 entry['fit_groups'],entry['calibration_groups'],entry['radius'],
                                 p['duration_upper_ns'],p['formula_work_upper'])

    def receipt(self):
        p = self._artifact['protocol']
        result = dict(artifact_id=self._id,protocol_id=p['protocol_id'],dataset_sha256=self._artifact['dataset_sha256'],
                    callback_profile_sha256=p['callback_profile_sha256'],observer_sha256=p['observer_sha256'],
                    estimator='frozen_group_mean_table',paired_attempts=len(p['pairs']),
                    failed_attempts=self._artifact['failed_attempts'],family_alpha=p['alpha'],
                    pointwise_confidence_established=False,owner_authenticity_verified=False,
                    cohort_exchangeability_verified=False,neural_critic_trained=False,
                    empirical_critic_fitted=True,final_efficacy_established=False)
        if 'capture_binding' in self._artifact:
            result['capture_binding'] = copy.deepcopy(self._artifact['capture_binding'])
        return result


def decide_empirical(policy, context, estimate, *, now_ns, resources):
    """Already discounted/costed PAIR difference: do not charge those costs twice."""
    if estimate is not None and type(estimate) is not EmpiricalEstimate:
        raise ValueError('empirical policy cannot consume deterministic scenario support')
    report = dict(policy_id=policy['policy_id'],context_id=context.context_id,context=asdict(context),
                  decision_at_ns=now_ns,post_critic_resources=copy.deepcopy(resources),estimate=None,
                  estimate_id=None,continue_computation=False,reason='unsupported_continuation',
                  comparison='conditional_group_mean_net_gain',confidence_bound_established=False,
                  pointwise_confidence_established=False,support_authenticity_verified=False,
                  sunk_critic_cost_subtracted_again=False,segment_cost_subtracted_again=False)
    if estimate is None: return report
    estimate.validate()
    if (estimate.context_id != context.context_id or estimate.critic_sha256 != policy['critic_sha256']
            or estimate.protocol_id != policy['empirical_protocol_id']
            or estimate.observed_through_ns != policy['critic_cutoff_ns']
            or not estimate.observed_through_ns < context.as_of_ns <= now_ns):
        raise ValueError('empirical estimate identity or cutoff differs')
    report.update(estimate=asdict(estimate),estimate_id=_digest(asdict(estimate)),net_gain_lower=estimate.net_gain_lower)
    if (now_ns >= min(policy['expires_at_ns'],estimate.valid_until_ns)
            or now_ns-estimate.observed_through_ns > policy['max_estimate_age_ns']):
        return {**report,'reason':'expired_support'}
    remaining,wall = resources['remaining_formula_work'],resources['remaining_wall_ns']
    if remaining is None or context.remaining_formula_work is None:
        return {**report,'reason':'incomplete_work_coverage'}
    _integer(remaining,'remaining work');_integer(wall,'remaining wall time')
    if remaining > context.remaining_formula_work or wall > context.remaining_wall_ns:
        raise ValueError('resources increased during critic invocation')
    if context.rounds_left != 1 or context.calls_left != 3:
        return {**report,'reason':'unsupported_horizon'}
    report.update(worst_branch_formula_work=estimate.formula_work_upper,worst_branch_duration_ns=estimate.duration_upper_ns)
    if estimate.formula_work_upper > remaining or estimate.duration_upper_ns >= wall:
        return {**report,'reason':'infeasible_continuation'}
    proceed = estimate.net_gain_lower > policy['minimum_margin']
    return {**report,'continue_computation':proceed,'reason':'supported_net_gain' if proceed else 'no_supported_net_gain'}
