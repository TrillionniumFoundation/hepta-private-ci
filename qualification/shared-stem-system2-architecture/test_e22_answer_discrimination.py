"""E22 source-only arithmetic and falsification tests; all labels are SYNTHETIC.

The real hosted workflow, not these fixtures, will consume original E21 pretrained
ZIPs and independently opened actual MultiRC human validation labels.
"""
from __future__ import annotations

import copy
import json
import tempfile
import unittest
from collections import defaultdict
from pathlib import Path

import e22_answer_discrimination as e


def case():
    rows=[]; labels={}
    for g in range(4):
        for q in range(2):
            count=5 if (g,q)==(3,1) else 4
            # Need 33 original candidate alternatives: 7 x 4 plus 1 x 5.
            for a in range(count):
                tid=f'{g}-{q}-{a}'; y=a % 2; labels[tid]=y
                prob={
                    'no_query':.61 if q else .39,
                    'conditioned':.505+(a%2)*.0001,
                    'mean_pool_query_fused':.30+.1*a,
                    'no_evidence':.49+.015*a,
                    'learned_linear_5':.24+.15*a,
                    'learned_gated_3':.60-.08*a,
                }
                rows.append({'task_id':tid,'source_group':f'passage-{g}',
                             'question_slot':q,'candidate_id':a,
                             'original_v1_candidate':a==0,'probs':prob})
    blind={'schema':e.BLIND_INPUT,'authority':'DENY_ALL',
           'production_accepted':False,'source_archive_sha256':e.SOURCE_SHA,
           'e15_head':e.E15_HEAD,'real_pretrained_forwards_new':0,
           'held_human_labels_opened':False,'source_group_count':4,
           'question_count':8,'candidate_count':33,'rows':rows}
    raw=(json.dumps(blind,sort_keys=True,separators=(',',':'))+'\n').encode()
    return blind,raw,labels


def independent_e21_review(blind, labels):
    # Independent simple arithmetic implementation of the inherited E21
    # summary shape, used only for synthetic contract tests.
    methods={}
    for arm in e.ALL:
        correct=0;sum_brier=0.; per=defaultdict(int);counts=defaultdict(int)
        hits_by_question=defaultdict(list);hits_by_passage=defaultdict(list)
        for row in blind['rows']:
            p=row['probs'][arm];y=labels[row['task_id']]
            yhat=int(p>=.5) if arm in e.LEARNED else int(p>.5)
            hit=int(yhat==y)
            correct+=hit;sum_brier+=2*(p-y)**2
            per[row['source_group']]+=hit
            counts[row['source_group']]+=1
            hits_by_question[(row['source_group'],row['question_slot'])].append(hit)
            hits_by_passage[row['source_group']].append(hit)
        methods[arm]={'correct':correct,'total':33,'brier':sum_brier/33,
                      'passage_correct':dict(sorted(per.items())),
                      'passage_total':dict(sorted(counts.items())),
                      'complete_question_count':sum(all(v) for v in hits_by_question.values()),
                      'complete_passage_count':sum(all(v) for v in hits_by_passage.values())}
    return {'schema':e.E21_SCORE,'authority':'DENY_ALL','production_accepted':False,
            'human_score_source_head_and_synthetic_merge_reconciled':True,
            'original_source_and_merge_scores_reconciled':True,
            'source_original_human_labels_sha256':e.VAL_SHA,
            'model_selected':False,'fbsde_reactivation_allowed':False,
            'original_human_passage_groups':4,'candidate_count':33,
            'original_question_count':8,'method_results':methods}


class TestE22SourceOnly(unittest.TestCase):
    def setUp(self):
        self.blind,self.raw,self.labels=case()
        self.summary=e.blind_audit(self.blind,self.raw)
        self.e21=independent_e21_review(self.blind,self.labels)

    def test_unlabeled_audit_original_census(self):
        x=self.summary
        self.assertEqual((x['original_passage_count'],x['original_question_count'],
                          x['original_candidate_count']),(4,8,33))
        self.assertEqual(x['original_reader_arms'],list(e.ALL))
        self.assertEqual(x['e21_blind_sha256'],e.sha256(self.raw))
        self.assertFalse(x['human_labels_opened'])
        self.assertFalse(x['reader_sufficiency_certified'])
        self.assertFalse(x['ndu_system2_admitted'])

    def test_noquery_is_exactly_invariant_on_mixed_human_questions(self):
        x=e.adjudicate(self.blind,self.raw,self.summary,self.labels,self.e21)
        ctrl=x['arm_results']['no_query']
        self.assertEqual(ctrl['constant_score_question_count'],8)
        self.assertEqual(ctrl['constant_hard_class_question_count'],8)
        self.assertEqual(ctrl['complete_question_count'],0)
        self.assertEqual(ctrl['positive_negative_pair_total'],
                         ctrl['positive_negative_pair_exact_tied'])
        self.assertEqual(x['no_query_mixed_question_complete_success_upper_bound'],0)
        self.assertFalse(x['answer_information_support_for_full_ndu_system2'])

    def test_question_pair_ranking_counts_partition_exactly(self):
        x=e.adjudicate(self.blind,self.raw,self.summary,self.labels,self.e21)
        for arm,outcome in x['arm_results'].items():
            self.assertEqual(outcome['positive_negative_pair_total'],
                             sum(outcome[k] for k in (
                                 'positive_negative_pair_concordant',
                                 'positive_negative_pair_discordant',
                                 'positive_negative_pair_exact_tied')))
            self.assertEqual(len(outcome['per_question']),8)
            self.assertLessEqual(outcome['complete_passage_count'],4)
            self.assertLessEqual(outcome['complete_question_count'],8)

    def test_e21_original_score_parity_is_required(self):
        for edit in ('correct','brier','complete_question_count','passage_correct'):
            bad=copy.deepcopy(self.e21)
            m=bad['method_results']['conditioned']
            if edit=='passage_correct':m[edit]['passage-0']+=1
            elif edit=='brier':m[edit]+=.25
            else:m[edit]+=1
            with self.subTest(edit=edit),self.assertRaises(e.EvidenceDenied):
                e.adjudicate(self.blind,self.raw,self.summary,self.labels,bad)

    def test_source_sha_forgery_and_fake_promotion_rejected(self):
        for field,value in (('source_archive_sha256','f'*64),
                            ('production_accepted',True),
                            ('held_human_labels_opened',True),
                            ('real_pretrained_forwards_new',False)):
            b=copy.deepcopy(self.blind);b[field]=value
            with self.subTest(field=field),self.assertRaises(e.EvidenceDenied):
                e.blind_audit(b,self.raw)

    def test_label_bearing_blind_field_and_missing_candidate_denied(self):
        for edit in ('extra','missing','relabel','duplicate'):
            b=copy.deepcopy(self.blind)
            if edit=='extra':b['rows'][0]['true_label']=1
            elif edit=='missing':b['rows'].pop()
            elif edit=='relabel':b['rows'][0]['task_id']=''
            else:b['rows'][0]['task_id']=b['rows'][1]['task_id']
            with self.subTest(edit=edit),self.assertRaises(e.EvidenceDenied):
                e.blind_audit(b,self.raw)

    def test_perturbed_postseal_raw_or_blind_summary_denied(self):
        wrong=copy.deepcopy(self.summary);wrong['e21_blind_sha256']='a'*64
        with self.assertRaises(e.EvidenceDenied):
            e.adjudicate(self.blind,self.raw,wrong,self.labels,self.e21)
        changed=copy.deepcopy(self.blind)
        changed['rows'][1]['probs']['conditioned']+=.1
        with self.assertRaises(e.EvidenceDenied):
            e.adjudicate(changed,self.raw,self.summary,self.labels,self.e21)

    def test_wrong_human_truth_or_e21_score_metadata_denied(self):
        wrong=dict(self.labels);wrong.pop(next(iter(wrong)))
        with self.assertRaises(e.EvidenceDenied):
            e.adjudicate(self.blind,self.raw,self.summary,wrong,self.e21)
        wrong=dict(self.labels);wrong[next(iter(wrong))]=True
        with self.assertRaises(e.EvidenceDenied):
            e.adjudicate(self.blind,self.raw,self.summary,wrong,self.e21)
        wrong=copy.deepcopy(self.e21);wrong['fbsde_reactivation_allowed']=True
        with self.assertRaises(e.EvidenceDenied):
            e.adjudicate(self.blind,self.raw,self.summary,self.labels,wrong)

    def test_float_tie_semantics_match_E21(self):
        self.assertEqual(e.hard_class('conditioned',.5),0)
        self.assertEqual(e.hard_class('learned_linear_5',.5),1)
        self.assertTrue(self.summary['question_information'][0]['arms']['no_query']
                        ['exact_constant_score'])

    def test_strict_json_duplicate_and_nan_rejected(self):
        for raw in (b'{"a":1,"a":2}',b'{"a":NaN}',b'{"a":Infinity}'):
            with self.subTest(raw=raw),self.assertRaises(e.EvidenceDenied):
                e.strict_json(raw)

    def test_emit_once_prevents_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'sealed.json'
            digest=e.emit_once(path,self.summary)
            self.assertEqual(digest,e.sha256(path.read_bytes()))
            with self.assertRaises(FileExistsError):
                e.emit_once(path,self.summary)

    def test_report_cannot_claim_model_selection_or_real_efficacy(self):
        x=e.adjudicate(self.blind,self.raw,self.summary,self.labels,self.e21)
        for k in ('model_selected','production_accepted','answer_information_support_for_full_ndu_system2'):
            self.assertIs(x[k],False)
        self.assertEqual(x['new_pretrained_forward_calls'],0)
        self.assertEqual(x['new_trained_parameters'],0)
        self.assertEqual(x['new_future_source_families'],0)


if __name__ == '__main__':
    unittest.main()
