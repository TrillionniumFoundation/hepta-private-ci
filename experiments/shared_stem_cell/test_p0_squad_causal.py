"""Adversarial *synthetic* source/evaluator fixtures, never original pretrained outcomes."""
from __future__ import annotations
import copy
import json
import tempfile
import unittest
from pathlib import Path

import p0_squad_materials as source
import p0_real_reader_cpu as worker
import p0_reader_independent_review as scorer


def simulated_row(prefix, idx):
    answer=f'NAME{prefix}{idx:03d}'
    context=(f'This is a public paragraph about test location {idx} in region {prefix}. '
             f'The recorded item is {answer} for the public archive. '
             'An unrelated recorded measurement was mentioned during a ceremony. '
             'The final observation records a different local fact for context.')
    return {'id':f'{prefix}-{idx}', 'title':f'{prefix}.article.{idx}',
            'context':context,
            'question':f'Which item was recorded at test location {idx}?',
            'answers':{'text':[answer], 'answer_start':[context.index(answer)]}}


def synthetic_material():
    a=[simulated_row('T',i) for i in range(50)]
    b=[simulated_row('V',i) for i in range(22)]
    return source.build(a,b)


def fake_report(name, fit, blind):
    """Deliberately fabricated claims for *negative validation tests* only."""
    pred=[{'case_id': c['case_id'], 'view_sha256':c['view_sha256'],
           'positive_probability': .91 if c['condition']=='sufficient' else .1,
           'encoder_forward_ms':.7,'head_forward_ms':.15,
           'full_request_ms':1.2} for c in blind['cases']]
    base={'schema':'hepta.p0.squad-physical-reader-receipt.v1','model':name,
          'fit_material_sha256':source.digest(source.canonical(fit)),
          'blind_material_sha256':source.digest(source.canonical(blind)),
          'number_blind_cases':len(blind['cases']),
          'actual_pretrained_execution_claimed':True, # UNTRUSTED synthetic fixture
          'source_model_independently_authenticated':False,
          'physical_model_calls_independently_authenticated':False,
          'human_independent_premise_reviewed':False,
          'future_outcomes_verified':False,
          'model_winner_selected':False,
          'production_promotion_permitted':False,'authority':'DENY_ALL',
          'cpu_process_ms':300.,'end_to_end_wall_ms':450.,'peak_process_rss_bytes':1500000000.,
          'model_load_ms':100.}
    if name=='laya421_nochange':
        return base | {'model_revision':worker.LAYA_SHA,
                       'head_mode':'pretrained_checkpoint_native_noul_nochange_not_equal_head',
                       'training':None,'control':{
                           'laya_native_nochange':{'predictions':pred}}}
    revision,width=worker.COMPACT_REVISIONS[name]
    return base | {'model_revision':revision, 'feature_width':width,
                   'original_e1_loader_preflight_claimed':True,
                   'mmbert_whole_serialized_checkpoint_byte_checked':True if name=='mmbert_small' else None,
                   'physical_model_load_and_encodings_ms':200.,
                   'head_mode':'frozen_same_initialization_vs_real_sgd',
                   'training':{'steps':worker.STEPS,'seed':worker.SEED,
                               'trained_head_parameters':2*width+2,
                               'initialized_frozen_weight_sha256':'1'*64,
                               'head_train_ms':18.,'train_only_gradient_update':True,
                               'control':{'frozen_head':{'head_sha256':'1'*64,'predictions':pred},
                                          'trained_head':{'head_sha256':'2'*64,'predictions':pred}}}}


class MaterialsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fit,cls.blind,cls.labels=synthetic_material()

    def test_genuine_algorithmic_split_and_all_four_conditions(self):
        self.assertEqual(len(self.fit['cases']), (source.WANTED['train']+source.WANTED['calibration'])*4)
        self.assertEqual(len(self.blind['cases']), source.WANTED['test']*4)
        worker.validate_materials(self.fit,self.blind)

    def test_no_label_in_blind(self):
        self.assertTrue(all('label' not in x for x in self.blind['cases']))
        self.assertTrue(all(x['label'] in (0,1,None) for x in self.labels['cases']))

    def test_edited_answer_must_match_original_bytes(self):
        example=simulated_row('N',11)
        with self.assertRaises(source.Invalid):
            source.remove_answer_sentence(example['context'],example['answers']['answer_start'][0]+1,'NAME')

    def test_remove_crucial_span(self):
        c=simulated_row('Q',9)
        removed,_=source.remove_answer_sentence(c['context'],c['answers']['answer_start'][0],c['answers']['text'][0])
        self.assertNotIn(c['answers']['text'][0],removed)
        self.assertIn('The final observation',removed)

    def test_answer_present_twice_rejected(self):
        c=simulated_row('N',12)
        answer=c['answers']['text'][0]
        text=c['context']+' Another note recorded '+answer+' in the archive.'
        with self.assertRaises(source.Invalid):
            source.remove_answer_sentence(text,c['answers']['answer_start'][0],answer)

    def test_unanswerable_squad_not_forged_positive(self):
        c=simulated_row('N',12)
        c['answers']={'text':[], 'answer_start':[]}
        self.assertIsNone(source.candidate(c))

    def test_nonanswer_source_rows_not_selected(self):
        short={'id':'bad','title':'short','context':'small',
               'question':'ok?', 'answers':{'text':['item'],'answer_start':[1]}}
        self.assertIsNone(source.candidate(short))

    def test_source_group_disjoint(self):
        names={s:{r['group_id'] for r in self.fit['cases']+self.blind['cases'] if r['split']==s}
               for s in source.WANTED}
        self.assertFalse(names['train']&names['calibration'])
        self.assertFalse(names['test']&names['train'])

    def test_repeat_title_rejected(self):
        c=simulated_row('S',1)
        with self.assertRaises(source.Invalid):
            source.select([c]*10, 2)

    def test_material_json_duplicate_key(self):
        with tempfile.TemporaryDirectory() as d:
            f=Path(d)/'dup.json';f.write_text('{"x":1,"x":2}')
            with self.assertRaises(source.Invalid):source.read(f)

    def test_material_create_only(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'a.json'
            source.write_new(path,{'x':1})
            with self.assertRaises(FileExistsError):source.write_new(path,{'x':2})

    def test_wrong_split_label_contamination_denied(self):
        b=copy.deepcopy(self.blind)
        b['cases'][0]['label']=1
        with self.assertRaises(source.Invalid):worker.validate_materials(self.fit,b)

    def test_missing_one_intervention_denied(self):
        b=copy.deepcopy(self.blind)
        b['cases'].pop()
        with self.assertRaises(source.Invalid):worker.validate_materials(self.fit,b)

    def test_evidence_byte_tampering_denied(self):
        b=copy.deepcopy(self.blind)
        b['cases'][0]['joint_input']['state']='tampered'
        with self.assertRaises(source.Invalid):worker.validate_materials(self.fit,b)

    def test_source_scope_leakage_denied(self):
        b=copy.deepcopy(self.blind)
        b['cases'][0]['group_id']=self.fit['cases'][0]['group_id']
        with self.assertRaises(source.Invalid):worker.validate_materials(self.fit,b)

    def test_future_credential_claim_denied(self):
        b=copy.deepcopy(self.blind);b['metadata']['future_chronology_verified']=True
        with self.assertRaises(source.Invalid):worker.validate_materials(self.fit,b)

    def test_nonfinite_json_denied(self):
        with tempfile.TemporaryDirectory() as d:
            f=Path(d)/'invalid.json';f.write_text('{"value":NaN}')
            with self.assertRaises(source.Invalid):source.read(f)

    def test_source_revision_drift_denied_before_any_model_load(self):
        b=copy.deepcopy(self.blind)
        b['metadata']['dataset_commit']='main'
        f=copy.deepcopy(self.fit);f['metadata']['dataset_commit']='main'
        with self.assertRaises(source.Invalid):worker.validate_materials(f,b)

    def test_case_id_must_bind_source_and_intervention(self):
        b=copy.deepcopy(self.blind)
        b['cases'][0]['case_id']='f'*24
        with self.assertRaises(source.Invalid):worker.validate_materials(self.fit,b)

    def test_train_label_tamper_denied(self):
        f=copy.deepcopy(self.fit)
        candidate=next(x for x in f['cases'] if x['condition']=='sufficient')
        candidate['label']=0
        with self.assertRaises(source.Invalid):worker.validate_materials(f,self.blind)

    def test_retrieval_training_truth_cannot_be_fabricated(self):
        f=copy.deepcopy(self.fit)
        candidate=next(x for x in f['cases'] if x['condition']=='retrieved')
        candidate['label']=None if candidate['label']==1 else 1
        with self.assertRaises(source.Invalid):worker.validate_materials(f,self.blind)

    def test_four_interventions_must_share_same_document_group(self):
        b=copy.deepcopy(self.blind)
        first=b['cases'][0]
        first['group_id']='a'*64
        with self.assertRaises(source.Invalid):worker.validate_materials(self.fit,b)

    def test_fake_source_production_authority_denied(self):
        f=copy.deepcopy(self.fit);b=copy.deepcopy(self.blind)
        f['metadata']['production_promotion_permitted']=True
        b['metadata']['production_promotion_permitted']=True
        with self.assertRaises(source.Invalid):worker.validate_materials(f,b)

    def test_original_parquet_sha_required(self):
        with tempfile.TemporaryDirectory() as d:
            f=Path(d)/'no.parquet';f.write_bytes(b'not an original SQuAD parquet')
            with self.assertRaises(source.Invalid):source.from_parquet(f,source.TRAIN_SHA)


class HeadExecutionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fit,cls.blind,_=synthetic_material()

    def test_real_cpu_torch_head_training_with_fake_features_not_pretrained(self):
        try: import torch
        except ImportError:self.skipTest('Torch runs in dedicated pinned physical CPU workflow')
        for width in (256,384):
            rows=self.fit['cases']+self.blind['cases']
            features={c['case_id']:[float((sum(c['case_id'].encode())%100)/100.)]*width for c in rows}
            v=worker.train_frozen_heads(self.fit['cases'],self.blind['cases'],features,width)
            self.assertEqual(v['trained_head_parameters'],2*width+2)
            self.assertNotEqual(v['control']['frozen_head']['head_sha256'],v['control']['trained_head']['head_sha256'])
            self.assertEqual(len(v['control']['trained_head']['predictions']),len(self.blind['cases']))

    def test_missing_feature_denied(self):
        try: import torch
        except ImportError:self.skipTest('Torch not installed')
        features={c['case_id']:[.1]*256 for c in self.fit['cases']}
        with self.assertRaises(source.Invalid):
            worker.train_frozen_heads(self.fit['cases'],self.blind['cases'],features,256)


class ReviewTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fit,cls.blind,cls.labels=synthetic_material()

    def reports(self):
        return {name:fake_report(name,self.fit,self.blind) for name in worker.MODELS}

    def test_four_claimed_arms_structurally_reviewed_only(self):
        r=scorer.review(self.fit,self.blind,self.labels,self.reports())
        self.assertEqual(set(r['results']),set(worker.MODELS))
        self.assertTrue(r['no_independent_semantic_verdict_for_mechanical_negative'])
        self.assertFalse(r['model_selection_permitted'])
        x=r['results']['mmbert_small']['controls']['trained_head']
        self.assertEqual(x['paired_oracle_vs_removed_groups'],source.WANTED['test'])
        self.assertEqual(x['lexical_answer_presence_baseline_accuracy'],1.)

    def test_deny_missing_real_model_arm(self):
        reports=self.reports();reports.pop('laya421_nochange')
        with self.assertRaises(source.Invalid):scorer.review(self.fit,self.blind,self.labels,reports)

    def test_wrong_native_laya_treated_as_trainable_is_denied(self):
        r=self.reports();r['laya421_nochange']['training']={'steps':40}
        with self.assertRaises(source.Invalid):scorer.review(self.fit,self.blind,self.labels,r)

    def test_fake_power_not_admitted_as_real(self):
        r=self.reports();r['granite_97m_r2']['source_model_independently_authenticated']=True
        with self.assertRaises(source.Invalid):scorer.review(self.fit,self.blind,self.labels,r)

    def test_swapped_report_source_identity_denied(self):
        r=self.reports();r['granite_97m_r2']['blind_material_sha256']='0'*64
        with self.assertRaises(source.Invalid):scorer.review(self.fit,self.blind,self.labels,r)

    def test_bad_predicted_probability_denied(self):
        r=self.reports();r['mmbert_small']['training']['control']['trained_head']['predictions'][1]['positive_probability']=float('nan')
        with self.assertRaises(source.Invalid):scorer.review(self.fit,self.blind,self.labels,r)

    def test_missing_one_case_in_original_predictions_denied(self):
        r=self.reports();r['embeddinggemma_2_text']['training']['control']['frozen_head']['predictions'].pop()
        with self.assertRaises(source.Invalid):scorer.review(self.fit,self.blind,self.labels,r)

    def test_eval_label_tamper_denied(self):
        labels=copy.deepcopy(self.labels)
        row=next(x for x in labels['cases'] if x['condition']=='sufficient')
        row['label']=0
        with self.assertRaises(source.Invalid):scorer.review(self.fit,self.blind,labels,self.reports())

    def test_retrieval_nonowner_cannot_claim_success(self):
        b=copy.deepcopy(self.blind); labels=copy.deepcopy(self.labels)
        row=next(x for x in b['cases'] if x['condition']=='retrieved')
        row['retrieved_source_id']='other-source'
        target=next(x for x in labels['cases'] if x['case_id']==row['case_id'])
        target['label']=1
        r=self.reports()
        for report in r.values():report['blind_material_sha256']=source.digest(source.canonical(b))
        with self.assertRaises(source.Invalid):scorer.review(self.fit,b,labels,r)

    def test_request_work_cannot_exceed_process_wall(self):
        r=self.reports()
        r['laya421_nochange']['end_to_end_wall_ms']=30.
        with self.assertRaises(source.Invalid):
            scorer.review(self.fit,self.blind,self.labels,r)

    def test_loading_plus_actual_head_learning_must_fit_process_wall(self):
        r=self.reports()
        r['granite_97m_r2']['training']['head_train_ms']=400.
        with self.assertRaises(source.Invalid):
            scorer.review(self.fit,self.blind,self.labels,r)

    def test_missing_duration_denied(self):
        r=self.reports();r['laya421_nochange']['control']['laya_native_nochange']['predictions'][0]['full_request_ms']=0
        with self.assertRaises(source.Invalid):scorer.review(self.fit,self.blind,self.labels,r)

    def test_wrong_frozen_head_lineage_denied(self):
        r=self.reports();r['mmbert_small']['training']['control']['frozen_head']['head_sha256']='3'*64
        with self.assertRaises(source.Invalid):scorer.review(self.fit,self.blind,self.labels,r)

    def test_laya_wrong_checkpoint_rejected(self):
        r=self.reports();r['laya421_nochange']['model_revision']='main'
        with self.assertRaises(source.Invalid):scorer.review(self.fit,self.blind,self.labels,r)

    def test_no_other_models_derived_from_hidden_labels(self):
        r=self.reports();p=r['granite_97m_r2']['training']['control']['trained_head']['predictions'][0]
        p['label']=1
        with self.assertRaises(source.Invalid):scorer.review(self.fit,self.blind,self.labels,r)

    def test_duplicate_source_intervention_denied(self):
        r=self.reports();pred=r['granite_97m_r2']['training']['control']['trained_head']['predictions']
        pred[0]=copy.deepcopy(pred[1])
        with self.assertRaises(source.Invalid):scorer.review(self.fit,self.blind,self.labels,r)

    def test_equal_quality_still_no_authorized_winner(self):
        r=scorer.review(self.fit,self.blind,self.labels,self.reports())
        self.assertTrue(all(value['controls'] for value in r['results'].values()))
        self.assertFalse(r['production_promotion_permitted'])
        self.assertTrue(r['four_model_equal_training_budget'] is False)



class WorkflowContractTest(unittest.TestCase):
    def test_source_workflow_recomputes_question_only_before_model_run(self):
        workflow=(Path(__file__).resolve().parents[2] /
                  '.github/workflows/hepta-p0-real-four-reader.yml').read_text()
        self.assertEqual(workflow.count('Independent label-blind original source/retrieval preflight'),1)
        self.assertIn('independent_question_only_retrieval(train+held)',workflow)
        self.assertIn('question-only-preflight.json',workflow)
        self.assertLess(workflow.index('Independent label-blind original source/retrieval preflight'),
                        workflow.index('  physical-four-models:'))

    def test_reviewed_checkout_ref_is_single_exact_pin(self):
        workflow=(Path(__file__).resolve().parents[2] / '.github/workflows/hepta-p0-real-four-reader.yml').read_text()
        for title, expected in (
            ('Checkout exact reviewed original compact Stem source', 'e05f939f65fb76f6bdbf7470eef7e63b77284dcd'),
            ('Checkout exact reviewed Gemma source', 'f8d168a7689eb3624d97c44751791badd069e521'),
        ):
            marker='      - name: '+title+'\n'
            self.assertEqual(workflow.count(marker), 1)
            begin=workflow.index(marker)
            end=workflow.find('\n      - ', begin+len(marker))
            section=workflow[begin:None if end<0 else end]
            refs=[line.split(':',1)[1].strip() for line in section.splitlines()
                  if line.startswith('          ref:')]
            self.assertEqual(refs,[expected], 'duplicate or mutable checkout source ref')



class QuestionOnlyRetrievalIntegrityTest(unittest.TestCase):
    """Adversarial mechanism tests only: synthetic data is NEVER model efficacy."""

    @classmethod
    def setUpClass(cls):
        cls.fit, cls.blind, cls.labels = synthetic_material()

    @staticmethod
    def rehash(case):
        case['view_sha256'] = source.digest(source.canonical(case['joint_input']))
        case['evidence_sha256'] = source.digest(case['joint_input']['state'].encode())

    def test_retrieval_must_be_independent_of_annotated_correct_answer(self):
        items = [
            {'source_id':'a','context':'eastern ridge has tall pine forest near market',
             'question':'Which ridge is near the market?', 'answer':'pine'},
            {'source_id':'b','context':'western ridge has a tall market building and river',
             'question':'Which ridge is near the market?', 'answer':'market'},
            {'source_id':'c','context':'the ridge and market are part of ancient ruins',
             'question':'Which ridge is near the market?', 'answer':'ancient'},
        ]
        first=source.bm25_neighbors(items)
        modified=copy.deepcopy(items)
        for item in modified:
            item['answer']='newly planted labeled answer never appearing in the passages'
        self.assertEqual(first,source.bm25_neighbors(modified))

    def test_query_answer_literal_is_excluded_from_squad_source_selection(self):
        item=simulated_row('Q',3)
        item['question']='What is the recorded NAMEQ003 item?'
        self.assertIsNone(source.candidate(item))

    def test_v1_retrieval_protocol_must_not_be_reinterpreted_as_v2(self):
        fit=copy.deepcopy(self.fit);blind=copy.deepcopy(self.blind)
        for doc in (fit,blind):
            doc['metadata']['retriever']='bm25:k1=1.2:b=0.75:within-partition:v1'
        with self.assertRaises(source.Invalid):worker.validate_materials(fit,blind)

    def test_v1_source_selection_must_not_pass_new_frozen_rule(self):
        fit=copy.deepcopy(self.fit);blind=copy.deepcopy(self.blind)
        for doc in (fit,blind):doc['metadata']['sample_rule']='sha256-title-rank:v1'
        with self.assertRaises(source.Invalid):worker.validate_materials(fit,blind)

    def test_retrieved_donor_swap_rejected_even_after_all_hashes_updated(self):
        blind=copy.deepcopy(self.blind)
        target=next(x for x in blind['cases'] if x['condition']=='retrieved')
        original_donor=target['retrieved_source_id']
        other=next(x for x in blind['cases'] if x['condition']=='sufficient' and x['source_id']!=original_donor)
        target['retrieved_source_id']=other['source_id']
        target['joint_input']['state']=other['joint_input']['state']
        self.rehash(target)
        with self.assertRaises(source.Invalid):worker.validate_materials(self.fit,blind)

    def test_retrieval_claim_without_donor_bytes_rejected_even_after_rehash(self):
        blind=copy.deepcopy(self.blind)
        target=next(x for x in blind['cases'] if x['condition']=='retrieved')
        target['joint_input']['state']='a fabricated passage with unrelated evidence'
        self.rehash(target)
        with self.assertRaises(source.Invalid):worker.validate_materials(self.fit,blind)

    def test_premise_removed_not_a_full_sentence_deletion_rejected_with_rehash(self):
        blind=copy.deepcopy(self.blind)
        target=next(x for x in blind['cases'] if x['condition']=='premise_removed')
        target['joint_input']['state'] += ' a harmless extra sentence.'
        self.rehash(target)
        with self.assertRaises(source.Invalid):worker.validate_materials(self.fit,blind)

    def test_no_evidence_control_not_mutable_after_rehash(self):
        blind=copy.deepcopy(self.blind)
        target=next(x for x in blind['cases'] if x['condition']=='none')
        target['joint_input']['state']='no evidence except accidental cue'
        self.rehash(target)
        with self.assertRaises(source.Invalid):worker.validate_materials(self.fit,blind)

    def test_question_cannot_drift_in_only_one_counterfactual_arm(self):
        blind=copy.deepcopy(self.blind)
        target=next(x for x in blind['cases'] if x['condition']=='premise_removed')
        target['joint_input']['question'] += ' Is this safe?'
        self.rehash(target)
        with self.assertRaises(source.Invalid):worker.validate_materials(self.fit,blind)

    def test_source_view_rewrite_and_digest_reseal_detected(self):
        blind=copy.deepcopy(self.blind)
        target=next(x for x in blind['cases'] if x['condition']=='sufficient')
        target['joint_input']['state'] += ' some unrelated text'
        target['annotated_answer_source_sha256']=source.digest(target['joint_input']['state'].encode())
        self.rehash(target)
        with self.assertRaises(source.Invalid):worker.validate_materials(self.fit,blind)

    def test_second_source_reviewer_replays_bm25_without_producer_helper(self):
        expected=scorer.independent_question_only_retrieval(
            self.fit['cases']+self.blind['cases'])
        self.assertEqual(set(expected),set(source.WANTED))
        self.assertEqual(expected['test']['questions'],source.WANTED['test'])
        from unittest.mock import patch
        with patch.object(worker, 'bm25_neighbors', side_effect=RuntimeError('producer BM25 unavailable')):
            self.assertEqual(expected,scorer.independent_question_only_retrieval(
                self.fit['cases']+self.blind['cases']))

    def test_second_source_reviewer_rejects_self_consistent_but_wrong_donor(self):
        blind=copy.deepcopy(self.blind)
        target=next(x for x in blind['cases'] if x['condition']=='retrieved')
        new_donor=next(x for x in blind['cases'] if x['condition']=='sufficient' and
                       x['source_id']!=target['retrieved_source_id'])
        target['joint_input']['state']=new_donor['joint_input']['state']
        target['retrieved_source_id']=new_donor['source_id']
        self.rehash(target)
        with self.assertRaises(source.Invalid):scorer.independent_question_only_retrieval(
            self.fit['cases']+blind['cases'])

    def test_score_reveals_retrieval_hit_rate_without_forged_nonowner_labels(self):
        reports={name:fake_report(name,self.fit,self.blind) for name in worker.MODELS}
        result=scorer.review(self.fit,self.blind,self.labels,reports)
        m=result['results']['granite_97m_r2']['controls']['trained_head']
        self.assertEqual(m['question_only_retrieval_original_source_hit_count'] +
                         m['retrieved_unreviewed_count'],source.WANTED['test'])
        self.assertTrue(m['nonowner_retrieval_accuracy_unavailable'])
        self.assertTrue(0 <= m['question_only_retrieval_original_source_hit_at_1'] <= 1)


if __name__=='__main__':unittest.main()
