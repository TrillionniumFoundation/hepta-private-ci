"""Synthetic rejection/roundtrip fixtures. NO model checkpoint is executed."""
import copy
import hashlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from real_model_artifact_replay import (replay, _metrics, AuditError,
    REVISION_GEMMA, REVISION_LAYA)


def sha(v):
    return hashlib.sha256(str(v).encode()).hexdigest()


def dumps(x):
    return json.dumps(x,sort_keys=True,separators=(',',':'),ensure_ascii=True).encode()


def fixture():
    cases=[]
    for i in range(128):
        source=sha(i)
        cases.append(dict(case_id=f"c{i:04d}",group_id=source,
                          source_digest=source,joint_input_digest=sha("input"+str(i)),
                          label=i%2,split="new_holdout"))
    panel=dict(case_count=128,cases=cases,chronological_future_claim=False,
               same_public_source_family=True,production_promotion="DENY_ALL",
               selection_domain_sha256=sha('source'))
    arms=[]
    def make(name):
        if name.startswith('gemma'):
            rev=REVISION_GEMMA
            if name.endswith('scaled_1024'): scale=1024;steps=40
            else: scale=1;steps=0 if name.endswith('frozen_head') else 40
            meta=dict(revision=rev,predetermined_logit_multiplier=scale,head_training_steps=steps)
        else:
            meta=dict(revision=REVISION_LAYA)
        rows=[]
        for i,c in enumerate(cases):
            p=(.495 if i%2==0 else .505) if name=='gemma2_frozen_head' else (.499 if i%2==0 else .501)
            if name=='laya421_frozen':p=.2 if i%2==0 else .8
            if name.endswith('scaled_1024'):
                import math
                z=1024*math.log(p/(1-p))
                p=1/(1+math.exp(-z)) if z>=0 else math.exp(z)/(1+math.exp(z))
            rows.append(dict(case_id=c['case_id'],split='new_holdout',
                             joint_input_digest=c['joint_input_digest'],source_digest=c['source_digest'],
                             prob_sports=p,measured_serving_micros=200))
        return dict(arm_id=name,production_promotion='DENY_ALL',
                    cross_sectional_new_source_not_temporal_future=True,
                    foundation_pretraining_overlap_ruled_out=False,
                    matched_full_lifecycle_cost=False,
                    raw_source_and_model_origin_independently_attested=False,
                    panel_digest=sha('panel'),metadata=meta,rows=rows)
    for n in ['gemma2_frozen_head','gemma2_trained_head','gemma2_trained_head_scaled_1024','laya421_frozen']:
        arms.append(make(n))
    metrics={}
    for a in arms:
        s=_metrics([r['prob_sports'] for r in a['rows']],[c['label'] for c in cases])
        metrics[a['arm_id']]={'cases':128,'accuracy':s['accuracy'],'brier':s['brier'],
                              'descriptive_ece_8bin':s['ece8_descriptive']}
    review=dict(replication_panel_digest=sha('panel'),metrics=metrics,
                source_and_report_digests={a['arm_id']:hashlib.sha256(dumps(a)).hexdigest() for a in arms})
    rawlog='''User time (seconds): {cpu}\nElapsed (wall clock) time (h:mm:ss or m:ss): {wall}\nMaximum resident set size (kbytes): {rss}\nExit status: 0\n'''
    log1=rawlog.format(cpu='4.0',wall='5.00',rss='1000')
    log2=rawlog.format(cpu='6.0',wall='8.00',rss='2000')
    res=dict(production_promotion='DENY_ALL',model_lifetime_cost_equalization_proven=False,
             measurements={'gemma':dict(model_process_exit_status=0,wall_seconds_including_model_load=5.0,
                                        process_peak_rss_bytes=1024000,process_user_cpu_seconds=4.0),
                           'laya':dict(model_process_exit_status=0,wall_seconds_including_model_load=8.0,
                                      process_peak_rss_bytes=2048000,process_user_cpu_seconds=6.0)})
    return {'stem-agnews-new-source-panel.json':panel,
            'stem-gemma-fresh-arms.json':arms[:3],
            'stem-laya-fresh-arm.json':arms[3],
            'stem-new-source-independent-review.json':review,
            'stem-process-resources.json':res,
            'stem-gemma-process-time.txt':log1,
            'stem-laya-process-time.txt':log2}


def save(folder,data):
    p=Path(folder)/'fixture.zip'
    with zipfile.ZipFile(p,'w',zipfile.ZIP_DEFLATED) as z:
        for name,content in data.items():
            z.writestr(name,content if type(content) is str else dumps(content))
    return p,hashlib.sha256(p.read_bytes()).hexdigest()

class ArtifactReplayTests(unittest.TestCase):
    def test_synthetic_positive_cannot_be_promoted(self):
        with tempfile.TemporaryDirectory() as t:
            p,h=save(t,fixture())
            r=replay(p,expected_archive_sha256=h,synthetic_fixture=True)
            self.assertEqual(r['source_cases'],128)
            self.assertEqual(r['raw_row_coverage'],512)
            self.assertIsNone(r['artifact_id'])
            self.assertFalse(r['p0_accepted'])
            self.assertFalse(r['independent_model_or_source_authentication'])
    def reject(self,alter):
        d=fixture();alter(d)
        with tempfile.TemporaryDirectory() as t:
            p,h=save(t,d)
            with self.assertRaises((AuditError,KeyError)):
                replay(p,expected_archive_sha256=h,synthetic_fixture=True)
    def test_unchanged_fixture_must_not_claim_real_artifact(self):
        with tempfile.TemporaryDirectory() as t:
            p,h=save(t,fixture())
            with self.assertRaises(AuditError):replay(p,expected_archive_sha256=h)
    def test_altered_zip_sha(self):
        with tempfile.TemporaryDirectory() as t:
            p,h=save(t,fixture())
            with self.assertRaises(AuditError):replay(p,expected_archive_sha256='a'*64,synthetic_fixture=True)
    def test_missing_arm(self):self.reject(lambda d:d['stem-gemma-fresh-arms.json'].pop())
    def test_missing_case(self):self.reject(lambda d:d['stem-agnews-new-source-panel.json']['cases'].pop())
    def test_duplicate_case(self):self.reject(lambda d:d['stem-agnews-new-source-panel.json']['cases'].__setitem__(0,copy.deepcopy(d['stem-agnews-new-source-panel.json']['cases'][1])))
    def test_bad_source_identity(self):self.reject(lambda d:d['stem-laya-fresh-arm.json']['rows'][0].update(source_digest=sha('poison')))
    def test_bad_probability(self):self.reject(lambda d:d['stem-laya-fresh-arm.json']['rows'][0].update(prob_sports=2))
    def test_modified_model_row(self):self.reject(lambda d:d['stem-gemma-fresh-arms.json'][1]['rows'][0].update(prob_sports=.999))
    def test_fake_selected_model(self):self.reject(lambda d:d['stem-gemma-fresh-arms.json'][1].update(production_promotion='SELECTED'))
    def test_false_future_claim(self):self.reject(lambda d:d['stem-agnews-new-source-panel.json'].update(chronological_future_claim=True))
    def test_fake_external_signature(self):self.reject(lambda d:d['stem-laya-fresh-arm.json'].update(raw_source_and_model_origin_independently_attested=True))
    def test_inconsistent_resource_log(self):self.reject(lambda d:d['stem-process-resources.json']['measurements']['laya'].update(process_user_cpu_seconds=0))
    def test_wrong_model_revision(self):self.reject(lambda d:d['stem-gemma-fresh-arms.json'][0]['metadata'].update(revision=REVISION_LAYA))
    def test_illegal_logit_rescale(self):self.reject(lambda d:d['stem-gemma-fresh-arms.json'][2]['rows'][0].update(prob_sports=.8))
    def test_zero_training_claim(self):self.reject(lambda d:d['stem-gemma-fresh-arms.json'][1]['metadata'].update(head_training_steps=0))
    def test_ece_uses_predicted_class_confidence(self):
        values=_metrics([.10,.81],[0,1]);self.assertEqual(values['correct'],2)
        self.assertAlmostEqual(values['ece8_descriptive'],.145)

if __name__=='__main__':unittest.main()
