"""Mechanism and negative evidence tests, never a real learning result."""
import unittest
from equal_budget_audit import AuditError, evaluate_panel, validate_panel


def fixture():
    cases = []
    for i, split in enumerate(('test', 'future1', 'future2', 'future3')):
        for j in range(8):
            cases.append(dict(
                case_id=f'{split}.{j}', group_id=f'{split}.group.{j}',
                split=split, observed_utc=f'2026-{i+2:02d}-{j+1:02d}T00:00:00Z',
                scope_id='project.a', source_digest=f'{len(cases)+1:064x}',
                outcome_receipt_digest=f'{len(cases)+100:064x}', truth=j % 2,
                predictions=[
                    dict(arm_id=a, probability=(0.8 if j % 2 else 0.2) if a == 'candidate' else 0.5,
                         prediction_receipt_digest=f'{1000+i*100+j*2+k:064x}',
                         observed_cost_units=1.0, measured_latency_micros=100,
                         trained_parameter_count=100 if a == 'candidate' else 0)
                    for k, a in enumerate(('baseline', 'candidate'))
                ]))
    return dict(
        schema='hepta.stem.equal-budget-paired.v1', plan_digest='a' * 64,
        frozen_before_utc='2026-01-01T00:00:00Z',
        scope_id='project.a', host_profile_digest='b' * 64,
        baseline_arm='baseline',
        lifecycle_cost_units={
            a: {k: 1.0 for k in ('training', 'evaluation', 'migration', 'storage', 'source_read')}
            for a in ('baseline', 'candidate')
        },
        arms=[dict(arm_id=a, model_digest=f'{k+1:064x}', policy_digest=f'{k+3:064x}')
              for k, a in enumerate(('baseline', 'candidate'))],
        cases=cases)


class PairedAudit(unittest.TestCase):
    def test_complete_paired_future_panel_mechanism_not_authority(self):
        result = evaluate_panel(fixture())
        self.assertEqual(result['independent_groups'], 32)
        self.assertTrue(result['comparisons'][0]['passes_statistical_cost_screen'])
        self.assertGreater(result['comparisons'][0]['future_group_gain_lcb95'], 0)
        self.assertEqual(result['production_promotion'], 'DENY_ALL')
        self.assertFalse(result['comparisons'][0]['independent_source_attestation'])

    def test_missing_arm_and_duplicate_are_rejected(self):
        a = fixture()
        a['cases'][0]['predictions'].pop()
        with self.assertRaises(AuditError):
            validate_panel(a)
        a = fixture()
        a['cases'][0]['predictions'][1]['arm_id'] = 'baseline'
        with self.assertRaises(AuditError):
            validate_panel(a)

    def test_group_source_time_and_scope_leakage(self):
        for change in ('group', 'source', 'time', 'scope', 'freeze'):
            a = fixture()
            if change == 'group':
                a['cases'][8]['group_id'] = a['cases'][0]['group_id']
            if change == 'source':
                a['cases'][8]['source_digest'] = a['cases'][0]['source_digest']
            if change == 'time':
                a['cases'][8]['observed_utc'] = '2026-01-01T00:00:00Z'
            if change == 'scope':
                a['cases'][8]['scope_id'] = 'other'
            if change == 'freeze':
                a['frozen_before_utc'] = '2026-06-01T00:00:00Z'
            with self.subTest(change=change), self.assertRaises(AuditError):
                validate_panel(a)

    def test_bad_cost_and_nan_probability_and_fake_signatures(self):
        for field, value in [('observed_cost_units', 0), ('observed_cost_units', -1),
                             ('probability', float('nan')), ('probability', 1),
                             ('prediction_receipt_digest', 'missing')]:
            a = fixture()
            a['cases'][0]['predictions'][0][field] = value
            with self.subTest(field=field), self.assertRaises(AuditError):
                validate_panel(a)

    def test_cost_too_high_blocks_even_if_task_gain_positive(self):
        a = fixture()
        for row in a['cases']:
            row['predictions'][1]['observed_cost_units'] = 2.0
        r = evaluate_panel(a)['comparisons'][0]
        self.assertGreater(r['matched_lifecycle_cost_ratio'], 1)
        self.assertFalse(r['passes_statistical_cost_screen'])

    def test_missing_or_infinite_lifecycle_cost_never_passes(self):
        a = fixture()
        a['lifecycle_cost_units']['candidate']['training'] = float('nan')
        with self.assertRaises(AuditError):
            validate_panel(a)
        a = fixture()
        del a['lifecycle_cost_units']['candidate']['evaluation']
        with self.assertRaises(AuditError):
            validate_panel(a)
        a = fixture()
        a['lifecycle_cost_units']['candidate']['training'] = 1_000_000
        self.assertFalse(evaluate_panel(a)['comparisons'][0]['passes_statistical_cost_screen'])

    def test_a_bad_future_window_blocks_even_with_overall_gain(self):
        a = fixture()
        for row in a['cases']:
            if row['split'] == 'future3':
                row['predictions'][1]['probability'] = 0.02 if row['truth'] == 1 else 0.98
        r = evaluate_panel(a)['comparisons'][0]
        self.assertLess(r['per_future_window_brier_gain']['future3'], 0)
        self.assertFalse(r['passes_statistical_cost_screen'])

    def test_receipt_reuse_or_arm_alias_is_rejected(self):
        for kind in ("outcome", "prediction", "arm_alias"):
            p = fixture()
            if kind == "outcome":
                p["cases"][1]["outcome_receipt_digest"] = p["cases"][0]["outcome_receipt_digest"]
            elif kind == "prediction":
                p["cases"][1]["predictions"][0]["prediction_receipt_digest"] = (
                    p["cases"][0]["predictions"][0]["prediction_receipt_digest"])
            else:
                p["arms"][1]["model_digest"] = p["arms"][0]["model_digest"]
                p["arms"][1]["policy_digest"] = p["arms"][0]["policy_digest"]
            with self.subTest(kind=kind), self.assertRaises(AuditError):
                validate_panel(p)

    def test_source_group_pseudoreplication_rejected(self):
        p = fixture()
        for row in p["cases"]:
            if row["split"] == "future3":
                row["group_id"] = f"future3.only.{row['truth']}"
        with self.assertRaises(AuditError):
            validate_panel(p)

    def test_multiple_arm_bootstrap_is_familywise_adjusted(self):
        p = fixture()
        p["arms"].append(dict(p["arms"][1], arm_id="candidate.two", model_digest="e" * 64,
                              policy_digest="f" * 64))
        p["lifecycle_cost_units"]["candidate.two"] = dict(p["lifecycle_cost_units"]["candidate"])
        for index, row in enumerate(p["cases"]):
            row["predictions"].append(dict(row["predictions"][1], arm_id="candidate.two",
                prediction_receipt_digest=f"{30000+index:064x}"))
        result = evaluate_panel(p)
        self.assertEqual(result["familywise_correction"], "bonferroni_over_declared_alternatives")
        self.assertAlmostEqual(result["one_sided_per_arm_alpha"], 0.025)
        for arm in result["comparisons"]:
            self.assertLessEqual(arm["future_group_gain_familywise_lcb"],
                                 arm["future_group_gain_lcb95"])
            self.assertEqual(arm["selection_authority"], "DENY_ALL")


    def test_test_window_inference_cost_is_not_free(self):
        panel = fixture()
        for row in panel["cases"]:
            if row["split"] == "test":
                row["predictions"][1]["observed_cost_units"] = 20.0
        result = evaluate_panel(panel)
        comparison = result["comparisons"][0]
        self.assertGreater(comparison["future_group_gain_familywise_lcb"], 0)
        self.assertGreater(comparison["matched_lifecycle_cost_ratio"], 1)
        self.assertFalse(comparison["passes_statistical_cost_screen"])

    def test_cost_boundary_excludes_unobserved_pretraining_and_unsigned_units(self):
        coverage = evaluate_panel(fixture())["cost_coverage"]
        self.assertEqual(coverage["scored_inference_windows"],
                         ["test", "future1", "future2", "future3"])
        self.assertEqual(coverage["inherited_pretraining_cost"],
                         "not_measured_or_included")
        self.assertFalse(coverage["cost_units_independently_verified"])
        self.assertFalse(coverage["shared_overhead_allocation_independently_verified"])

    def test_a_cheap_test_does_not_hide_future_excess_cost(self):
        panel = fixture()
        for row in panel["cases"]:
            row["predictions"][1]["observed_cost_units"] = (
                0.001 if row["split"] == "test" else 1.5)
        comparison = evaluate_panel(panel)["comparisons"][0]
        self.assertGreater(comparison["matched_lifecycle_cost_ratio"], 1)
        self.assertFalse(comparison["passes_statistical_cost_screen"])

    def test_no_promotion_even_for_green_self_claims(self):
        r = evaluate_panel(fixture())
        self.assertFalse(r['comparisons'][0]['model_execution_independently_verified'])
        self.assertEqual(r['comparisons'][0]['selection_authority'], 'DENY_ALL')


if __name__ == '__main__':
    unittest.main()
