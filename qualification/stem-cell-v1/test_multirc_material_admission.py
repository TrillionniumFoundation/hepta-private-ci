"""Genuine source-wide malformed MultiRC text must not block label-blind eligible passages.

All tests use strict source indices, no dataset weights, no fabricated inference.
The original trace failed during the full parquet scan, before any learning.
"""
import copy
import unittest

from multirc_materials import _group_inputs, prepare_panels, validate_panel_bundles
from multirc_candidate_slate import prepare_candidate_slate
from test_multirc_real_study import fixture_rows


SHA_T = 'a'*64
SHA_V = 'b'*64


def sources():
    return fixture_rows(10), fixture_rows(8, 'val')


def prepare(train, evaluation, *, train_count=5, eval_count=4):
    return prepare_panels(train, evaluation, seed=7347,
        train_passages=train_count, val_passages=eval_count,
        dataset_sha256_train=SHA_T, dataset_sha256_val=SHA_V)


class CompletePassageTextAdmission(unittest.TestCase):
    def test_bad_answer_excludes_entire_paragraph_and_keeps_slate_complete(self):
        a, b = sources()
        a[0]['answer'] = ''
        b[1]['answer'] = ''
        train, eval_, labels = prepare(a, b)
        self.assertTrue(validate_panel_bundles(train, eval_))
        stats = train['material_admission']
        self.assertEqual(stats['train']['invalid_text_fields']['answer'],1)
        self.assertEqual(stats['validation']['invalid_text_fields']['answer'],1)
        self.assertEqual(stats['train']['invalid_text_passages'],1)
        self.assertEqual(stats['validation']['invalid_text_passages'],1)
        self.assertEqual((len(train['rows']),len(eval_['rows'])),(5,4))
        # Neither side may choose just the other, originally valid answer
        # from an incomplete native paragraph.
        self.assertTrue(all('train passage 0' not in r['evidence'] for r in train['rows']))
        self.assertTrue(all('val passage 0' not in r['evidence'] for r in eval_['rows']))
        slate, receipt = prepare_candidate_slate(train,eval_,b,original_label_receipt=labels)
        self.assertEqual(len(slate['rows']),4)
        self.assertEqual(len(receipt['labels']),16)

    def test_whitespace_question_and_missing_answer_exclude_whole_groups(self):
        a,b=sources()
        a[0]['question']='   '
        a[4]['answer']=None
        a[8]['paragraph']='  '
        t,e,_=prepare(a,b)
        stats=t['material_admission']['train']
        self.assertEqual(stats['invalid_text_passages'],3)
        self.assertEqual(stats['invalid_text_fields'],{'paragraph':1,'question':1,'answer':1})
        self.assertEqual(stats['eligible_passages'],7)
        self.assertEqual(sum(stats['excluded_by_predeclared_structure'].values()),0)
        self.assertTrue(all('train passage 0' not in x['evidence'] and
                            'train passage 1' not in x['evidence'] and
                            'train passage 2' not in x['evidence'] for x in t['rows']))

    def test_source_oversize_only_excludes_ineligible_not_all_evaluation(self):
        a,b=sources()
        a[0]['question']='x'*8193
        b[0]['answer']='x'*4097
        t,e,_=prepare(a,b)
        self.assertEqual(t['material_admission']['train']['invalid_text_fields']['question'],1)
        self.assertEqual(t['material_admission']['validation']['invalid_text_fields']['answer'],1)
        self.assertTrue(validate_panel_bundles(t,e))

    def test_label_blind_to_flips_and_row_permutation_after_exclusion(self):
        a,b=sources()
        a[0]['answer']=''; b[1]['question']=''
        ta,ea,la=prepare(a,b)
        reverse_a=copy.deepcopy(a);reverse_b=copy.deepcopy(b)
        for row in reverse_a+reverse_b:row['label']=1-row['label']
        reverse_a.reverse();reverse_b.reverse()
        tb,eb,lb=prepare(reverse_a,reverse_b)
        self.assertEqual([x['source_group'] for x in ta['rows']],
                         [x['source_group'] for x in tb['rows']])
        self.assertEqual(ea['rows'],eb['rows'])
        self.assertEqual(ta['material_admission'],tb['material_admission'])
        self.assertNotEqual(la['labels'],lb['labels'])

    def test_corrupt_source_labels_and_ids_never_silently_discarded(self):
        for defect in ('bool_label','bad_idx','duplicate_bad_row','untrusted_dict'):
            a,b=sources();a[0]['answer']=''
            if defect=='bool_label':a[0]['label']=True
            if defect=='bad_idx':a[0]['idx']['paragraph']=True
            if defect=='duplicate_bad_row':a.append(copy.deepcopy(a[0]))
            if defect=='untrusted_dict':a[0]['question']={'malformed':True}
            with self.subTest(defect=defect),self.assertRaises(ValueError):
                prepare(a,b)

    def test_selected_passage_cannot_hide_invalid_native_alternative(self):
        a,b=sources()
        b[1]['answer']=''
        t,e,labels=prepare(a,b)
        self.assertTrue(all('val passage 0' not in row['evidence'] for row in e['rows']))
        slate,_=prepare_candidate_slate(t,e,b,original_label_receipt=labels)
        self.assertEqual(len(slate['rows']),4)
        # Inject a missing/empty answer into an actually SELECTED source,
        # which must now fail the candidate-slate integrity check.
        invalid=copy.deepcopy(b)
        chosen=next(row['evidence'] for row in e['rows'])
        entry=next(row for row in invalid if row['paragraph']==chosen)
        entry['answer']=''
        with self.assertRaisesRegex(ValueError,'selected original MultiRC passage'):
            prepare_candidate_slate(t,e,invalid,original_label_receipt=labels)

    def test_future_native_candidate_slate_count_is_preregistered_without_labels(self):
        a,b=sources()
        # One answer only in a question, and nine complete alternatives in
        # another: neither passage may enter training or a heldout native slate.
        a=[r for r in a if not (r['idx']['paragraph']==0 and r['idx']['question']==0 and r['idx']['answer']==1)]
        template=next(r for r in a if r['idx']['paragraph']==1 and r['idx']['question']==1)
        for aid in range(2,9):
            n=copy.deepcopy(template);n['idx']['answer']=aid;n['answer']=f'candidate {aid}'
            a.append(n)
        tr,ev,_=prepare(a,b)
        self.assertEqual(tr['material_admission']['train']['excluded_by_predeclared_structure']['incomplete_native_answer_slate'],2)
        self.assertEqual(tr['material_admission']['train']['eligible_passages'],8)
        self.assertTrue(all('train passage 0' not in row['evidence'] and
                            'train passage 1' not in row['evidence'] for row in tr['rows']))

    def test_exhausted_valid_passage_pool_is_failure_not_success(self):
        a,b=sources()
        for item in a:
            item['answer']=''
        with self.assertRaisesRegex(ValueError,'insufficient eligible'):
            prepare(a,b)

    def test_bad_admission_receipt_is_not_accepted_even_after_resealing(self):
        from next_round_matrix import _digest
        t,e,_=prepare(*sources())
        for name,value in (('raw_passages',0),('invalid_text_passages',True),
                           ('eligible_passages',-1)):
            ta,ev=copy.deepcopy(t),copy.deepcopy(e)
            for panel in (ta,ev):panel['material_admission']['train'][name]=value
            head={k:v for k,v in ta.items() if k not in ('rows','split','panel_id')}
            seal=_digest(dict(header=head,train=ta['rows'],evaluation=ev['rows']))
            ta['panel_id']=ev['panel_id']=seal
            with self.subTest(name=name),self.assertRaises(ValueError):
                validate_panel_bundles(ta,ev)

    def test_non_utf8_size_payload_fails_bounded_guard(self):
        a,b=sources();a[0]['answer']='a'*(1048577)
        with self.assertRaisesRegex(ValueError,'unbounded untrusted'):
            prepare(a,b)

    def test_group_input_one_parameter_incompatible_data_still_fails(self):
        a,_=sources();a[0]['question']=None
        g,stats=_group_inputs(a,'train',return_stats=True)
        self.assertEqual(stats['invalid_text_passages'],1)
        self.assertEqual(len(g),9)
        self.assertEqual(stats['raw_rows'],40)


if __name__=='__main__':
    unittest.main()
