"""Original-report public source adversarial tests; synthetic cases are not model inference."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from v12_public_audit import audit,read_file
from v12_reader_disagreement import disagreement_inventory,read_exact,SCHEMA

HERE=Path(__file__).parent
PUBLIC=HERE/'STEM_V12_ORIGINAL_READER_NEGATIVE_20261015.json'

def mock_v11():
    sample=['A','B','C']
    table={f'conv-47/q{i}':{
        **{'bm25_full':sample.copy(),'dense_full':['D','E','F']},
        **{f'seed{s}/{arm}':sample.copy() for s in (41,47,53) for arm in ('residual','safe_two')}
    } for i in range(829)}
    for seed,ordered,changed in ((41,68,3),(47,7,0),(53,46,1)):
        for i in range(ordered):
            table[f'conv-47/q{i}'][f'seed{seed}/residual']=(['A','B','X'] if i<changed else ['A','C','B'])
    return {'schema':SCHEMA.replace('v12.original-disagreement-reader','v11.original-minilm-lexical-residual')+'.sealed-predictions',
            'labels_read_before_seal':False,'production_authorized':False,'predictions':table}

class TestV12(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.original=read_file(PUBLIC)
    def test_public_negative(self):
        self.assertEqual(audit(self.original)['audit'],'PASS_CONTRACT_ONLY')
    def test_original_source_sha_required(self):
        v=copy.deepcopy(self.original);v['upstream_v9_source_sha256']='0'*64
        with self.assertRaises(ValueError):audit(v)
    def test_no_production(self):
        v=copy.deepcopy(self.original);v['production_authorized']=True
        with self.assertRaises(ValueError):audit(v)
    def test_no_promotion(self):
        v=copy.deepcopy(self.original);v['stem_winner_verified']=True
        with self.assertRaises(ValueError):audit(v)
    def test_no_semantic_claim(self):
        v=copy.deepcopy(self.original);v['human_semantic_correctness']=1.0
        with self.assertRaises(ValueError):audit(v)
    def test_no_extra_source_family(self):
        v=copy.deepcopy(self.original);v['independent_source_roots']=4
        with self.assertRaises(ValueError):audit(v)
    def test_disagreement_not_829_independents(self):
        v=copy.deepcopy(self.original);v['unique_disagreement_questions']=829
        with self.assertRaises(ValueError):audit(v)
    def test_no_fake_reader_calls(self):
        v=copy.deepcopy(self.original);v['deduplicated_genuine_reader_requests']=12
        with self.assertRaises(ValueError):audit(v)
    def test_unknown_reader_parity(self):
        v=copy.deepcopy(self.original);v['official_HF_operator_tokenizer_parity']=True
        with self.assertRaises(ValueError):audit(v)
    def test_no_gold_source_hit(self):
        v=copy.deepcopy(self.original);v['publisher_weak_support_route_hits']=1
        with self.assertRaises(ValueError):audit(v)
    def test_no_fabricated_future(self):
        v=copy.deepcopy(self.original);v['independent_future_calendar_windows']=2
        with self.assertRaises(ValueError):audit(v)
    def test_no_full_compute_claim(self):
        v=copy.deepcopy(self.original);v['matched_total_lifecycle_cost']=True
        with self.assertRaises(ValueError):audit(v)
    def test_no_false_v6_fix(self):
        v=copy.deepcopy(self.original);v['v6_seed41_retention_fixed']=True
        with self.assertRaises(ValueError):audit(v)
    def test_no_out_of_range_model_hash(self):
        v=copy.deepcopy(self.original);v['reader_weights_sha256']='a'*64
        with self.assertRaises(ValueError):audit(v)
    def test_reject_extra_row(self):
        v=copy.deepcopy(self.original);v['secret_label']='leak'
        with self.assertRaises(ValueError):audit(v)
    def test_reject_missing_aggregate(self):
        v=copy.deepcopy(self.original);del v['original_reader_physical_forward_calls']
        with self.assertRaises(ValueError):audit(v)
    def test_reject_duplicate_json(self):
        with tempfile.TemporaryDirectory() as root:
            p=Path(root)/'dup.json';p.write_text('{"x":1,"x":2}')
            with self.assertRaises(ValueError):read_file(p)
    def test_reject_nonfinite(self):
        with tempfile.TemporaryDirectory() as root:
            p=Path(root)/'nan.json';p.write_text('{"x":NaN}')
            with self.assertRaises(ValueError):read_file(p)
    def test_reject_bad_public_digest(self):
        v=copy.deepcopy(self.original);v['rerun_token_text_sha256']='0'*63
        with self.assertRaises(ValueError):audit(v)
    def test_source_census_all_models_complete(self):
        data=mock_v11();data['schema']='hepta.stem.v11.original-minilm-lexical-residual.shadow.v1.sealed-predictions'
        counts,selected=disagreement_inventory(data)
        self.assertEqual(counts,{'41':{'ordered':68,'membership':3},'47':{'ordered':7,'membership':0},'53':{'ordered':46,'membership':1}})
        self.assertEqual(len(selected),3)
    def test_source_inventory_missing_denied(self):
        data=mock_v11();data['schema']='hepta.stem.v11.original-minilm-lexical-residual.shadow.v1.sealed-predictions';data['predictions'].pop('conv-47/q0')
        with self.assertRaises(ValueError):disagreement_inventory(data)
    def test_source_gold_column_denied(self):
        data=mock_v11();data['schema']='hepta.stem.v11.original-minilm-lexical-residual.shadow.v1.sealed-predictions';data['predictions']['conv-47/q1']['publisher_gold']=['A']
        with self.assertRaises(ValueError):disagreement_inventory(data)
    def test_source_duplicate_evidence_denied(self):
        data=mock_v11();data['schema']='hepta.stem.v11.original-minilm-lexical-residual.shadow.v1.sealed-predictions';data['predictions']['conv-47/q3']['bm25_full']=['A','A','B']
        with self.assertRaises(ValueError):disagreement_inventory(data)
    def test_original_file_byte_tamper(self):
        with tempfile.TemporaryDirectory() as root:
            p=Path(root)/'source.json';p.write_text('{"my_test":1}')
            with self.assertRaises(ValueError):read_exact(p,'f'*64)

if __name__=='__main__':unittest.main()
