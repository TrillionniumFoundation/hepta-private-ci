"""Measured release-time FIFO, frozen CPU proxy, independent audit, no CLIP."""
from __future__ import annotations
from pathlib import Path
import json
import shutil
import tempfile
import unittest

import torch
from experiments.shared_stem_cell import execution as e
from experiments.shared_stem_cell import public_video as public
from experiments.shared_stem_cell import test_public_video as video_fixture
from experiments.shared_stem_cell import video_cpu_proxy as cpu
from experiments.shared_stem_cell import video_cpu_tune as tune
from experiments.shared_stem_cell import video_cpu_queue as queue
from experiments.shared_stem_cell import audit_video_cpu_queue as auditor

class ArrivalAwareVideoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)
        cls.fixture=video_fixture.PublicVideoTests()
        cls.fixture.setUp()
        cls.root=cls.fixture.root/'queue-source'
        cls.root.mkdir()
        f=cls.fixture
        data,cohort=public.stage(cls.root,_read=f.read,_decode=f.decode,
            inventory=f.inventory,revision=f.revision,readme_blob=f.readme_blob)
        e.write_once(cls.root/'manifest.json',{
            'schema':'hepta.shared-stem-media.v1','classes':2,'steps':80,'seed':20261014,
            'temporal':False,'video_profile':'paired_temporal_order_v1',
            'dataset':data,'cohort':cohort,
            'models':{'clip':{'path':'vision/model','revision':'b'*40,'files':{}}}})
        cls.output=cls.fixture.root/'queued-study'
        cls.workloads=(('paired',8,2,0),('paired',8,8,4_000_000))
        cls.report=queue.run(cls.root,cls.output,workloads=cls.workloads,
                             calibration_rounds=2,evaluation_rounds=2,warmups=0)
        cls.audited=auditor.audit(cls.root,cls.output)
    @classmethod
    def tearDownClass(cls):cls.fixture.tearDown()

    def altered(self,fn):
        output=Path(tempfile.mkdtemp(dir=self.fixture.root))
        self.addCleanup(lambda: shutil.rmtree(output,ignore_errors=True))
        files=('protocol.json','training.json','calibration.json','selection.json',
               'holdout-predictions.json','evaluation.json','report.json')
        payload={p:e.decode((self.output/p).read_bytes()) for p in files}
        fn(payload)
        for name in files:
            (output/name).write_bytes(e.canonical(payload[name]))
        report=payload['report.json']
        for key,file in (('protocol_sha256','protocol.json'),('calibration_sha256','calibration.json'),
                         ('selection_sha256','selection.json'),('evaluation_sha256','evaluation.json'),
                         ('holdout_predictions_sha256','holdout-predictions.json')):
            report[key]=e.sha((output/file).read_bytes())
        (output/'report.json').write_bytes(e.canonical(report))
        return output

    def test_real_io_conv_and_gru_heldout_without_clipping_or_fake_tower(self):
        self.assertEqual(len(self.report['summaries']),2)
        self.assertEqual(set(self.audited['audited_workloads']),{'paired:8:2:0','paired:8:8:4000000'})
        self.assertFalse(self.audited['real_pretrained_clip'])
        self.assertFalse(self.audited['independently_attested_latency'])
        ev=e.decode((self.output/'evaluation.json').read_bytes())['measurements']
        for arms in ev.values():
            for policy in queue.POLICIES:
                runs=arms[queue.policy_key(policy)]
                self.assertEqual(len(runs),2)
                for run in runs:
                    self.assertGreater(run['conv_forward_ns'],0)
                    self.assertGreater(run['preprocess_ns'],0)
                    self.assertEqual(sum(run['conv_batch_sizes']),run['unique_frames'])
                    self.assertEqual(run['physical_forward_calls'],len(run['conv_batch_sizes']))

    def test_source_fold_isolation_and_presealed_choice(self):
        selection=e.decode((self.output/'selection.json').read_bytes())
        source_sets=[set(selection['source_groups'][k]) for k in ('train','calibration','holdout')]
        self.assertEqual([len(s) for s in source_sets],[6,2,2])
        self.assertEqual(len(set.union(*source_sets)),10)
        self.assertFalse(selection['holdout_labels_used'])
        seal=e.sha((self.output/'selection.json').read_bytes())
        predictions=e.decode((self.output/'holdout-predictions.json').read_bytes())
        self.assertEqual(predictions['selection_sha256'],seal)
        self.assertTrue(predictions['before_holdout_label_score'])

    def test_actual_request_release_and_response_are_causal(self):
        records=e.decode((self.output/'evaluation.json').read_bytes())['measurements']
        for workload,by_policy in records.items():
            gap=int(workload.rsplit(':',1)[-1]);depth=int(workload.split(':')[2])
            for arm in by_policy.values():
                for run in arm:
                    self.assertEqual(run['arrival_offsets_ns'],[i*gap for i in range(8)])
                    self.assertEqual(run['requested_frame_rows'],8*depth)
                    self.assertEqual(run['latency_p95_ns'],queue.percentile([r['response_latency_ns']
                                                                             for r in run['records']],95))
                    for record in run['records']:
                        self.assertGreaterEqual(record['dispatch_offset_ns'],record['scheduled_arrival_offset_ns'])
                        self.assertEqual(record['response_latency_ns'],record['completion_offset_ns']-
                                         record['scheduled_arrival_offset_ns'])

    def test_shared_cache_is_not_reset_per_group(self):
        ev=e.decode((self.output/'evaluation.json').read_bytes())['measurements']
        for workload,arms in ev.items():
            runs=arms['1:0']
            for run in runs:
                # This is a physical cache for the whole FIFO run, not one per dispatch group.
                self.assertEqual(len(run['groups']),8)
                for g in run['groups']:
                    self.assertEqual(len(g['case_ids']),1)
                if '8:4000000' in workload:
                    self.assertGreater(run['requested_frame_rows'],run['unique_frames'])

    def test_all_policy_arms_are_physically_run_and_charged(self):
        cal=e.decode((self.output/'calibration.json').read_bytes())['measurements']
        hold=e.decode((self.output/'evaluation.json').read_bytes())['measurements']
        expected=len(self.workloads)*len(queue.POLICIES)*4
        self.assertEqual(self.report['all_arm_execution_count_including_warmups'],expected)
        total=sum(x['physical_forward_calls'] for fold in (cal,hold)
                  for arms in fold.values() for runs in arms.values() for x in runs)
        self.assertEqual(self.report['all_measured_arm_calls'],total)
        self.assertGreater(self.report['all_arm_calls_plus_training_and_warmups'],total)

    def test_predicted_classes_are_equal_across_schedule_capacity(self):
        evals=e.decode((self.output/'evaluation.json').read_bytes())['measurements']
        for arms in evals.values():
            baseline=arms['1:0'][0]['records']
            for candidates in arms.values():
                for item in candidates:
                    self.assertEqual([r['prediction'] for r in item['records']],
                                     [r['prediction'] for r in baseline])
                    for a,b in zip(baseline,item['records']):
                        self.assertLess(max(abs(x-y) for x,y in zip(a['probabilities'],b['probabilities'])),2e-5)

    def test_calibration_preserves_first_response_guard_and_falls_back(self):
        arr={'1:0':[{'first_response_ns':5,'latency_p95_ns':100,'end_to_end_wall_ns':100}]*2}
        for policy in queue.POLICIES[1:]:
            arr[queue.policy_key(policy)]=[{'first_response_ns':10,'latency_p95_ns':40,
                                           'end_to_end_wall_ns':50}]*2
        self.assertEqual(queue.choose(arr)['policy_key'],'1:0')
        for item in arr['4:8000000']:
            item['first_response_ns']=6
        self.assertEqual(queue.choose(arr)['policy_key'],'4:8000000')
        self.assertEqual(auditor.choice(arr)[0],queue.choose(arr)['policy_key'])

    def test_reject_policy_outside_fixed_grid_before_work(self):
        _,folds,_,_=tune.split_sources(self.root,e.decode((self.root/'manifest.json').read_bytes()))
        model=cpu.FrozenPixelConv()
        reader,_=cpu.train_reader(self.root,e.decode((self.root/'manifest.json').read_bytes()),
                                  model, [c for pool in folds['train']['paired'] for c in [pool]])
        with self.assertRaises(e.InputError):
            queue.execute_once(self.root,model,reader,folds['holdout']['paired'][:8],2,0,(8,0))
        with self.assertRaises(e.InputError):
            queue.execute_once(self.root,model,reader,folds['holdout']['paired'][:8],2,999,(1,0))

    def test_independent_auditor_rejects_forged_group_physical_calls_with_recomputed_hash(self):
        def tamper(doc):
            sample=next(iter(doc['evaluation.json']['measurements'].values()))['1:0'][0]
            sample['groups'][0]['frame_events'][0]['physical_forward_calls']=0
        with self.assertRaisesRegex(ValueError,'physical'):
            auditor.audit(self.root,self.altered(tamper))

    def test_independent_auditor_rejects_forged_p95_with_recomputed_hash(self):
        def tamper(doc):
            sample=next(iter(doc['evaluation.json']['measurements'].values()))['1:0'][0]
            sample['latency_p95_ns']+=2_000_000
        with self.assertRaisesRegex(ValueError,'quantile'):
            auditor.audit(self.root,self.altered(tamper))

    def test_independent_auditor_rejects_forged_early_dispatch(self):
        def tamper(doc):
            sample=doc['evaluation.json']['measurements']['paired:8:8:4000000']['4:8000000'][0]
            sample['groups'][0]['dispatch_offset_ns']=0
        with self.assertRaises(ValueError):
            auditor.audit(self.root,self.altered(tamper))

    def test_independent_auditor_rejects_forged_selected_policy_with_recomputed_hash(self):
        def tamper(doc):
            choice=next(iter(doc['selection.json']['by_workload'].values()))
            choice['policy_key']='4:8000000' if choice['policy_key']!='4:8000000' else '1:0'
        with self.assertRaises(ValueError):
            auditor.audit(self.root,self.altered(tamper))

    def test_independent_auditor_rejects_forged_holdout_speed_claim(self):
        def tamper(doc):
            summ=next(iter(doc['report.json']['summaries'].values()))
            summ['selected_vs_scalar_full_wall_ratio']+=0.5
        with self.assertRaisesRegex(ValueError,'latency summary'):
            auditor.audit(self.root,self.altered(tamper))

    def test_independent_auditor_rejects_forged_training_cost(self):
        def tamper(doc):doc['report.json']['all_measured_arm_calls']+=1
        with self.assertRaises(ValueError):auditor.audit(self.root,self.altered(tamper))

    def test_reject_larger_unknown_grid_even_if_report_claims_accuracy(self):
        fake={queue.policy_key(p):[{'first_response_ns':10,'latency_p95_ns':20,
                                      'end_to_end_wall_ns':100}]*2 for p in queue.POLICIES}
        fake['8:0']=fake['1:0']
        with self.assertRaises(e.InputError):queue.choose(fake)

if __name__=='__main__':unittest.main()
