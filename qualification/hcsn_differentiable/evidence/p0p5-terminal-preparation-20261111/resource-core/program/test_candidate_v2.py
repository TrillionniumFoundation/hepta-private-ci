"""New synthetic C2 ancestry and cost failures; no model, actual training, or data read."""
import copy
import unittest

from candidate_accounting import candidate
from resource_arithmetic import matrix_metrics


def development(fraction):
    support=[2904]*10+[2912]
    matrix=[[0]*11 for _ in range(11)]
    for i,n in enumerate(support):
        matrix[i][i]=int(n*fraction)
        matrix[i][(i+1)%11]=n-matrix[i][i]
    _,metrics=matrix_metrics(matrix)
    return dict(metrics,confusion_matrix=matrix,events=31952)


class Proof:
    def __init__(self,chain,replay):
        self.chain,self.replay=chain,replay
    def candidate(self,name):
        return self.chain,self.replay


def fixture(final=4,status='completed_development'):
    ds={n:development(q) for n,q in [(1,.1),(2,.2),(3,.4)]}
    fit={'name':'hcsn-s101-lr0.003','seed':101,'plan':{'seed':101,'learning_rate':.003},
         'report_bytes':10,'report_sha256':'a'*64,'outer':{'whole_process_wall_seconds':100.,'hard_wall_seconds':14400},
         'source_before':{'frozen.py':'b'*64},'memorization':{'passed':True},'status':'budget_exhausted',
         'training_adequacy_established':False,'main_updates':26,'diagnostic_passed':True}
    points=[{'phase':'original','epoch':0,'kind':'development_before','wall_seconds':1.,'quality':.01,
             'CPU_lower_seconds':None,'CPU_upper_seconds':None}]
    points += [{'phase':'original','epoch':n,'kind':'complete_epoch','wall_seconds':n*30.,
                'quality':ds[n]['macro_f1_11_classes'],'CPU_lower_seconds':n*2.,'CPU_upper_seconds':n*2.} for n in (1,2)]
    parent={'fit':fit,'points':points,'row':{'full_chain_charged_wall_seconds':100.,
            'cumulative_CPU_lower_bound_seconds':5.,'max_attempt_RSS_bytes':1000}}
    outer={'parent_full_outer_wall_seconds':100.,'parent_actual_hard_wall_seconds':14400,
        'cumulative_active_wall_cap_seconds':43200,'remaining_at_dispatch_seconds':43100.,
        'whole_process_wall_seconds':30.,'attempt_wrapper_wall_seconds':35.,'child_cpu_seconds':10.,
        'child_peak_rss_bytes':2000,'process_started':True,'terminal_evidence_complete':True,
        'returncode':0 if status=='completed_development' else 2,'result':{'bytes':20,'sha256':'c'*64}}
    epochs=[{'epoch':n,'complete':True,'development':ds[3],'phase_process_wall_seconds':10+n*.1,
             'cumulative_process_wall_seconds':110+n*.1,'phase_process_cpu_seconds':n*.1} for n in range(3,final+1)]
    adequate=final==30 and status=='completed_development'
    report={'schema':'hcsn-c2-soft-wall-continuation-v1','production_execution':True,'arm':'hcsn','seed':101,
        'learning_rate':.003,'confirmation_access':False,'parent_outer':fit['outer'],
        'parent_report':{'bytes':10,'sha256':'a'*64},'parent_full_outer_wall_charged':100.,
        'refund_for_discarded_parent_work_seconds':0,'fresh_independent_fits_started':0,'continuation_attempts_started':1,
        'new_diagnostic_updates':0,'inherited_memorization':fit['memorization'],
        'source_before':fit['source_before'],'source_after':fit['source_before'],
        'source_and_parent_inputs_unchanged':True,'common_and_physical_weights_unchanged':True,
        'parent_retained_epochs':2,'retained_main_updates_at_resume':24,'phase_process_wall_seconds':25.,
        'cumulative_process_wall_seconds':125.,'phase_process_cpu_seconds':8.,'epochs':epochs,
        'cumulative_epochs_completed':final,'cumulative_active_wall_cap_seconds':43200,'maximum_cumulative_epochs':200,
        'new_main_updates':(final-2)*12,'logical_main_updates':final*12,
        'actual_executed_main_updates_logged_all_phases':26+(final-2)*12,'new_unretained_logged_updates':0,
        'stopping':{'best':ds[3]['macro_f1_11_classes'],'best_epoch':3,
                    'plateau_anchor':ds[3]['macro_f1_11_classes'],'stale_epochs':final-3},
        'best_epoch':3,'training_adequacy_established':adequate,'status':status,
        'stop_reason':'development_plateau' if adequate else 'epoch_cap_not_convergence',
        'peak_rss_bytes':2000,'best_checkpoint_sha256':'d'*64}
    spec={'path':'/synthetic/copy/report.json','source_path':'/synthetic/native/report.json','identity':outer['result']}
    chain={'report_identity':spec['identity'],'report_path':spec['source_path'],'inputs':{spec['source_path']:spec['identity']},
        'fit_plan':fit['plan'],'source_map':fit['source_before'],'C2_status':status,'reported_adequacy':adequate,
        'last_complete_epoch':final,'best':{'epoch':3,'identity':{'bytes':100,'sha256':'d'*64}},
        'best_epoch_metrics':ds[3],'C2_observed_training_budget_compliant':True,
        'independent_adequacy_supported':adequate,
        'status':'PASSED_BOUND_EVIDENCE_ONLY' if status=='completed_development' else 'FAILED_OR_INCOMPLETE_CHAIN'}
    replay={'inputs':chain['inputs'],'fresh_development':ds[3]}
    return parent,outer,report,spec,Proof(chain,replay),[2904]*10+[2912]


class CandidateTests(unittest.TestCase):
    def test_prefix_crossing_and_final_wrapper_cost_remain_distinct(self):
        args=fixture()
        row=candidate(*args)
        self.assertTrue(row['quality_verified'],row['errors'])
        self.assertEqual(row['selected_epoch'],3)
        self.assertEqual(row['first_observed_target_crossing']['wall_seconds'],110.3)
        self.assertEqual(row['full_chain_charged_wall_seconds'],135.)
        self.assertEqual(row['cumulative_CPU_lower_bound_seconds'],15.)
        self.assertIsNone(row['cumulative_full_CPU_seconds'])
        self.assertFalse(row['independent_adequate'])

    def test_strict_first_best_and_parent_offset_cannot_be_changed(self):
        for key in ('best','clock','source','actual_updates'):
            args=list(fixture())
            if key=='best':
                args[2]['best_epoch']=4; args[2]['stopping']['best_epoch']=4
            if key=='clock': args[2]['epochs'][0]['cumulative_process_wall_seconds']+=100.
            if key=='source': args[2]['source_and_parent_inputs_unchanged']=False
            if key=='actual_updates': args[2]['actual_executed_main_updates_logged_all_phases']-=2
            row=candidate(*args)
            with self.subTest(key=key):
                self.assertFalse(row['quality_verified'])
                self.assertEqual(row['full_chain_charged_wall_seconds'],135.)
                self.assertTrue(row['errors'])

    def test_recording_failed_or_resource_censored_quality_stays_diagnostic(self):
        for status in ('failed_recording','budget_exhausted'):
            row=candidate(*fixture(status=status))
            with self.subTest(status=status):
                self.assertTrue(row['quality_verified'],row['errors'])
                self.assertFalse(row['producer_adequate'])
                self.assertFalse(row['independent_adequate'])
                self.assertEqual(row['status'],'verified_diagnostic_checkpoint')

    def test_actual_plateau_requires_independent_recording_and_budget_support(self):
        row=candidate(*fixture(final=30))
        self.assertTrue(row['independent_adequate'],row['errors'])
        args=list(fixture(final=30)); args[4].chain['status']='FAILED_OR_INCOMPLETE_CHAIN'
        args[4].chain['independent_adequacy_supported']=False
        row=candidate(*args)
        self.assertTrue(row['producer_adequate'])
        self.assertTrue(row['quality_verified'],row['errors'])
        self.assertFalse(row['independent_adequate'])

    def test_missing_report_and_missing_auditor_never_erase_cost(self):
        args=list(fixture()); args[2]=None; args[4]=None
        missing=candidate(*args,error='absent terminal artifact')
        self.assertFalse(missing['quality_verified'])
        self.assertEqual(missing['full_chain_charged_wall_seconds'],135.)
        args=list(fixture()); args[4]=None
        unverified=candidate(*args)
        self.assertTrue(unverified['history_metadata_checked'])
        self.assertIsNotNone(unverified['raw_saved_quality'])
        self.assertFalse(unverified['quality_verified'])

    def test_missing_CPU_and_wrapper_are_unknown_with_observed_lower_bound(self):
        args=list(fixture()); args[1]['attempt_wrapper_wall_seconds']=None; args[1]['child_cpu_seconds']=None
        row=candidate(*args)
        self.assertIsNone(row['full_chain_charged_wall_seconds'])
        self.assertEqual(row['known_chain_wall_lower_bound_seconds'],130.)
        self.assertEqual(row['cumulative_CPU_lower_bound_seconds'],5.)
        self.assertFalse(row['quality_verified'])
        self.assertIn('C2 child wait4 CPU missing',row['CPU_missing_components'])

    def test_mismatched_independent_CM_or_report_identity_withholds_quality(self):
        for mutation in ('identity','metrics'):
            args=list(fixture())
            if mutation=='identity': args[4].chain['report_identity']={'bytes':20,'sha256':'x'*64}
            else: args[4].replay['fresh_development']=development(.5)
            with self.subTest(mutation=mutation):
                row=candidate(*args)
                self.assertFalse(row['quality_verified'])
                self.assertEqual(row['full_chain_charged_wall_seconds'],135.)


if __name__=='__main__':
    unittest.main()

