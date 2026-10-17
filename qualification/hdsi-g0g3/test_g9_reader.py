"""G9 adversarial source contracts + optional true original 135M Reader regression."""
from __future__ import annotations
import copy,hashlib,json,os,subprocess,sys,tempfile,unittest
from pathlib import Path
from g9_reader_panel import ARMS,ROOTS,validate,from_original,digest
from g9_native_reader import ByteBPE,NativeSmolLM135,verify_material
from g9_independent_review import norm,literal_contains,f1,original_bm25,review
from g9_material_custody import extract

HERE=Path(__file__).resolve().parent
ROOT=HERE.parent/'original'
PANEL=HERE.parent/'g9-label-free-4arm.json'
RUNS=[HERE.parent/f'g9-raw-{r}.json' for r in ROOTS]


def synthetic_source_fixture():
    """Hermetic, explicitly NON-original fake source for protocol/authority testing."""
    from g9_reader_panel import SCHEMA
    cases=[]
    for root in ROOTS:
        for j in range(4):
            q='Where did the fictitious person go in this synthetic test? '+str(j)
            d={'id':'D1:1','text':'Only a synthetic document: bookstore.',
               'text_sha':hashlib.sha256(b'Only a synthetic document: bookstore.').hexdigest()}
            cases.append({'id':root+'/q'+str(j),'root':root,'question':q,
                          'question_sha':hashlib.sha256(q.encode()).hexdigest(),
                          'arms':{'none':[],'bm25':[d], 'oracle':[d], 'lesion':[]}})
    p={'schema':SCHEMA,'original_sha':'79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4',
       'reader_weight_sha':'5af571cbf074e6d21a03528d2330792e532ca608f24ac70a143f6b369968ab8c',
       'source_roster_digest':'0'*64,'original_held_roots':list(ROOTS),
       'four_questions_per_root':4,'case_source':'original_g8_question_roster_first4_per_held_root',
       'arms':list(ARMS),'oracle_support_uses_publisher_held_evidence_ids':True,
       'historically_public_not_future':True,'original_answers_in_packet':False,
       'reader_tokenizer_parity_verified':False,'research_only':True,
       'production_authorized':False,'disposition':'HOLD_NO_GO','cases':cases}
    p['digest']=digest(p)
    return p


class G9SourceTests(unittest.TestCase):
    def setUp(self):
        p=os.environ.get('HDSI_G9_PANEL')
        self.packet=json.loads(Path(p).read_bytes()) if p else synthetic_source_fixture()

    def test_four_fixed_arms_are_unique(self):
        self.assertEqual(len(ARMS),4);self.assertEqual(len(ROOTS),4)
        self.assertEqual(len(set(ARMS)),4)

    def test_synthetic_fixture_contract_not_original_efficacy(self):
        fixture=synthetic_source_fixture()
        validate(fixture)
        self.assertEqual(len(fixture['cases']),16)
        self.assertFalse(fixture['production_authorized'])

    def test_exact_question_label_omission(self):
        validate(self.packet)
        self.assertEqual(len(self.packet['cases']),16)
        self.assertFalse(self.packet['original_answers_in_packet'])
        for c in self.packet['cases']:
            self.assertTrue({'answer','category','gold','adversarial_answer'}.isdisjoint(c))

    def test_changed_original_packet_digest_rejected(self):
        p=copy.deepcopy(self.packet);p['cases'][0]['question']+=' malicious addition'
        with self.assertRaises(ValueError):validate(p)

    def test_resigned_gold_field_rejected(self):
        p=copy.deepcopy(self.packet);p['cases'][0]['answer']='secret'
        p['digest']=digest({k:v for k,v in p.items() if k!='digest'})
        with self.assertRaises(ValueError):validate(p)

    def test_resigned_wrong_lesion_rejected(self):
        p=copy.deepcopy(self.packet);p['cases'][0]['arms']['lesion']=p['cases'][0]['arms']['oracle']
        p['digest']=digest({k:v for k,v in p.items() if k!='digest'})
        with self.assertRaises(ValueError):validate(p)

    def test_resigned_fake_future_claim_rejected(self):
        p=copy.deepcopy(self.packet);p['historically_public_not_future']=False
        p['digest']=digest({k:v for k,v in p.items() if k!='digest'})
        with self.assertRaises(ValueError):validate(p)

    def test_literal_word_boundary(self):
        self.assertFalse(literal_contains('notebook','no'))
        self.assertTrue(literal_contains('The answer is Ned.','Ned'))
        self.assertFalse(literal_contains('Tuesday morning','May'))

    def test_exact_not_confused_with_contains(self):
        from g9_independent_review import exact
        self.assertFalse(exact('The answer is Ned.','Ned'))
        self.assertTrue(exact('Ned!','Ned'))

    def test_overlap_f1_bounded(self):
        self.assertEqual(f1('Ned','Ned'),1.)
        self.assertEqual(f1('wrong','right'),0.)
        self.assertTrue(0.<f1('The answer is Ned','Ned')<1.)

    def test_independent_bm25_is_stable(self):
        docs=[{'id':'D1:1','text':'purple dog adopted'},{'id':'D1:2','text':'coffee'}]
        self.assertEqual(original_bm25(docs,'adopted dog'),[0,1])

    def test_material_path_rejects_unpinned(self):
        with tempfile.TemporaryDirectory() as t:
            d=Path(t)
            for f in ['model.safetensors','tokenizer.json','config.json']:(d/f).write_bytes(b'wrong')
            with self.assertRaises(ValueError):verify_material(d)

    def test_untrusted_tar_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'archive.zip';p.write_bytes(b'not original')
            with self.assertRaises(ValueError):extract(p,Path(t)/'model','model')

    def test_review_mutation_rejected_on_original(self):
        if not ROOT.joinpath('locomo.json').exists() or not all(p.exists() for p in RUNS):
            self.skipTest('full original source/real pretrained predictions absent')
        public=json.loads(PANEL.read_bytes());receipts=[json.loads(f.read_bytes()) for f in RUNS]
        expected=review((ROOT/'locomo.json').read_bytes(),public,receipts)
        self.assertEqual(expected['per_arm']['oracle']['literal_answer'],3)
        broken=copy.deepcopy(receipts);broken[0]['records'][0]['text']='made-up'
        with self.assertRaises(ValueError):review((ROOT/'locomo.json').read_bytes(),public,broken)

    def test_reviewer_denies_forged_price(self):
        if not ROOT.joinpath('locomo.json').exists() or not all(p.exists() for p in RUNS):
            self.skipTest('full original source/real pretrained predictions absent')
        public=json.loads(PANEL.read_bytes());receipts=[json.loads(f.read_bytes()) for f in RUNS]
        broken=copy.deepcopy(receipts);broken[0]['physical_work']['calls']=0
        broken[0]['digest']=digest({k:v for k,v in broken[0].items() if k!='digest'})
        with self.assertRaises(ValueError):review((ROOT/'locomo.json').read_bytes(),public,broken)

    def test_original_roster_and_bm25_replay(self):
        if not (ROOT/'locomo.json').exists():self.skipTest('publisher bytes unavailable')
        packet=from_original((ROOT/'locomo.json').read_bytes())
        self.assertEqual(packet['digest'],'4509418014c0178baffaa32c877671f17a1f8cf59567c8bde6f32678e999cb51')
        self.assertEqual(len(packet['cases']),16)

    def test_held_labels_not_in_reader_root(self):
        if not (ROOT/'reader').exists():self.skipTest('model material absent')
        self.assertFalse((ROOT/'reader'/'locomo.json').exists())
        self.assertFalse((ROOT/'reader'/'gold.json').exists())


class G9OriginalModelTests(unittest.TestCase):
    def test_real_native_tokenizer_roundtrip(self):
        if not (ROOT/'reader'/'tokenizer.json').exists():self.skipTest('original tokenizer absent')
        t=ByteBPE(ROOT/'reader'/'tokenizer.json')
        s='Hello world! When was the book bought in 2023?'
        self.assertEqual(t.decode(t.encode(s)),s)

    def test_original_native_model_prefill_decode_parity(self):
        if not (ROOT/'reader'/'model.safetensors').exists():self.skipTest('original weights absent')
        import torch
        model=NativeSmolLM135(ROOT/'reader')
        seq=[1]+model.tok.encode('user\nWhat year?')+[2,1]+model.tok.encode('assistant\n')
        logits=model.logits(seq);token=int(logits.argmax());native=model.next_step(token)
        reference=model.logits(seq+[token]);self.assertEqual(int(native.argmax()),int(reference.argmax()))
        self.assertLess(float((native-reference).abs().max()),0.0001)

if __name__=='__main__':unittest.main()
