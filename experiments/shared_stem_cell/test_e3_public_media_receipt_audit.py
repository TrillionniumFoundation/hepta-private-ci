"""Deterministic synthetic ZIP fault injection: never treated as public model efficacy."""
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile, ZIP_DEFLATED

import e3_public_media_receipt_audit as a


def canonical(v):
    return json.dumps(v,sort_keys=True,separators=(',',':'),allow_nan=False).encode()


def fixture():
    files={}
    for j,(root,parts) in enumerate(a.ROOTS.items()):
        rows=[]
        for partition,count in parts.items():
            for i in range(count):
                n=len(rows)
                rows.append({'case_id':f'{j}-{partition}-{i}','split':partition,'scope':'test',
                             'group':hashlib.sha256(f'g{j},{partition},{i}'.encode()).hexdigest(),
                             'label':i%4,'inputs':{'image':{'sha256':hashlib.sha256(f'image{j},{partition},{i}'.encode()).hexdigest()}}})
        files[f'{root}/dataset.jsonl']=b'\n'.join(canonical(row) for row in rows)+b'\n'
        test=[r for r in rows if r['split']=='holdout']
        ids=[row['case_id'] for row in test]
        prob=[[.97 if k==row['label'] else .01 for k in range(4)] for row in test]
        if 'choice' in root:
            named={key:prob for key in ('text_only:final','text_only:frozen','visual_prior:final','visual_prior:frozen','visual_zero:final','visual_zero:frozen')}
            pred={'case_ids':ids,'probabilities':named,'selected_key':'text_only:frozen'}
            report={'scores':{k:{z:v for z,v in a.scores(matrix,[row['label'] for row in test]).items() if z!='correct_by_case'} for k,matrix in named.items()},
                    'selected_key':'text_only:frozen','heldout_option_permutation_passed':True}
        else:
            named={key:prob for key in ('image','image+text','text')}
            n=len(test)
            same={'correct':n,'gains':0,'losses':0,'ties':n,'accuracy_delta':0.}
            op={key:prob for key in a.REQUIRED_OPERATORS}
            meta={'as_observed':{'rows':list(range(n))}}
            for modality in ('image','text'):
                meta['mask:'+modality]={'rows':[None]*n}
                meta['rotate:'+modality]={'rows':list(range(1,n))+[0]}
            pred={'case_ids':ids,'predictions':named,'frozen_predictions':named,
                  'modality_interventions':{'predictions':op,'causal_semantics_established':False,
                                            'source_rows':meta,'partitions':['holdout']*n}}
            report={'modality_intervention_scores':{'holdout':{'paired':{k:same for k in a.REQUIRED_OPERATORS}}}}
        path=f'{root}/'+('choice-execution' if 'choice' in root else 'media-execution')
        pred_bytes=canonical(pred);files[path+'/predictions.json']=pred_bytes
        report['prediction_sha256']=a.sha(pred_bytes)
        files[path+'/report.json']=canonical(report)
    return files


def serialize(files):
    out=io.BytesIO()
    with ZipFile(out,'w',compression=ZIP_DEFLATED) as z:
        for name,bytes_ in files.items():z.writestr(name,bytes_)
    return out.getvalue()


class E3AuditTests(unittest.TestCase):
    def run_case(self,change=None,pass_expected=False):
        files=fixture()
        if change:change(files)
        blob=serialize(files)
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'pinned.zip';path.write_bytes(blob)
            with patch.object(a,'ARCHIVE_SHA256',a.sha(blob)):
                if pass_expected:
                    result=a.review(path)
                    self.assertFalse(result['production_promotion_permitted'])
                    self.assertFalse(result['granite_dinov2_or_gemma_multimodal_comparison_performed'])
                    return result
                with self.assertRaises((a.Invalid, ValueError,KeyError)):
                    a.review(path)
    def change(self,files,name,fn):
        obj=a.load(files[name]);fn(obj);files[name]=canonical(obj)
    def test_synthetic_happy_path(self):
        x=self.run_case(pass_expected=True)
        self.assertEqual({r['n_holdout'] for r in x['results'].values()},{32,64})
    def test_source_pinned_sha(self):
        files=fixture();blob=serialize(files)
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'wrong.zip';p.write_bytes(blob)
            with self.assertRaises(a.Invalid):a.review(p)
    def test_wrong_labels_not_hidden_by_report(self):
        def tamper(files):
            path='hepta-choice-media/dataset.jsonl'
            arr=[a.load(x) for x in files[path].splitlines()]
            for r in arr:
                if r['split']=='holdout':r['label']=(r['label']+1)%4;break
            files[path]=b'\n'.join(canonical(x) for x in arr)+b'\n'
        self.run_case(tamper)
    def test_wrong_holdout_ids(self):
        self.run_case(lambda files:self.change(files,'hepta-choice-media/choice-execution/predictions.json',lambda o:o['case_ids'].reverse()))
    def test_fake_published_score(self):
        self.run_case(lambda files:self.change(files,'hepta-choice-media/choice-execution/report.json',lambda o:o['scores']['visual_prior:final'].update(correct=0)))
    def test_forged_prediction_checksum(self):
        self.run_case(lambda files:self.change(files,'hepta-choice-media/choice-execution/report.json',lambda o:o.update(prediction_sha256='f'*64)))
    def test_duplicate_cross_cohort_group(self):
        def tamper(files):
            path='hepta-choice-media/dataset.jsonl'
            arr=[a.load(x) for x in files[path].splitlines()]
            other=[a.load(x) for x in files['hepta-public-media/dataset.jsonl'].splitlines()]
            arr[0]['group']=other[0]['group']
            files[path]=b'\n'.join(canonical(x) for x in arr)+b'\n'
        self.run_case(tamper)
    def test_fake_mask_source(self):
        self.run_case(lambda files:self.change(files,'hepta-public-media/media-execution/predictions.json',lambda o:o['modality_interventions']['source_rows']['mask:image']['rows'].insert(0,0)))
    def test_fake_rotation_source(self):
        self.run_case(lambda files:self.change(files,'hepta-public-media/media-execution/predictions.json',lambda o:o['modality_interventions']['source_rows']['rotate:text'].update(rows=list(range(32)))))
    def test_nonfinite_probabilities(self):
        self.run_case(lambda files:self.change(files,'hepta-public-media/media-execution/predictions.json',lambda o:o['predictions']['image'][0].__setitem__(0,-.1)))
    def test_missing_case(self):
        def tamper(files):
            path='hepta-public-media/dataset.jsonl';files[path]=b'\n'.join(files[path].splitlines()[:-1])+b'\n'
        self.run_case(tamper)
    def test_unsupported_causal_semantics(self):
        self.run_case(lambda files:self.change(files,'hepta-public-media/media-execution/predictions.json',lambda o:o['modality_interventions'].update(causal_semantics_established=True)))
    def test_option_selection_mismatch(self):
        self.run_case(lambda files:self.change(files,'hepta-choice-media/choice-execution/report.json',lambda o:o.update(selected_key='visual_prior:final')))
    def test_zip_duplicate_filename(self):
        files=fixture();blob=serialize(files)
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'dupe.zip';p.write_bytes(blob)
            with ZipFile(p,'a') as z:z.writestr(next(iter(files)),b'bad')
            with patch.object(a,'ARCHIVE_SHA256',a.sha(p.read_bytes())):
                with self.assertRaises(a.Invalid):a.review(p)
    def test_duplicate_json_key(self):
        def tamper(files):
            path='hepta-choice-media/choice-execution/report.json'
            files[path]=b'{"scores":{},"scores":{},"prediction_sha256":"'+b'a'*64+b'"}'
        self.run_case(tamper)

if __name__=='__main__':
    unittest.main()
