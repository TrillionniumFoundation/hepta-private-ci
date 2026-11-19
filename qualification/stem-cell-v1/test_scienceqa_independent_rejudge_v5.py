"""V5 independent ScienceQA source/rejudgment contract tests; fixtures are synthetic."""
import copy
import io
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import scienceqa_independent_rejudge_v5 as v5


def rgb_bytes(rgb):
    from PIL import Image
    p=Image.new('RGB',(2,2),rgb)
    stream=io.BytesIO();p.save(stream,format='PNG')
    return stream.getvalue()


def fixture_source(full=False):
    sizes=dict(v5.SOURCE_SPLITS) if full else {'train':2,'validation':1,'test':2}
    raw={}; idx=0
    for split,n in sizes.items():
        raw[split]=[]
        for j in range(n):
            raw[split].append({
                'question':f'Which action is {split} {j}?', 'hint':'',
                'choices':['up','down','left','right'],
                'image':{'bytes':rgb_bytes((idx % 256, (idx*3) % 256, (idx*7) % 256))},
            })
            idx+=1
    selected=v5.select_original(raw,sizes)
    def answer(split, i):
        return (i+list(sizes).index(split))%4
    seal=v5.sealed_source(selected,answer,sizes=sizes)
    return raw,selected,seal


def fixture_archive(seal):
    held={x['id']:x['label'] for x in seal['held']}
    results=[]
    for case in seal['cases']:
        if case['split']!='test':continue
        probs={}
        for a in v5.ARMS:
            if a == 'train_gate':
                pred=(held[case['id']]+1)%4
            else:
                pred=held[case['id']]
            arr=[.1,.1,.1,.1];arr[pred]=.7
            probs[a]=arr
        results.append({'id':case['id'],'group':case['group'],'split':'test',
                        'source_input_sha256':v5.sha(v5.canonical(case)), 'arms':probs})
    prediction={'arms':list(v5.ARMS),'held_labels_visible_to_inference':False,
                'production_accepted':False,'predictions':results}
    summarized={}
    for name in v5.ARMS:
        correct=0; brier=[]; nll=[]
        for r in results:
            p=r['arms'][name];y=held[r['id']]
            correct+=int(max(range(4),key=lambda k:p[k])==y)
            brier.append(sum((p[k]-int(k==y))**2 for k in range(4))/4)
            nll.append(-math.log(p[y]))
        summarized[name]={'correct':correct,'accuracy':correct/len(results),
                          'nll':math.fsum(nll)/len(results),
                          'brier_4class_mean':math.fsum(brier)/len(results)}
    paired={}
    baseline={r['id']:max(range(4),key=lambda k:r['arms']['text_only'][k])==held[r['id']]
              for r in results}
    for name in v5.ARMS:
        if name in ('text_only','image_masked'):continue
        new={r['id']:max(range(4),key=lambda k:r['arms'][name][k])==held[r['id']]
             for r in results}
        harm=sum(baseline[i] and not new[i] for i in baseline)
        rescue=sum(not baseline[i] and new[i] for i in baseline)
        # Test oracle uses direct binomial enumeration, not the source function.
        n=harm+rescue
        p=min(1.,2*sum(math.comb(n,j) for j in range(min(harm,rescue)+1))/(2**n)) if n else 1.
        paired[name]={'new_errors_vs_text':harm,'rescued_errors_vs_text':rescue,
                      'mcnemar_unadjusted_exact_p':p}
    archive={
        'source-seals.json':v5.canonical({'source_sha256':seal['source_sha256'],
                        'fit_labels_sha256':seal['fit_sha256'],
                        'private_test_labels_sha256':seal['held_sha256']}),
        'sealed-source-bound-predictions.json':v5.canonical(prediction),
        'independent-descriptive-review.json':v5.canonical({'authority':'DENY_ALL',
                        'arms':summarized,'paired_vs_text_only':paired}),
        'physical-completed-or-absent.json':v5.canonical({
                        'completed_original_pretrained_stage_and_scoring':True,
                        'authority':'DENY_ALL'}),
    }
    return archive


class V5Tests(unittest.TestCase):
    def test_closed_archive_sha_and_original_inventory(self):
        import zipfile
        with tempfile.TemporaryDirectory() as d:
            zip_path=Path(d)/'frozen.zip'
            synthetic={k:(k+'\n').encode() for k in v5.MEMBERS if k!='SHA256SUMS'}
            sums=''.join(f'{v5.sha(blob)}  {name}\n' for name,blob in sorted(synthetic.items()))
            synthetic['SHA256SUMS']=sums.encode()
            with zipfile.ZipFile(zip_path,'w') as z:
                for name,blob in sorted(synthetic.items()):z.writestr(name,blob)
            with patch.object(v5,'ARCHIVE_SHA',v5.sha(zip_path.read_bytes())):
                self.assertEqual(set(v5.read_archive(zip_path)),v5.MEMBERS)
                with zipfile.ZipFile(zip_path,'a') as z:z.writestr('forged.txt','bad')
                with patch.object(v5,'ARCHIVE_SHA',v5.sha(zip_path.read_bytes())):
                    with self.assertRaises(v5.V5Error):v5.read_archive(zip_path)

    def test_source_first_images_and_label_roster(self):
        _,selected,seal=fixture_source()
        self.assertEqual([len(selected[s]) for s in v5.SOURCE_SPLITS],[2,1,2])
        self.assertEqual([len(seal[key]) for key in ('fit','held')],[3,2])
        self.assertEqual(seal['images'],5)
        self.assertEqual(len(seal['source_sha256']),64)

    def test_rejudges_fixture_label_source_independently(self):
        _,_,seal=fixture_source(full=True)
        archive=fixture_archive(seal)
        with patch.object(v5,'SOURCE_SHA',seal['source_sha256']), \
             patch.object(v5,'FIT_SHA',seal['fit_sha256']), \
             patch.object(v5,'HELD_SHA',seal['held_sha256']), \
             patch.object(v5,'PRED_SHA',v5.sha(archive['sealed-source-bound-predictions.json'])):
            fake=copy.deepcopy(seal)
            r=v5.score_original(archive,fake)
            self.assertEqual(r['arms']['text_only']['correct'],64)
            self.assertEqual(r['arms']['train_gate']['correct'],0)
            self.assertEqual(r['paired']['train_gate']['new_errors'],64)
            self.assertTrue(r['heldout_labels_independently_reconstructed'])
            self.assertFalse(r['independent_human_visual_necessity_adjudication'])
            self.assertFalse(r['production_authorized'])

    def test_fake_gold_or_prediction_drift_fails_closed(self):
        _,_,seal=fixture_source(full=True)
        archive=fixture_archive(seal)
        with patch.object(v5,'SOURCE_SHA',seal['source_sha256']), \
             patch.object(v5,'FIT_SHA',seal['fit_sha256']), \
             patch.object(v5,'HELD_SHA',seal['held_sha256']), \
             patch.object(v5,'PRED_SHA',v5.sha(archive['sealed-source-bound-predictions.json'])):
            fake=copy.deepcopy(seal)
            tampered=copy.deepcopy(fake)
            tampered['held'][0]['label']=(tampered['held'][0]['label']+1)%4
            with self.assertRaises(v5.V5Error):v5.score_original(archive,tampered)
            bad=copy.deepcopy(archive)
            p=v5.parse(bad['sealed-source-bound-predictions.json'])
            p['predictions'][0]['arms']['train_gate'][0]=.9
            bad['sealed-source-bound-predictions.json']=v5.canonical(p)
            with self.assertRaises(v5.V5Error):v5.score_original(bad,fake)

    def test_duplicate_nonfinite_and_incomplete_source_are_denied(self):
        with self.assertRaises(v5.V5Error):v5.parse(b'{"x":1,"x":2}')
        with self.assertRaises(v5.V5Error):v5.parse(b'{"x":1e999}')
        public,_,_=fixture_source()
        public['test']=public['test'][:1]
        with self.assertRaises(v5.V5Error):
            v5.select_original(public,{'train':2,'validation':1,'test':2})
        self.assertEqual(v5.exact_mcnemar(7,14),.18924713134765625)

    def test_archive_outer_sha_required_even_when_zip_wellformed(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'fake.zip'
            import zipfile
            with zipfile.ZipFile(path,'w') as z:z.writestr('source-seals.json','{}')
            with self.assertRaises(v5.V5Error):v5.read_archive(path)

if __name__=='__main__':unittest.main()
