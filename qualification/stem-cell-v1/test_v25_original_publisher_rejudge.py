"""Independent synthetic failure tests; original-public source tests have NO fallback."""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import math
import tempfile
import unittest

import v25_original_publisher_rejudge as w
import v24_multimodal_causal_bounds as v24


def vectors():
    # SYNTHETIC labels and synthetic probabilities; never called original model evidence.
    sources = []
    for i in range(192):
        split = 'train' if i<96 else 'validation' if i<128 else 'test'
        sources.append({'id':f'{i+1:064x}', 'group':f'{2000+i:064x}',
                        'image':f'{4000+i:064x}', 'split':split,
                        'question':f'artificial question {i}', 'hint':'',
                        'choices':['a','b','c','d'], 'scope':'public-scienceqa-e3-research'})
    held=sources[128:]
    labels=[{'id':x['id'],'group':x['group'],'split':'test','label':(i%4)}
            for i,x in enumerate(held)]
    pred=[]
    for i,row in enumerate(held):
        text=[.251,.250,.250,.249] if i<21 else [.7,.1,.1,.1]
        img = [.24,.28,.24,.24] if i<19 else list(text)
        gate = [.1,.1,.7,.1] if i%5==0 else list(text)
        arms={a:list(text) for a in v24.ARMS}
        arms['bridge_image_only']=img
        arms['train_gate']=gate
        arms['bridge_equal_fusion']=[(x+y)/2 for x,y in zip(text,img)]
        arms['unaligned_equal_fusion']=[.1,.1,.1,.7] if i%7==0 else list(text)
        arms['rotated_equal_fusion']=[.1,.7,.1,.1] if i%6==0 else list(text)
        pred.append({'id':row['id'],'group':row['group'],'split':'test',
                     'source_input_sha256':w.sha(w.canonical(row)),'arms':arms})
    return sources,labels,{'predictions':pred}


def independent_report(pred, labels):
    truth={x['id']:x['label'] for x in labels}
    review={'arms':{},'paired_vs_text_only':{}}
    by_id=sorted(pred['predictions'],key=lambda x:x['id'])
    outcomes={}
    for arm in v24.ARMS:
        okay=[];brier=[];nll=[]
        for row in by_id:
            y=truth[row['id']];p=row['arms'][arm]
            top=max(range(4),key=lambda j:(p[j],-j))
            okay.append(int(y==top))
            brier.append(sum((p[k]-(k==y))**2 for k in range(4))/4)
            nll.append(-math.log(max(p[y],1e-12)))
        outcomes[arm]=okay
        review['arms'][arm]={'correct':sum(okay),'brier_4class_mean':math.fsum(brier)/64,
                             'nll':math.fsum(nll)/64}
    base=outcomes['text_only']
    for arm in v24.PAIR_ARMS:
        cur=outcomes[arm]
        rescue=sum(a==0 and b==1 for a,b in zip(base,cur))
        harm=sum(a==1 and b==0 for a,b in zip(base,cur))
        review['paired_vs_text_only'][arm]={'rescued_errors_vs_text':rescue,'new_errors_vs_text':harm,
                                            'mcnemar_unadjusted_exact_p':v24.exact_p(rescue,harm)}
    return review


class SyntheticContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sources,cls.labels,cls.pred=vectors()
        cls.review=independent_report(cls.pred,cls.labels)

    def test_original_spec_still_pinned(self):
        self.assertEqual(w.PUB_REVISION,'b9984af01798586705cee1fbdfa80a6dcbef04f1')
        self.assertEqual(w.STAGER_SHA,'3ca8f55ed6b7143729258e4a1e53693614460950')
        self.assertEqual(w.CONTRACT_SHA,'bd6d95ff957c3855b71a8778d7c13f61ff4d6a7a')

    def test_synthetic_math_only(self):
        ids=w.source_identity(self.sources,self.labels,sealed_pred=self.pred)
        result=w.evaluate_original(self.pred,self.review,ids)
        self.assertEqual(result['precommitted_v24_label_blind_route']['conditional_image_calls_planned'],21)
        self.assertEqual(result['precommitted_v24_label_blind_route']['changed_top1_vs_text'],19)
        self.assertIn('historical_correct',result['precommitted_v24_label_blind_route'])
        self.assertIsNone(result['precommitted_v24_label_blind_route']['actual_conditional_encoder_forward_count'])

    def fails(self, *, source=None,labels=None,pred=None,review=None):
        with self.assertRaises((w.Invalid,ValueError,TypeError,KeyError)):
            s=source if source is not None else copy.deepcopy(self.sources)
            l=labels if labels is not None else copy.deepcopy(self.labels)
            p=pred if pred is not None else copy.deepcopy(self.pred)
            r=review if review is not None else copy.deepcopy(self.review)
            targets=w.source_identity(s,l,sealed_pred=p)
            w.evaluate_original(p,r,targets)

    def test_complete_synthetic_stage_transport_only(self):
        # Mechanism fixture, NOT original publisher data; restoring the immutable
        # source lock guarantees the CLI remains original-only afterwards.
        with tempfile.TemporaryDirectory() as d:
            base=Path(d)
            src=b''.join(w.canonical(row) for row in self.sources)
            lab=b''.join(w.canonical(row) for row in self.labels)
            sha_src=w.sha(src);sha_lab=w.sha(lab)
            (base/'source.jsonl').write_bytes(src)
            (base/'labels.jsonl').write_bytes(lab)
            fake={'source_sha256':sha_src,'private_test_labels_sha256':sha_lab,
                  'fit_labels_sha256':'a'*64,'cohort_sha256':'c'*64}
            stage={'dataset':w.PUB,'dataset_revision':w.PUB_REVISION,
                   'source_sha256':sha_src,'private_test_labels_sha256':sha_lab,
                   'fit_labels_sha256':'a'*64,'cohort_sha256':'c'*64,
                   'raw_image_count':192,'externally_independent_labels':False,
                   'production_accepted':False}
            (base/'stage.json').write_bytes(w.canonical(stage))
            original=v24.SOURCE_SHA256
            v24.SOURCE_SHA256=sha_src
            try:
                review=copy.deepcopy(self.review)
                review['holdout_targets_sha256']=sha_lab
                result=w.verify_staged(fake,base/'source.jsonl',base/'labels.jsonl',
                                       base/'stage.json',self.pred,review)
                self.assertEqual(result['precommitted_v24_label_blind_route']['conditional_image_calls_planned'],21)
                (base/'labels.jsonl').write_bytes(lab+b'{}\n')
                with self.assertRaises(w.Invalid):
                    w.verify_staged(fake,base/'source.jsonl',base/'labels.jsonl',
                                    base/'stage.json',self.pred,review)
            finally:
                v24.SOURCE_SHA256=original
        self.assertEqual(v24.SOURCE_SHA256,original)

    def test_missing_source(self):
        self.fails(source=copy.deepcopy(self.sources[:-1]))

    def test_extra_source(self):
        sources=copy.deepcopy(self.sources)
        sources.append(copy.deepcopy(sources[-1]));self.fails(source=sources)

    def test_duplicate_source_id(self):
        sources=copy.deepcopy(self.sources)
        sources[1]['id']=sources[0]['id'];self.fails(source=sources)

    def test_unexpected_training_label(self):
        labels=copy.deepcopy(self.labels)
        labels[0]['split']='train';self.fails(labels=labels)

    def test_boolean_label(self):
        labels=copy.deepcopy(self.labels)
        labels[0]['label']=True;self.fails(labels=labels)

    def test_missing_original_labels(self):
        self.fails(labels=copy.deepcopy(self.labels[:-1]))

    def test_wrong_group_binding(self):
        labels=copy.deepcopy(self.labels)
        labels[0]['group']='f'*64;self.fails(labels=labels)

    def test_source_text_swap_without_resealing(self):
        s=copy.deepcopy(self.sources);s[-1]['question']='different source';self.fails(source=s)

    def test_source_choice_swap_without_resealing(self):
        s=copy.deepcopy(self.sources);s[-1]['choices'][0]='false';self.fails(source=s)

    def test_bad_scope(self):
        s=copy.deepcopy(self.sources);s[0]['scope']='production';self.fails(source=s)

    def test_added_target_to_source(self):
        s=copy.deepcopy(self.sources);s[-1]['answer']=2;self.fails(source=s)

    def test_prediction_arm_swap(self):
        p=copy.deepcopy(self.pred)
        p['predictions'][0]['arms']['bridge_image_only']=p['predictions'][30]['arms']['bridge_image_only']
        self.fails(pred=p)

    def test_review_forged_correct(self):
        r=copy.deepcopy(self.review);r['arms']['train_gate']['correct']+=1;self.fails(review=r)

    def test_review_forged_score(self):
        r=copy.deepcopy(self.review);r['arms']['train_gate']['nll']+=0.005;self.fails(review=r)

    def test_review_forged_pair(self):
        r=copy.deepcopy(self.review);r['paired_vs_text_only']['train_gate']['new_errors_vs_text']+=1
        self.fails(review=r)

    def test_mismatched_labels_change_outcome(self):
        l=copy.deepcopy(self.labels);l[0]['label']=(l[0]['label']+1)%4;self.fails(labels=l)

    def test_extra_prediction(self):
        p=copy.deepcopy(self.pred);p['predictions'].append(copy.deepcopy(p['predictions'][-1]));self.fails(pred=p)

    def test_duplicate_prediction(self):
        p=copy.deepcopy(self.pred);p['predictions'][1]['id']=p['predictions'][0]['id'];self.fails(pred=p)

    def test_bad_probs(self):
        p=copy.deepcopy(self.pred);p['predictions'][0]['arms']['train_gate'][0]=float('nan');self.fails(pred=p)

    def test_duplicate_json_key_rejected(self):
        with self.assertRaises(w.Invalid):w.parse_strict(b'{"id":"a","id":"b"}\n')

    def test_noncanonical_jsonl_rejected(self):
        with self.assertRaises(w.Invalid):w.strict_lines(b'{"id": "a"}\n',1,1)

    def test_missing_newline_rejected(self):
        with self.assertRaises(w.Invalid):w.strict_lines(b'{"id":"a"}',1,1)

    def test_canonical_round_trip(self):
        b=w.canonical({'b':True,'a':[1,2]})
        self.assertEqual(w.strict_lines(b,1,1),[{'a':[1,2],'b':True}])

    def test_nonfinite_json_rejected(self):
        with self.assertRaises(w.Invalid):w.parse_strict(b'{"v":NaN}')

    def test_pinned_file_symlink_and_rewrite(self):
        with tempfile.TemporaryDirectory() as d:
            base=Path(d);p=base/'original.jsonl';p.write_bytes(b'abc\n')
            self.assertEqual(w.pinned_file(p,w.sha(b'abc\n'),100),b'abc\n')
            with self.assertRaises(w.Invalid):w.pinned_file(p,'0'*64,100)
            alias=base/'alias';alias.symlink_to(p)
            with self.assertRaises(w.Invalid):w.pinned_file(alias,w.sha(b'abc\n'),100)



class OriginalArchive(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        value=os.environ.get('HEPTA_V25_ORIGINAL_ZIP')
        if value is None:
            raise RuntimeError('genuine E3 original ZIP required; never skip/replace with synthetic')
        cls.archive=Path(value)

    def test_no_positive_without_pub_files(self):
        with tempfile.TemporaryDirectory() as d:
            archive=self.archive
            self.assertTrue(archive.exists())
            out=Path(d)/'negative.json'
            result=w.run(archive,out)
            self.assertEqual(result['decision'],'HOLD_ORIGINAL_PUBLIC_SOURCE_AND_LABEL_BYTES_NOT_REOPENED')
            self.assertIsNone(result['v24_conditional_route_historical_accuracy'])
            self.assertFalse(result['original_publisher_labels_independently_rescored'])
            with self.assertRaises(FileExistsError):w.run(archive,out)
            self.assertEqual(json.loads(out.read_text()),result)

    def test_all_or_none_source_material(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(w.Invalid):w.run(self.archive,Path(d)/'must_not_exist.json',
                                                       Path(d)/'source.jsonl',None,None)

    def test_fail_on_real_archive_wrong_bytes(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'fake.zip'; p.write_bytes(b'fabricated original model archive')
            with self.assertRaises(v24.Invalid):w.run(p,Path(d)/'missing.json')

    def test_real_original_archive_is_historical_not_future(self):
        p=self.archive
        pred,rev,seals=v24.verify_archive(p)
        self.assertEqual(rev['original_heldout_cases'],64)
        self.assertFalse(rev['external_ground_truth_independent_owner'])
        self.assertFalse(rev['visual_necessity_ground_truth_adjudicated'])
        self.assertEqual(seals['dataset_revision'],w.PUB_REVISION)

class OriginalPublisherPhysical(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        required=('HEPTA_V25_ORIGINAL_SOURCES','HEPTA_V25_ORIGINAL_LABELS','HEPTA_V25_ORIGINAL_STAGE_SEALS')
        if any(k not in os.environ for k in required):
            raise RuntimeError('all original publisher ScienceQA inputs are required; never skip or substitute fixtures')
        cls.args=[Path(os.environ[k]) for k in required]

    def test_genuine_original_label_byte_parity_and_all_arms(self):
        pred,review,seals=v24.verify_archive(Path(os.environ['HEPTA_V25_ORIGINAL_ZIP']))
        d=w.verify_staged(seals,*self.args,pred,review)
        self.assertEqual(d['all_original_arms']['text_only']['original_historical_correct'],17)
        self.assertEqual(d['all_original_arms']['train_gate']['original_historical_correct'],24)
        self.assertEqual(d['all_original_arms']['bridge_image_only']['original_historical_correct'],21)
        self.assertEqual(d['precommitted_v24_label_blind_route']['conditional_image_calls_planned'],21)
        self.assertIn(d['precommitted_v24_label_blind_route']['historical_correct'],range(5,34))

    def test_actual_original_material_tamper_fails(self):
        pred,review,seals=v24.verify_archive(Path(os.environ['HEPTA_V25_ORIGINAL_ZIP']))
        with tempfile.TemporaryDirectory() as d:
            raw=self.args[1].read_bytes()
            corrupt=Path(d)/'bad-labels.jsonl';corrupt.write_bytes(raw[:-3]+b'---')
            with self.assertRaises(w.Invalid):w.verify_staged(seals,self.args[0],corrupt,self.args[2],pred,review)

if __name__=='__main__':
    unittest.main()
