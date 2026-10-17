"""V7 offline tests use artificial features, NEVER claim pretrained-image quality."""
import copy
import json
import unittest
from unittest.mock import patch
import torch
import torch.nn.functional as F

import scienceqa_image_intervention_v7 as run
import scienceqa_image_intervention_v7_review as audit


def source():
    rows=[]
    for i in range(192):
        split='train' if i<96 else 'validation' if i<128 else 'test'
        rows.append({'id': f'{i+1:064x}','group': f'{i+1000:064x}',
                     'split':split,'scope':'public-scienceqa-e3-research',
                     'question':'Q','hint':'','choices':['A','B','C','D'],
                     'image':f'{i+5000:064x}'})
    return rows

class TestPhysicalInterventionMechanics(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(2)
        torch.manual_seed(71)
        cls.rows=source()
        cls.labels=[{'id':s['id'],'label':i%4} for i,s in enumerate(cls.rows[:128])]
        cls.q=F.normalize(torch.randn(192,384),dim=-1)
        cls.c=F.normalize(torch.randn(192,4,384),dim=-1)
        cls.images=F.normalize(torch.randn(192,384),dim=-1)

    def test_deterministic_different_source_image(self):
        m=run.source_derangement(self.rows)
        self.assertEqual(len(m),64)
        self.assertEqual(set(m),set(m.values()))
        self.assertEqual(m,run.source_derangement(self.rows[::-1]))
        self.assertTrue(all(k!=v for k,v in m.items()))
        data=copy.deepcopy(self.rows)
        data[-2]['group']=data[-1]['group']
        with self.assertRaises(run.InterventionError):run.source_derangement(data)

    def test_actual_train_only_ranked_head_no_test_labels(self):
        a=run.training_once(self.rows,self.labels,self.q,self.c,self.images,steps=2)
        b=run.training_once(self.rows,self.labels,self.q,self.c,self.images,steps=2)
        self.assertEqual(a['bridge_hash'],b['bridge_hash'])
        self.assertEqual(a['gate_hash'],b['gate_hash'])
        self.assertEqual(sum(v.numel() for v in a['gate'].parameters()),769)
        out=run.prediction_variant(self.q[-64:],self.c[-64:],self.images[-64:],a)
        self.assertEqual(len(out),64)
        self.assertEqual(len(out[0]),4)
        self.assertAlmostEqual(sum(out[0]),1.,places=6)
        other=run.prediction_variant(self.q[-64:],self.c[-64:],
                                      self.images[-64:].roll(1,dims=0),a)
        self.assertGreater(max(abs(x-y) for row1,row2 in zip(out,other)
                               for x,y in zip(row1,row2)),1e-8)
        forged=self.labels+[{'id':self.rows[-1]['id'],'label':1}]
        with self.assertRaises(run.InterventionError):
            run.training_once(self.rows,forged,self.q,self.c,self.images,steps=2)

    def test_historical_original_parity_fail_closed(self):
        old=[]
        for i in range(64):
            old.append({'id':str(i),'group':str(64+i),'source_input_sha256':f'{i:064x}',
                        'arms':{'text_only':[.6,.2,.1,.1],'train_gate':[.6,.2,.1,.1]}})
        self.assertEqual(run.validate_original_parity(copy.deepcopy(old),old),0.)
        changed=copy.deepcopy(old);changed[0]['arms']['train_gate']=[.2,.6,.1,.1]
        with self.assertRaises(run.InterventionError):
            run.validate_original_parity(changed,old)
        changed=copy.deepcopy(old);changed[1]['arms']['text_only']=[.601,.199,.1,.1]
        self.assertAlmostEqual(run.validate_original_parity(changed,old),.001)

    def _independent_label_review_fixture(self):
        rows=source()
        held=[{'id':r['id'],'label':0} for r in rows[-64:]]
        archive_rows=[]; interventions=[]
        test=rows[-64:]
        for j,row in enumerate(test):
            # Frozen original correct-image model has 24 / 64 correct;
            # frozen text-only has 17 / 64 correct, as in original real E3.
            def probs(good):
                return [.7,.1,.1,.1] if good else [.1,.7,.1,.1]
            visual=probs(j<24); textual=probs(j<17)
            identity=audit.sha(audit.canonical(row))
            archive_rows.append({'id':row['id'],'group':row['group'],
                                 'source_input_sha256':identity,
                                 'arms':{'train_gate':visual,'text_only':textual}})
            peer=test[(j+1)%len(test)]
            interventions.append({'id':row['id'],'group':row['group'],
                       'source_input_sha256':identity,'split':'test',
                       'other_group_image_from_id':peer['id'],
                       'other_group_image_source_group':peer['group'],
                       'arms':{'correct_image':visual,'other_group_image':probs(j<12),
                               'black_image':probs(j<18),'text_only':textual}})
        hist={'source_sha256':'a'*64,
              'fit':{'organ_fitted_bridge_sha256':'b'*64,
                     'gate_sha256':'c'*64},'predictions':archive_rows}
        frozen=audit.canonical(hist)
        candidate={'schema':audit.SCHEMA, 'source_sha256':'a'*64,
            'fit_labels_sha256':audit.FIT_SHA,'original_prediction_sha256':audit.sha(frozen),
            'original_model_code_commit':audit.HEAD,
            'model_text_repo':'ibm-granite/granite-embedding-97m-multilingual-r2',
            'model_text_revision':'835ad14087e140460703cf0fae09f97d469d65c2',
            'model_vision_repo':'facebook/dinov2-small',
            'model_vision_revision':'ed25f3a31f01632728cabb09d1542f84ab7b0056',
            'original_trained_bridge_sha256':'b'*64,'original_trained_gate_sha256':'c'*64,
            'historical_bridge_sha256':'b'*64,'historical_gate_sha256':'c'*64,
            'historical_bridge_byte_parity':True,'historical_gate_byte_parity':True,
            'training_steps_original':80,'training_steps_independent_check':80,
            'text_forward_batches_original':60,'vision_forward_batches_original':24,
            'vision_forward_batches_black_mask':1,'vision_forward_batches_other_image_extra':0,
            'history_max_probability_delta':0.,'independent_refit_max_probability_delta':0.,
            'black_image_png_sha256':'d'*64, 'per_case_predictions':interventions,
            'test_labels_loaded_by_producer':False,'same_head_parameters_in_all_image_arms':True,
            'actual_frozen_pretrained_model_executed':True,
            'actual_image_mask_dino_forward_executed':True,
            'other_group_image_source_was_physically_encoded':True,
            'independent_human_necessity_adjudication':False,'model_promoted':False,
            'production_authorized':False,'authority':'DENY_ALL'}
        return candidate,rows,held,{'sealed-source-bound-predictions.json':frozen}

    def test_independent_late_label_join_on_original_shape(self):
        candidate,rows,held,archive=self._independent_label_review_fixture()
        with patch.object(audit,'SOURCE_SHA','a'*64),patch.object(
                audit,'ORIGINAL_SHA',candidate['original_prediction_sha256']):
            result=audit.review(candidate,rows,held,archive)
        self.assertEqual(result['arms']['correct_image']['correct'],24)
        self.assertEqual(result['arms']['text_only']['correct'],17)
        self.assertEqual(result['arms']['other_group_image']['correct'],12)
        self.assertFalse(result['independent_human_visual_necessity_adjudicated'])
        self.assertEqual(result['authority'],'DENY_ALL')

    def test_reject_forged_mispair_labels_and_missing_forward(self):
        candidate,rows,held,archive=self._independent_label_review_fixture()
        for label, mutate in (
            ('wrong_mispaired_group',lambda x: x['per_case_predictions'][0].__setitem__(
                'other_group_image_source_group','e'*64)),
            ('unauthorized',lambda x: x.__setitem__('production_authorized',True)),
            ('fake_forward',lambda x: x.__setitem__('vision_forward_batches_black_mask',0)),
            ('extra_target',lambda x: x['per_case_predictions'][0].__setitem__('label',0)),
            ('wrong_source_model',lambda x: x.__setitem__('model_text_revision','mutable')),
            ('missing_case',lambda x: x['per_case_predictions'].pop()),
        ):
            bad=copy.deepcopy(candidate);mutate(bad)
            with self.subTest(label=label),patch.object(audit,'SOURCE_SHA','a'*64),patch.object(
                    audit,'ORIGINAL_SHA',candidate['original_prediction_sha256']):
                with self.assertRaises(audit.ReviewError):audit.review(bad,rows,held,archive)

    def test_prelabel_seal_rejects_tamper_and_substituted_file(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as root:
            producer=Path(root)/'sealed-interventions.json'
            seal=Path(root)/'prelabel.sha256'
            original=b'{"source":"prelabel-only","authority":"DENY_ALL"}\\n'
            producer.write_bytes(original)
            seal.write_text(audit.sha(original)+'  '+str(producer)+'\\n',encoding='ascii')
            self.assertEqual(audit.verify_prelabel_seal(seal,producer,original),
                             audit.sha(original))
            for content in ('0'*64+'  '+str(producer)+'\\n',
                            audit.sha(original)+'  '+str(producer)+'-wrong\\n',
                            audit.sha(original)+' *'+str(producer)+'\\n'):
                seal.write_text(content,encoding='ascii')
                with self.assertRaises(audit.ReviewError):
                    audit.verify_prelabel_seal(seal,producer,original)
            seal.write_text(audit.sha(original)+'  '+str(producer)+'\\n',encoding='ascii')
            with self.assertRaises(audit.ReviewError):
                audit.verify_prelabel_seal(seal,producer,original+b'drift')
            link=Path(root)/'link.sha256'
            link.symlink_to(seal)
            with self.assertRaises(audit.ReviewError):
                audit.verify_prelabel_seal(link,producer,original)

    def test_reject_fake_review_or_nonfinite(self):
        with self.assertRaises(audit.ReviewError):audit.parse(b'{"a":1,"a":2}')
        with self.assertRaises(audit.ReviewError):audit.parse(b'{"a":1e999}')
        with self.assertRaises(audit.ReviewError):audit.top1([.1,.2,float('nan'),.7])
        self.assertEqual(audit.exact_p(14,7),.18924713134765625)
        self.assertEqual(audit.exact_p(0,0),1.)
        with self.assertRaises(audit.ReviewError):audit.review({},self.rows,[],{})

if __name__=='__main__':unittest.main()
