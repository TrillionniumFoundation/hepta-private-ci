"""Synthetic independent-review provenance; never executes historical artifacts."""
import copy
import unittest
from historical_review import bind_historical_adequacy
from resource_arithmetic import roster


def fixture():
    names=[n for n in roster() if not n.startswith('hcsn-')]
    failures=['snn_plif-s101-lr0.001','cfc-s211-lr0.001','snn_plif-s307-lr0.001']
    fits,rows,originals,children={},[],[],[]
    for name in names:
        adequate=name not in failures
        fits[('original',name)]={'report_sha256':name+'-parent'}
        rows.append({'name':name,'producer_adequate':adequate,'independent_adequate':False,
                     'selected_epoch':3,'quality':.4,'diagnostic_passed':adequate})
        originals.append({'name':name,'audit_status':'passed_completed_original_baseline',
            'report_sha256':name+'-parent','memorization_passed':adequate,'original_stop_reason':'development_plateau',
            'independent_adequacy':{'independently_recomputed':adequate,'first_plateau_epoch':30},
            'epochs':30,'best_epoch':3,'independent_selected_development':{'macro_f1_11_classes':.4}})
    for name in names[:7]:
        fits[('C1',name)]={'report_sha256':name+'-child'}
        children.append({'name':name,'audit_status':'passed_completed_C1_chain_artifacts',
            'parent_report_sha256':name+'-parent','child_report_sha256':name+'-child',
            'phase_chain':{'logical_phase_chain_checks_passed':True,'derived_chain_adequacy':True,
                           'combined_state':{'best_epoch':3}},
            'independent_selected_development':{'macro_f1_11_classes':.4}})
    common={'confirmation_access':False,'training_performed':False,'optimizer_steps_executed':0,
            'identity_checks':{'source_unchanged':True,'pinned_inputs_unchanged':True}}
    first=dict(copy.deepcopy(common),schema='fresh42-completed-baseline36-plus-C1-independent-review-v1',
               passed=False,original_baseline_records=originals)
    second=dict(copy.deepcopy(common),schema='baseline36-C1-independent-clock-supplement-v2',passed=True,
        C1_records=children,memorization_failures_retained=failures,
        original36_reuse={'prior_result_sha256':'a'*64,'original36_passed_subrecords_reused':36,
                         'all_prior_input_and_source_file_hashes_rechecked':True})
    ids={'baseline_v1':{'bytes':1,'sha256':'a'*64},'baseline_v2':{'bytes':2,'sha256':'b'*64}}
    return rows,fits,{'baseline_v1':first,'baseline_v2':second},ids


class HistoricalReviewTests(unittest.TestCase):
    def test_published_independent_subrecords_support33_without_relabeling_old_failure(self):
        args=fixture(); result=bind_historical_adequacy(*args)
        self.assertEqual(sum(r['independent_adequate'] for r in args[0]),33)
        self.assertFalse(result['prior_overall_passed'])
        self.assertFalse(result['training_adequacy_reexecuted_now'])
        self.assertTrue(all(not r['independent_adequacy_reexecuted_now'] for r in args[0]))

    def test_producer_claim_cannot_replace_independent_adequacy(self):
        args=list(fixture())
        next(r for r in args[0] if not r['diagnostic_passed'])['producer_adequate']=True
        with self.assertRaises(ValueError): bind_historical_adequacy(*args)

    def test_changed_original_C1_identity_or_missing_candidate_refused(self):
        for mutation in ('original','child','missing'):
            args=list(fixture())
            if mutation=='original': args[2]['baseline_v1']['original_baseline_records'][0]['report_sha256']='wrong'
            if mutation=='child': args[2]['baseline_v2']['C1_records'][0]['child_report_sha256']='wrong'
            if mutation=='missing': args[2]['baseline_v1']['original_baseline_records'].pop()
            with self.subTest(mutation=mutation),self.assertRaises(ValueError): bind_historical_adequacy(*args)

    def test_failed_reuse_source_or_changed_best_refused(self):
        for mutation in ('reuse','source','best','quality'):
            args=list(fixture())
            if mutation=='reuse': args[2]['baseline_v2']['original36_reuse']['prior_result_sha256']='wrong'
            if mutation=='source': args[2]['baseline_v2']['identity_checks']['source_unchanged']=False
            if mutation=='best': args[2]['baseline_v2']['C1_records'][0]['phase_chain']['combined_state']['best_epoch']=4
            if mutation=='quality': args[2]['baseline_v2']['C1_records'][0]['independent_selected_development']['macro_f1_11_classes']=.5
            with self.subTest(mutation=mutation),self.assertRaises(ValueError): bind_historical_adequacy(*args)


if __name__=='__main__':
    unittest.main()

