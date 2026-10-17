"""Hermetic and original-material-optional G5 provenance, learning and review tests."""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

import g5_original_evidence as producer
import g5_independent_review as auditor
import g5_full_corpus_cheap as cheap
import g5_material_custody as custody


def public_fixture():
    roots=[]
    for root in producer.TRAIN_ROOTS+producer.HELD_ROOTS:
        dialog=[{'dia_id':f'D1:{i}','speaker':'Test',
                 'text':f'Public evidence number {i} discusses the original event and date.'}
                for i in range(1,261)]
        qa=[{'question':f'Which date appears for event {i} from {root}?',
             'answer':f'private human answer {i}',
             'evidence':[f'D1:{i+1}'], 'category':1} for i in range(32)]
        roots.append({'sample_id':root,'conversation':{'session_1':dialog},'qa':qa})
    return json.dumps(roots,sort_keys=True,separators=(',',':')).encode()


def fixture_packets():
    blob=public_fixture()
    sha=hashlib.sha256(blob).hexdigest()
    with patch.dict(producer.CHECKSUMS,{'locomo.json':sha}):
        pub=producer.source_packet(blob)
        producer.verify_packet(pub)
    # Avoid test fake root masquerading as genuinely original publisher bytes.
    with patch.object(auditor,'LOCOMO_SHA',sha):
        p=copy.deepcopy(pub)
        gold={}
        for r in p['roots']:
            if r['split']=='HELD':
                for q in r['questions']:
                    i=int(q['id'][1:]);gold[(r['root'],q['id'])]=[f'D1:{i+1}']
        predictions=[]
        for r in p['roots']:
            if r['split']=='TRAIN':continue
            ordered=sorted(z['id'] for z in r['docs'])
            for q in r['questions']:
                predictions.append({'root':r['root'],'qid':q['id'],
                                    'question_sha':q['text_sha'],
                                    'ranks':{arm:ordered.copy() for arm in auditor.ARMS}})
        fitting={'initial_sha':'a'*64,'trained_sha':'b'*64,'steps':100,
                 'train_supported':40,'parameters':6144,'training_elapsed_wall_seconds':1.0,
                 'training_loss_final':0.5}
        raw={'schema':'hepta.hdsi.g5.real-minilm-evidence-study.v1',
             'source_digest':p['digest'],'model_sha':auditor.MODEL_SHA,
             'source_sha':sha,'training':fitting,'shuffled_supervision_training':dict(fitting),
             'roots':{r['root']:{'actual_completed_forward_sequences':280,
                                'logical_fanout_borrows':280,'unique_feature_keys':280,
                                'root_split':r['split']} for r in p['roots']},
             'actual_full_encoder_forward_sequences':2800,
             'encoder_token_positions':30000,'actual_batched_model_calls':180,
             'original_hidden_dimension':384,'held_predictions':predictions,
             'cost':{'elapsed_wall_seconds':40.0,'elapsed_cpu_seconds':38.0,
                     'head_fit_wall_seconds':3.0,'maxrss_bytes_unattested':100000000,
                     'energy_joules':None,'target_host_p99_ms':None},
             'original_model_forward':True,'independent_human_answer_scored':False,
             'future_generalization_verified':False,'ndu_incremental_utility_verified':False,
             'source_family_holdout_verified':True,'production_authorized':False,
             'disposition':'HOLD_NO_GO'}
        run=producer._sealed(raw,'hepta.hdsi.g5.physical-prelabel')
    return blob,p,run


class G5SourceOnlyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.blob,cls.packet,cls.record=fixture_packets()

    def test_held_source_is_label_free(self):
        self.assertEqual(sum(z['split']=='HELD' for z in self.packet['roots']),4)
        self.assertTrue(all(set(q)=={'id','text','text_sha'}
                            for r in self.packet['roots'] if r['split']=='HELD'
                            for q in r['questions']))
        self.assertTrue(all('train_support' in q
                            for r in self.packet['roots'] if r['split']=='TRAIN'
                            for q in r['questions']))

    def test_source_validation_rejects_held_gold_even_when_resealed(self):
        bad=copy.deepcopy(self.packet)
        q=next(z for z in bad['roots'] if z['split']=='HELD')['questions'][0]
        q['train_support']=['D1:1']
        bad=producer._sealed({k:v for k,v in bad.items() if k!='digest'},
                             'hepta.hdsi.g5.original-source')
        with patch.dict(producer.CHECKSUMS,{'locomo.json':hashlib.sha256(self.blob).hexdigest()}):
            with self.assertRaises(producer.Denied):producer.verify_packet(bad)

    def test_original_source_sha_required(self):
        with self.assertRaises(producer.Denied):producer.read_publisher(self.blob)

    def test_fake_question_label_or_source_drift_rejected(self):
        bad=copy.deepcopy(self.packet)
        bad['roots'][-1]['questions'][0]['text']='unfrozen label-bearing question'
        with patch.dict(producer.CHECKSUMS,{'locomo.json':hashlib.sha256(self.blob).hexdigest()}):
            with self.assertRaises(producer.Denied):producer.verify_packet(bad)

    def test_bm25_prefers_exact_nontrivial_term(self):
        r=producer.bm25('mountain science evidence',['science ocean','mountain science evidence','unrelated cars'])
        self.assertGreater(r[1],r[0]);self.assertGreater(r[1],r[2])

    @unittest.skipUnless(importlib.util.find_spec("torch") is not None, "requires local real PyTorch tensor runtime")
    def test_rank8_trains_real_synthetic_tensor_without_oracle(self):
        import torch
        torch.set_num_threads(1)
        r=self.packet['roots']
        f={z['root']:(torch.randn(24,384),torch.randn(256,384)) for z in r}
        p,receipt=producer.train_rank8(r,f,shuffled=False)
        self.assertEqual(receipt['steps'],100)
        self.assertEqual(receipt['parameters'],6144)
        self.assertNotEqual(receipt['initial_sha'],receipt['trained_sha'])
        self.assertTrue(all(x.isfinite().all().item() for x in p.values()))

    @unittest.skipUnless(importlib.util.find_spec("torch") is not None, "requires local real PyTorch tensor runtime")
    def test_shuffled_supervision_keeps_exact_budget(self):
        import torch
        torch.set_num_threads(1)
        t=torch.Generator().manual_seed(1)
        f={z['root']:(torch.randn(24,384,generator=t),torch.randn(256,384,generator=t))
           for z in self.packet['roots']}
        _,one=producer.train_rank8(self.packet['roots'],f,shuffled=False)
        _,other=producer.train_rank8(self.packet['roots'],f,shuffled=True)
        self.assertEqual(one['initial_sha'],other['initial_sha'])
        self.assertEqual(one['train_supported'],other['train_supported'])
        self.assertEqual(one['steps'],other['steps'])

    def _review(self,run):
        with patch.object(auditor,'LOCOMO_SHA',hashlib.sha256(self.blob).hexdigest()):
            return auditor.count_original(self.blob,self.packet,run)

    def test_independent_review_reconstructs_all_publisher_roots(self):
        x=self._review(self.record)
        self.assertEqual(x['historical_original_publisher_questions'],96)
        self.assertEqual(x['metrics']['bm25']['denominator'],96)
        self.assertFalse(x['production_authorized'])

    def test_duplicate_document_rank_rejected_even_with_new_sha(self):
        bad=copy.deepcopy(self.record)
        ranks=bad['held_predictions'][0]['ranks']['bm25']
        ranks[0]=ranks[1]
        bad=producer._sealed({k:v for k,v in bad.items() if k!='digest'},
                             'hepta.hdsi.g5.physical-prelabel')
        with self.assertRaises(ValueError):self._review(bad)

    def test_missing_test_prediction_rejected(self):
        bad=copy.deepcopy(self.record)
        bad['held_predictions'].pop()
        bad=producer._sealed({k:v for k,v in bad.items() if k!='digest'},
                             'hepta.hdsi.g5.physical-prelabel')
        with self.assertRaises(ValueError):self._review(bad)

    def test_authority_claim_rejected_even_when_resealed(self):
        bad=copy.deepcopy(self.record)
        bad['production_authorized']=True
        bad=producer._sealed({k:v for k,v in bad.items() if k!='digest'},
                             'hepta.hdsi.g5.physical-prelabel')
        with self.assertRaises(ValueError):self._review(bad)

    def test_model_forward_counter_must_conserve(self):
        bad=copy.deepcopy(self.record)
        bad['actual_full_encoder_forward_sequences']-=1
        bad=producer._sealed({k:v for k,v in bad.items() if k!='digest'},
                             'hepta.hdsi.g5.physical-prelabel')
        with self.assertRaises(ValueError):self._review(bad)

    def test_private_test_label_added_to_source_is_rejected_by_independent_scorer(self):
        bad=copy.deepcopy(self.packet)
        bad['roots'][-1]['questions'][0]['answer']='human label leak'
        bad=producer._sealed({k:v for k,v in bad.items() if k!='digest'},
                             'hepta.hdsi.g5.original-source')
        with patch.object(auditor,'LOCOMO_SHA',hashlib.sha256(self.blob).hexdigest()):
            with self.assertRaises(ValueError):auditor.count_original(self.blob,bad,self.record)

    def test_raw_train_label_mutation_is_detected_independently(self):
        bad=copy.deepcopy(self.packet)
        bad['roots'][0]['questions'][0]['train_support']=['D9:999']
        bad=producer._sealed({k:v for k,v in bad.items() if k!='digest'},
                             'hepta.hdsi.g5.original-source')
        with patch.object(auditor,'LOCOMO_SHA',hashlib.sha256(self.blob).hexdigest()):
            with self.assertRaises(ValueError):auditor.count_original(self.blob,bad,self.record)

    def test_full_corpus_cheap_protocol_fake_source(self):
        with patch.object(cheap,'LOCOMO_SHA',hashlib.sha256(self.blob).hexdigest()):
            record=cheap.evaluate_full_pub(self.blob)
        self.assertEqual(record['metrics']['denominator'],96)
        self.assertTrue(record['applies_to_different_doc_budget'])
        self.assertEqual(record['metrics']['original_transcript_documents'],1040)

    def test_full_corpus_does_not_accept_unpinned_bytes(self):
        with self.assertRaises(ValueError):cheap.evaluate_full_pub(self.blob)

    def test_original_archive_download_does_not_run_without_authentication(self):
        with patch.dict(os.environ,{'GH_TOKEN':''}):
            with self.assertRaises(ValueError):
                custody.download_original(Path('/unlikely/g5-archive'))

    def test_historical_material_extraction_rejects_fake_original_archive(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);f=root/'bad.zip';f.write_bytes(b'not the SHA pinned original')
            with self.assertRaises(ValueError):
                custody.extract_pinned(f,root/'stage',mode='reviewer')
            self.assertFalse((root/'stage').exists())

    def test_model_ingress_rejects_raw_held_gold(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory)/'locomo.json').write_bytes(self.blob)
            with patch.dict(producer.CHECKSUMS,{'locomo.json':hashlib.sha256(self.blob).hexdigest()}):
                with self.assertRaisesRegex(producer.Denied,'raw original QA'):
                    producer.produce(Path(directory),self.packet)

    def test_no_forged_future_window(self):
        bad=copy.deepcopy(self.record)
        bad['future_generalization_verified']=True
        bad=producer._sealed({k:v for k,v in bad.items() if k!='digest'},
                             'hepta.hdsi.g5.physical-prelabel')
        with self.assertRaises(ValueError):self._review(bad)


class G5GenuineOriginalOptionalTests(unittest.TestCase):
    def test_batch_vs_scalar_full_six_layers(self):
        original=os.environ.get('HDSI_G5_ORIGINAL_ROOT')
        if original is None:
            self.skipTest('actual external historical original model material not supplied')
        from real_minilm_reference import RealMiniLM
        from g5_batched_encoder import BatchedMiniLM
        import torch
        torch.set_num_threads(1)
        corpus=Path(original)
        scalar=RealMiniLM(corpus)
        batched=BatchedMiniLM(corpus,16)
        real=producer.source_packet((corpus/'locomo.json').read_bytes())
        inp=[(r['text'].encode(),'text') for r in real['roots'][0]['docs'][:16]]
        b=batched.encode_batch(inp)
        s=[scalar.encode(x.decode()) for x,_ in inp]
        self.assertEqual(batched.calls,16)
        self.assertEqual(batched.actual_batches,1)
        self.assertTrue(all(max(abs(u-v) for u,v in zip(one,two)) < 1e-5
                            for one,two in zip(b,s)))
        self.assertTrue(all(len(x)==384 for x in b))


if __name__ == '__main__':unittest.main()
