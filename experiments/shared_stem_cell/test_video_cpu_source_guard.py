"""Source-wise conditional fallback; exact queue integration and independent audit."""
from __future__ import annotations

from pathlib import Path
import shutil
import tempfile
import unittest

import torch

from experiments.shared_stem_cell import execution as e
from experiments.shared_stem_cell import public_video as public
from experiments.shared_stem_cell import test_public_video as fixture
from experiments.shared_stem_cell import video_cpu_queue as queue
from experiments.shared_stem_cell import video_cpu_source_guard as guard
from experiments.shared_stem_cell import audit_video_cpu_source_guard as audit


class GuardSelectionTests(unittest.TestCase):
    def records(self, count=8, diverse=True):
        return [{'case_id':f'cell-{i}', 'source_id': ('a' if i<count//2 else 'b')*64 if diverse else 'a'*64,
                 'response_latency_ns':100} for i in range(count)]

    def grid(self, *, sources=True, bad_round=False, bad_source=False, improve=True):
        names=[queue.policy_key(x) for x in queue.POLICIES]
        cases=self.records(diverse=sources)
        ids=[x['case_id'] for x in cases]
        calibration={}
        for name in names:
            calibration[name]=[]
            for iteration in range(3):
                latency=100 if name=='1:0' else (130 if bad_round and iteration==2 else 80 if improve else 102)
                records=[{**x,'response_latency_ns':latency} for x in cases]
                if bad_source and name!='1:0':
                    for record in records[4:]:record['response_latency_ns']=110
                calibration[name].append({'iteration':iteration,'case_ids':ids,
                    'arrival_offsets_ns':list(range(len(ids))),
                    'records':records,'policy_key':name,'depth':2,'gap_ns':0,
                    'latency_p95_ns':latency,'first_response_ns':70 if name!='1:0' else 80,
                    'whole_run_wall_ns':900 if name!='1:0' else 1000})
        return calibration

    def test_all_rounds_and_sources_pass_to_qualify(self):
        v=guard.choose(self.grid())
        self.assertEqual(v['selected_policy_key'],'2:0')
        self.assertEqual(len(v['qualified']),4)
        self.assertEqual(v,audit.derive(self.grid()))

    def test_single_source_requires_scalar_even_for_large_savings(self):
        x=guard.choose(self.grid(sources=False))
        self.assertEqual(x['selected_policy_key'],'1:0')
        self.assertEqual(x['comparison']['2:0']['reason'],'insufficient_source_groups')

    def test_one_bad_paired_round_blocks_optimistic_median(self):
        x=guard.choose(self.grid(bad_round=True))
        self.assertEqual(x['selected_policy_key'],'1:0')
        self.assertEqual(len(x['comparison']['2:0']['paired_rounds']),3)
        self.assertFalse(x['comparison']['2:0']['paired_rounds'][-1]['passes'])

    def test_per_source_tail_regression_blocks_even_if_whole_metric_improves(self):
        x=guard.choose(self.grid(bad_source=True))
        self.assertEqual(x['selected_policy_key'],'1:0')
        self.assertFalse(x['comparison']['2:0']['paired_rounds'][0]['passes'])

    def test_no_improvement_keeps_scalar(self):
        x=guard.choose(self.grid(improve=False))
        self.assertEqual(x['selected_policy_key'],'1:0')
        self.assertEqual(x,audit.derive(self.grid(improve=False)))

    def test_missing_calibration_arm_rejected(self):
        vals=self.grid();del vals['4:0']
        with self.assertRaises(e.InputError):guard.choose(vals)

    def test_matched_arrivals_and_source_ids_required(self):
        vals=self.grid();vals['4:0'][1]['arrival_offsets_ns'][0]=-1
        with self.assertRaises(e.InputError):guard.choose(vals)
        vals=self.grid();vals['2:0'][0]['records'][0]['source_id']='c'*64
        with self.assertRaises(e.InputError):guard.choose(vals)

    def test_selection_has_explicit_no_population_guarantee(self):
        x=guard.choose(self.grid())
        self.assertTrue(x['empirical_guard_not_population_certificate'])
        self.assertTrue(x['same_queue_sources_not_independent'])
        self.assertTrue(x['uses_previously_exposed_public_source_family'])
        self.assertFalse(x['production_accepted'])


class GuardProtocolIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)
        cls.factory=fixture.PublicVideoTests()
        cls.factory.setUp()
        cls.root=cls.factory.root/'robust-source'
        cls.root.mkdir()
        f=cls.factory
        data,cohort=public.stage(cls.root,_read=f.read,_decode=f.decode,
           inventory=f.inventory,revision=f.revision,readme_blob=f.readme_blob)
        e.write_once(cls.root/'manifest.json',{'schema':'hepta.shared-stem-media.v1',
            'classes':2,'steps':80,'seed':20261014,'temporal':False,
            'video_profile':'paired_temporal_order_v1',
            'dataset':data,'cohort':cohort,
            'models':{'clip':{'path':'vision/model','revision':'b'*40,'files':{}}}})
        cls.output=f.root/'robust-execution'
        cls.workloads=(('paired',8,2,0),('paired',16,8,12_000_000))
        cls.report=queue.run(cls.root,cls.output,workloads=cls.workloads,
                             calibration_rounds=2,evaluation_rounds=2,warmups=0)
        cls.result=audit.audit(cls.root,cls.output)

    @classmethod
    def tearDownClass(cls):cls.factory.tearDown()

    def mutate(self,fn):
        target=Path(tempfile.mkdtemp(dir=self.factory.root))
        self.addCleanup(lambda:shutil.rmtree(target,ignore_errors=True))
        files=['protocol.json','training.json','calibration.json','selection.json',
            'holdout-predictions.json','evaluation.json','report.json']
        docs={file:e.decode((self.output/file).read_bytes()) for file in files}
        fn(docs)
        # Honest regenerated file hashes, not only a broken checksum.
        select=e.canonical(docs['selection.json']);docs['report.json']['selection_sha256']=e.sha(select)
        docs['holdout-predictions.json']['selection_sha256']=e.sha(select)
        docs['evaluation.json']['selection_sha256']=e.sha(select)
        for file in files:
            if file=='report.json':continue
            (target/file).write_bytes(e.canonical(docs[file]))
        for k,file in [('protocol_sha256','protocol.json'),('calibration_sha256','calibration.json'),
                       ('selection_sha256','selection.json'),('evaluation_sha256','evaluation.json'),
                       ('holdout_predictions_sha256','holdout-predictions.json')]:
            docs['report.json'][k]=e.sha((target/file).read_bytes())
        docs['evaluation.json']['holdout_prediction_sha256']=docs['report.json']['holdout_predictions_sha256']
        (target/'evaluation.json').write_bytes(e.canonical(docs['evaluation.json']))
        docs['report.json']['evaluation_sha256']=e.sha((target/'evaluation.json').read_bytes())
        (target/'report.json').write_bytes(e.canonical(docs['report.json']))
        return target

    def test_end_to_end_calibration_is_frozen_before_holdout_and_audited(self):
        self.assertEqual(len(self.result['by_workload']),2)
        choice=e.decode((self.output/'selection.json').read_bytes())
        cal=e.decode((self.output/'calibration.json').read_bytes())
        for name in choice['by_workload']:
            self.assertEqual(choice['source_guard_by_workload'][name],
                             guard.choose(cal['measurements'][name]))
        self.assertEqual(self.result['by_workload']['paired:8:2:0']['conservative_source_winner'],'1:0')
        self.assertFalse(self.result['new_unseen_source_data'])

    def test_no_additional_encoder_work_for_retrospective_guard(self):
        self.assertTrue(self.report['all_reference_policies_physically_executed_and_charged'])
        self.assertEqual(self.report['all_arm_execution_count_including_warmups'],
                         len(self.workloads)*len(queue.POLICIES)*4)
        self.assertEqual(self.report['all_measured_arm_calls'],
            sum(run['physical_forward_calls'] for arms in
                e.decode((self.output/'calibration.json').read_bytes())['measurements'].values()
                for runs in arms.values() for run in runs)+
            sum(run['physical_forward_calls'] for arms in
                e.decode((self.output/'evaluation.json').read_bytes())['measurements'].values()
                for runs in arms.values() for run in runs))

    def test_auditor_catches_forged_guard_even_after_rebinding_hashes(self):
        def bad(docs):
            key=next(iter(docs['selection.json']['source_guard_by_workload']))
            docs['selection.json']['source_guard_by_workload'][key]['selected_policy_key']='4:8000000'
        with self.assertRaisesRegex(ValueError,'source-guard selection'):
            audit.audit(self.root,self.mutate(bad))

    def test_auditor_catches_forged_selected_heldout_benefit(self):
        def bad(docs):
            k=next(iter(docs['report.json']['summaries']))
            docs['report.json']['summaries'][k]['source_guard_selected_vs_scalar_p95_ratio']=1.9
        with self.assertRaisesRegex(ValueError,'source guard heldout'):
            audit.audit(self.root,self.mutate(bad))

    def test_old_strategy_remains_preserved_as_competing_baseline(self):
        choice=e.decode((self.output/'selection.json').read_bytes())
        for name in choice['by_workload']:
            self.assertIn('policy_key',choice['by_workload'][name])
            self.assertIn('selected_policy_key',choice['source_guard_by_workload'][name])
            self.assertIn('selected_vs_scalar_p95_ratio',self.report['summaries'][name])

if __name__=='__main__':unittest.main()
