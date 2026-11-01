"""Exercise proof-obligation failures and actual stored numerical witnesses."""

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))
from propagation.certification import CONTINUOUS_OBLIGATIONS, certify


def main():
    nested = json.loads((ROOT/'NESTED_REFINEMENT.json').read_text())
    rows = []
    for row in nested['action_rows']:
        finite = certify(row['qvalues'], target='computed_finite_reference', horizon=3,
                         reference_qvalues=row['reference_qvalues'])
        continuous = certify(row['qvalues'], target='continuous_financial_task', horizon=3,
                             reference_qvalues=row['reference_qvalues'])
        assert continuous['status'] == 'uncertified'
        assert not continuous['continuous_optimality_claim_allowed']
        assert finite['whole_policy_regret_bound'] is None
        rows.append(dict(mean=row['mean'], width=row['width'], p0=row['p0'], dt=row['dt'],
            factor=row['factor'], inherited_witness=row['inherited_witness'], finite=finite, continuous=continuous))
    # This supplied Q-bound only concerns an observable, and its arithmetic
    # padding has not been formally certified: the claim must stay blocked.
    observable = json.loads((ROOT/'OBSERVABLE_BUDGET.json').read_text())
    observable_gates = []
    obligations = {k: True for k in CONTINUOUS_OBLIGATIONS}
    obligations['arithmetic_error_included'] = False
    for row in observable['constructed_first_hit_decision']:
        gate = certify(row['qvalues'], target='continuous_declared_observable', horizon=1,
            continuous_uniform_q_error=row['conditional_gap_check']['value_error'],
            continuous_obligations=obligations,
            continuous_evidence_description='Constructed safe/advance first-hit payoff only; mathematical enclosure is conditional on numerical arithmetic.')
        assert gate['status'] == 'uncertified'
        assert gate['missing_evidence'] == ['arithmetic_error_included']
        observable_gates.append(dict(n_active=row['n_active'], certificate=gate,
                                    mathematical_gap_pass_conditional_on_arithmetic=row['conditional_gap_check']['action_certified']))
    # A local vector bound must not be silently promoted to a policy bound.
    local = certify([1., .5], target='computed_finite_reference', reference_qvalues=[.99, .51],
                    horizon=3, all_policy_value_error=.02, all_policy_bound_justified=False)
    assert local['whole_policy_regret_bound'] is None
    conditional_policy = certify([1., .5], target='computed_finite_reference', reference_qvalues=[.99, .51],
                    horizon=3, all_policy_value_error=.02, all_policy_bound_justified=True)
    assert abs(conditional_policy['whole_policy_regret_bound']-(.04+3e-12)) < 1e-16
    assert conditional_policy['continuous_optimality_claim_allowed'] is False
    # Ties are tested with exact rational arithmetic on the supplied float values.
    ties = certify([1., 1.+5e-13], target='computed_finite_reference',
                   reference_qvalues=[1., 1.+5e-13], horizon=3)
    assert ties['action'] == 0 and not ties['action_gap_certified']
    assert abs(ties['tie_loss_budget']-3e-12) < 1e-27
    # An omitted continuous obligation must fail even with a claimed zero bound.
    incomplete = certify([1., 0.], continuous_uniform_q_error=0.,
                          continuous_obligations={k:True for k in CONTINUOUS_OBLIGATIONS if k != 'spatial_error_included'},
                          continuous_evidence_description='Synthetic negative test; not evidence.')
    assert incomplete['status'] == 'uncertified'
    summary = []
    for factor in (1, 2):
        part = [r for r in rows if r['factor'] == factor and not r['inherited_witness']]
        summary.append(dict(factor=factor, contexts=len(part),
            finite_vector_action_certificates=sum(r['finite']['action_gap_certified'] for r in part),
            continuous_action_certificates=sum(r['continuous']['action_gap_certified'] for r in part),
            whole_policy_certificates=sum(r['finite']['whole_policy_regret_bound'] is not None for r in part)))
    payload = dict(summary=summary, rows=rows, constructed_observable_gates=observable_gates,
        negative_tests_passed=True,
        synthetic_uniform_policy_bound_formula_test=conditional_policy,
        scope='The synthetic policy-bound test checks implementation of 2D+H*tau; it is not evidence that such D has been proved for R13. Actual finite-reference decisions certify only the supplied vectors. Every actual continuous financial-task and full-policy claim is blocked.')
    path = ROOT/'CERTIFICATION_GATE.json'
    if path.exists():
        raise ValueError('Evidence is append-only')
    path.write_text(json.dumps(payload, indent=2, allow_nan=False)+'\n')
    print(json.dumps({'summary':summary,'negative_tests_passed':True,'scope':payload['scope']}, indent=2))


if __name__ == '__main__':
    main()
