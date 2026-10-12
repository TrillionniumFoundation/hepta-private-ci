"""Exact-binomial, independent-fold and real guarded-execution regressions."""

from dataclasses import replace
import math
import unittest

from development_quality import (BoundPolicy, Census, Observation, RiskPlan,
                                 binomial_upper, digest, select_guarded)


def census(fold, n, time, *, groups=None, strata=None, inputs=None):
    return Census('research', fold, tuple(f'{fold}-{i}' for i in range(n)),
                  inputs or tuple(digest([fold, i]) for i in range(n)),
                  groups or tuple(f'{fold}-group-{i}' for i in range(n)),
                  strata or ('slice',)*n, (time,)*n)


def history():
    return tuple(census(name, 2, i) for i,name in enumerate(('model_fit', 'critic_fit', 'calibration')))


def fixture(n=512):
    base = BoundPolicy('fixed', 4, 0., 'a'*64, None, 'b'*64)
    child = BoundPolicy('learned', 4, 0., 'a'*64, 'c'*64, 'b'*64)
    plan = RiskPlan(base, (child,), ('slice',))
    risk = census('risk', n, 3)
    def observed(policy, depths, times):
        return Observation(policy.identity(), risk.identity(), (0,)*n, (depths,)*n, (times,)*3, (times,)*3)
    return plan, risk, (0,)*n, (observed(base, 4, 100), observed(child, 1, 50))


class BinomialTests(unittest.TestCase):
    def test_zero_failures_is_not_zero_risk(self):
        bound = binomial_upper(0, 64, .025)
        self.assertAlmostEqual(bound, 1 - .025**(1/64), places=10)
        self.assertGreater(bound, .05)
        self.assertEqual(binomial_upper(64, 64, .05), 1)
        self.assertEqual(binomial_upper(0, 0, .05), 1)

    def test_small_sample_exact_coverage_against_direct_binomial_oracle(self):
        for n in (2, 5, 10, 20):
            for alpha in (.01, .05, .2):
                bounds = [binomial_upper(k, n, alpha) for k in range(n+1)]
                for p in (.02, .1, .3, .5, .8, .95):
                    failure = sum(math.comb(n,k)*p**k*(1-p)**(n-k)
                                  for k,b in enumerate(bounds) if b < p)
                    self.assertLessEqual(failure, alpha + 1e-11)

    def test_monotone_in_events_evidence_and_multiplicity(self):
        values = [binomial_upper(k, 512, .01) for k in range(12)]
        self.assertEqual(values, sorted(values))
        self.assertLess(binomial_upper(0, 512, .01), binomial_upper(0, 128, .01))
        self.assertGreater(binomial_upper(3, 512, .001), binomial_upper(3, 512, .05))

    def test_extreme_valid_counts_stay_finite(self):
        for k in (1, 2000, 4095):
            value = binomial_upper(k, 4096, .00001)
            self.assertTrue(math.isfinite(value))
            self.assertTrue(k/4096 < value <= 1)

    def test_invalid_binomial_arguments(self):
        for args in ((True, 64, .05), (0, True, .05), (65, 64, .05), (0, 64, math.nan), (0, 64, 0)):
            with self.assertRaises(ValueError):
                binomial_upper(*args)


class RiskSelectionTests(unittest.TestCase):
    def test_clean_faster_candidate_selected_under_explicit_group_assumption(self):
        plan, risk, gold, observed = fixture()
        selected, report = select_guarded(plan, history(), risk, gold, observed)
        self.assertEqual(selected.selected_policy_digest, plan.candidates[0].identity())
        self.assertFalse(report['fallback'])
        self.assertFalse(report['production_authorized'])
        self.assertFalse(report['iid_group_assumption_verified'])
        self.assertEqual(report['family_tests'], 2)

    def test_no_quality_tradeoff_for_speed(self):
        plan, risk, gold, observed = fixture()
        bad = replace(observed[1], predictions=(1,)*32 + (0,)*480)
        chosen, report = select_guarded(plan, history(), risk, gold, (observed[0], bad))
        self.assertEqual(chosen.selected_policy_digest, plan.baseline.identity())
        self.assertFalse(report['candidates'][0]['quality_passed'])

    def test_quality_gains_do_not_cancel_harmful_answers(self):
        plan, risk, gold, observed = fixture()
        baseline = replace(observed[0], predictions=(1,)*32 + (0,)*480)
        candidate = replace(observed[1], predictions=(0,)*32 + (1,)*32 + (0,)*448)
        _, report = select_guarded(plan, history(), risk, gold, (baseline, candidate))
        self.assertEqual(report['candidates'][0]['slices']['__all__']['harmful_groups'], 32)
        self.assertTrue(report['fallback'])

    def test_literal_zero_harm_requirement_retains_baseline(self):
        plan, risk, gold, observed = fixture()
        chosen, report = select_guarded(replace(plan, maximum_harm=0), history(), risk, gold, observed)
        self.assertEqual(chosen.selected_policy_digest, plan.baseline.identity())
        self.assertIsNone(report['zero_harm_groups_needed'])
        self.assertTrue(report['fallback'])

    def test_small_clean_sample_does_not_establish_two_percent_floor(self):
        plan, risk, gold, observed = fixture(64)
        _, report = select_guarded(plan, history(), risk, gold, observed)
        self.assertTrue(report['fallback'])
        self.assertGreater(report['zero_harm_groups_needed'], 64)

    def test_rows_in_one_group_cannot_manufacture_sample_size(self):
        plan, risk, gold, observed = fixture()
        risk = replace(risk, groups=('one-group',)*512)
        observed = tuple(replace(o, census_digest=risk.identity()) for o in observed)
        _, report = select_guarded(plan, history(), risk, gold, observed)
        self.assertEqual(report['candidates'][0]['slices']['__all__']['groups'], 1)
        self.assertTrue(report['fallback'])

    def test_duplicate_content_across_groups_rejected(self):
        _, risk, _, _ = fixture()
        with self.assertRaises(ValueError):
            replace(risk, input_digests=(risk.input_digests[0],)*512).validate()

    def test_missing_preregistered_stratum_is_not_silently_omitted(self):
        plan, risk, gold, observed = fixture()
        _, report = select_guarded(replace(plan, strata=('slice','unobserved')), history(), risk, gold, observed)
        self.assertTrue(report['fallback'])
        self.assertEqual(report['family_tests'], 3)
        self.assertEqual(report['candidates'][0]['slices']['unobserved']['upper'], 1)

    def test_protected_slice_failure_despite_stronger_overall_rate(self):
        plan, risk, gold, observed = fixture()
        plan = replace(plan, strata=('large','small'))
        risk = replace(risk, strata=('large',)*448 + ('small',)*64)
        observed = tuple(replace(o, census_digest=risk.identity()) for o in observed)
        observed = (observed[0], replace(observed[1], predictions=(0,)*508 + (1,)*4))
        _, report = select_guarded(plan, history(), risk, gold, observed)
        self.assertTrue(report['fallback'])
        self.assertFalse(report['candidates'][0]['slices']['small']['passed'])

    def test_clean_but_slower_or_unstable_cost_falls_back(self):
        plan, risk, gold, observed = fixture()
        for timing in ((110,110,110), (50,110,50), (99,99,99)):
            child = replace(observed[1], wall_ns=timing)
            _, report = select_guarded(plan, history(), risk, gold, (observed[0], child))
            self.assertTrue(report['candidates'][0]['quality_passed'])
            self.assertTrue(report['fallback'])

    def test_entire_portfolio_and_order_required(self):
        plan, risk, gold, observed = fixture()
        for invalid in (observed[::-1], observed[:1], observed + (observed[1],)):
            with self.assertRaises(ValueError):
                select_guarded(plan, history(), risk, gold, invalid)

    def test_changed_input_or_policy_evidence_rejected(self):
        plan, risk, gold, observed = fixture()
        for key in ('census_digest', 'policy_digest'):
            with self.assertRaises(ValueError):
                select_guarded(plan, history(), risk, gold,
                               (observed[0], replace(observed[1], **{key:'f'*64})))

    def test_missing_predictions_and_invalid_resource_observations_rejected(self):
        plan, risk, gold, observed = fixture()
        for change in ({'predictions':(0,)*511}, {'predictions':(True,)*512},
                       {'wall_ns':(1,2)}, {'wall_ns':(1,True,3)}, {'depths':(5,)*512}):
            with self.assertRaises(ValueError):
                select_guarded(plan, history(), risk, gold, (observed[0],replace(observed[1], **change)))

    def test_group_time_content_scope_and_wrong_fold_rejected(self):
        plan, risk, gold, observed = fixture()
        for changed in (replace(risk, scope='other'), replace(risk, observed_at=(2,)*512),
                        replace(risk, groups=(history()[0].groups[0],)*512),
                        replace(risk, input_digests=(history()[0].input_digests[0],)+risk.input_digests[1:]),
                        replace(risk, fold='heldout')):
            with self.assertRaises(ValueError):
                select_guarded(plan, history(), changed, gold, observed)

    def test_duplicate_or_foreign_policies_rejected(self):
        plan, _, _, _ = fixture()
        for candidates in ((plan.baseline,), (plan.candidates[0],)*2,
                           (replace(plan.candidates[0], model_digest='d'*64),)):
            with self.assertRaises(ValueError):
                replace(plan, candidates=candidates).validate()


if __name__ == '__main__':
    unittest.main()
