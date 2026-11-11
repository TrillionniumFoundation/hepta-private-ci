"""Hand-controlled clocks and wrapper costs, using synthetic saved metadata only."""
import copy
import unittest

from old_metadata import historical_candidate, parent_cost, phase_points


def fit(phase='original'):
    parent={'name':'gru-s101-lr0.001','arm':'gru','seed':101,'phase':'original','report_sha256':'a'*64,
        'report_bytes':1,'source_unchanged':True,'common_weights_unchanged':True,'plan':{'learning_rate':.001},
        'outer':{'whole_process_wall_seconds':100.,'result_sha256':'a'*64},'peak_rss_bytes':1000,
        'all_report_clock_fields':{'cpu_seconds':40.},'best_epoch':1,'selected_development':None,
        'training_adequacy_established':False,'diagnostic_passed':False,'stop_reason':'epoch_cap_not_convergence'}
    child=dict(parent,phase='C1',report_sha256='b'*64,best_epoch=2,parent_report_sha256='a'*64,
        parent_cpu_lower_bound_seconds=50.,plan={'parent_plan':parent['plan']},
        outer={'whole_process_wall_seconds':30.,'attempt_wrapper_wall_seconds':35.,'result_sha256':'b'*64,
               'parent_outer_wall_seconds':100.,'phase_full_process_cpu_seconds':10.})
    return parent if phase=='original' else child


def observation(parent, epoch, wall, kind='complete_epoch'):
    cm=[[int(i==j) for j in range(11)] for i in range(11)]
    d={'confusion_matrix':cm,'events':11,'accuracy':1.,'macro_f1_11_classes':1.,
       'macro_f1_present_classes':1.,'balanced_accuracy_present_classes':1.}
    result={k:parent[k] for k in ('name','arm','seed','phase','report_sha256','report_bytes')}
    result.update(epoch=epoch,kind=kind,development=d,process_wall_seconds=wall,process_cpu_seconds=None)
    return result


class HistoricalTests(unittest.TestCase):
    def test_preserves_later_cumulative_clock_not_early_C1_sample(self):
        parent,child=fit(),fit('C1')
        row=observation(child,2,0)
        row.update(phase_process_wall_seconds=20.,cumulative_process_wall_seconds=120.00001,
            cumulative_cpu_lower_bound_seconds=55.,cumulative_cpu_upper_bound_seconds=None,
            cumulative_full_process_cpu_seconds=None,phase_full_process_cpu_seconds=5.)
        points,_=phase_points(child,[row],parent,events=11)
        self.assertEqual(points[0]['wall_seconds'],120.00001)
        self.assertIsNone(points[0]['CPU_upper_seconds'])
        for key,value in [('cumulative_process_wall_seconds',119.9),('phase_process_wall_seconds',31.)]:
            wrong=copy.deepcopy(row); wrong[key]=value
            with self.subTest(key=key), self.assertRaises(ValueError):
                phase_points(child,[wrong],parent,events=11)

    def test_wrapper_cost_is_not_assigned_to_earlier_quality_event(self):
        parent,child=fit(),fit('C1')
        points=[{'phase':'original','epoch':0,'kind':'development_before','wall_seconds':1.,'quality':0.,'CPU_lower_seconds':None},
                {'phase':'original','epoch':1,'kind':'complete_epoch','wall_seconds':50.,'quality':.2,'CPU_lower_seconds':50.},
                {'phase':'C1','epoch':2,'kind':'complete_epoch','wall_seconds':120.,'quality':.4,'CPU_lower_seconds':55.}]
        row=historical_candidate(parent,child,points)
        self.assertEqual(row['full_chain_charged_wall_seconds'],135.)
        self.assertEqual(row['first_observed_target_crossing']['wall_seconds'],120.)
        self.assertFalse(row['independent_adequate'])
        self.assertFalse(row['diagnostic_passed'])
        self.assertIsNone(row['cumulative_full_CPU_seconds'])

    def test_missing_wrapper_and_CPU_are_not_zero_filled(self):
        parent,child=fit(),fit('C1')
        child['outer'].pop('attempt_wrapper_wall_seconds')
        points=[{'phase':'original','epoch':1,'kind':'complete_epoch','wall_seconds':50.,'quality':.2,'CPU_lower_seconds':None},
                {'phase':'C1','epoch':2,'kind':'complete_epoch','wall_seconds':120.,'quality':.4,'CPU_lower_seconds':None}]
        row=historical_candidate(parent,child,points)
        self.assertIsNone(row['full_chain_charged_wall_seconds'])
        self.assertEqual(row['known_chain_wall_lower_bound_seconds'],130.)
        parent['all_report_clock_fields']={}
        self.assertIsNone(parent_cost(parent,[points[0]])['cumulative_CPU_lower_bound_seconds'])


if __name__=='__main__':
    unittest.main()
