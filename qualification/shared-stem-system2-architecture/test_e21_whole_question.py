"""E21 independent source-locked adversarial and question-metric tests.

Actual authentic E15 model predictions are required; fake labels in this test
are explicitly SYNTHETIC and NEVER a real human task success claim.
"""
import copy
import hashlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import e21_whole_question as e


def real_files():
    original=os.environ.get('HEPTA_E21_SOURCE')
    folds=[os.environ.get(f'HEPTA_E21_FOLD_{i}') for i in range(4)]
    scores=[os.environ.get('HEPTA_E21_SCORE_SOURCE'),os.environ.get('HEPTA_E21_SCORE_MERGE')]
    if not original or any(not v for v in folds+scores):
        raise ValueError('E21 requires original hosted source and all six original E15 ZIPs: no synthetic fallback')
    for f in [original]+folds+scores:
        if not Path(f).is_file():raise ValueError('missing actual E15 original ZIP')
    return original,folds,scores


class OriginalResearchEvidence(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original,cls.folds,cls.scores=real_files()
        cls.blind=e.load_blind_source(cls.original,cls.folds)

    def test_original_full_census(self):
        b=self.blind
        self.assertEqual((b['source_group_count'],b['question_count'],b['candidate_count']),(4,8,33))
        self.assertEqual(sum(r['original_v1_candidate'] for r in b['rows']),8)
        self.assertFalse(b['held_human_labels_opened'])
        self.assertFalse(b['production_accepted'])
        self.assertEqual(b['real_pretrained_forwards_new'],0)

    def test_six_real_model_options_and_no_labels(self):
        self.assertEqual(set(self.blind['rows'][0]['probs']),set(e.ALL))
        self.assertFalse(any('label' in r or 'human' in r for r in self.blind['rows']))
        for row in self.blind['rows']:
            self.assertTrue(all(0<p<1 for p in row['probs'].values()))

    def test_original_group_and_question_counts(self):
        groups={r['source_group'] for r in self.blind['rows']}
        q={(r['source_group'],r['question_slot']) for r in self.blind['rows']}
        self.assertEqual(len(groups),4)
        self.assertEqual(len(q),8)
        self.assertEqual(sorted(len([r for r in self.blind['rows'] if r['source_group']==g]) for g in groups),[6,8,9,10])

    def test_true_original_noquery_invariance(self):
        questions={}
        for r in self.blind['rows']:
            questions.setdefault((r['source_group'],r['question_slot']),[]).append(r['probs']['no_query'])
        self.assertEqual(len(questions),8)
        self.assertTrue(all(len(set(x))==1 for x in questions.values()))

    def test_two_independent_human_score_artifacts_agree(self):
        ss=[]
        for path,(_,sha,_) in zip(self.scores,e.E15_SCORES):
            rec=e._scores_zip(path,sha)
            self.assertFalse(rec['production_accepted'])
            self.assertFalse(rec['independent_future_generations_established'])
            ss.append(rec['summary'])
        for arm in e.ALL:
            self.assertEqual(ss[0][arm]['correct'],ss[1][arm]['correct'])
            self.assertEqual(ss[0][arm]['brier'],ss[1][arm]['brier'])
        self.assertEqual(ss[0]['learned_linear_5']['correct'],17)
        self.assertEqual(ss[0]['mean_pool_query_fused']['correct'],17)
        self.assertEqual(ss[0]['learned_gated_3']['correct'],16)

    def test_prior_real_human_group_delta_is_balanced(self):
        s=e._scores_zip(self.scores[0],e.E15_SCORES[0][1])['summary']
        linear=s['learned_linear_5']['passage_correct']
        pool=s['mean_pool_query_fused']['passage_correct']
        self.assertEqual([linear[g]-pool[g] for g in sorted(linear)],[2,0,0,-2])
        self.assertGreater(s['mean_pool_query_fused']['brier'],s['learned_linear_5']['brier'])

    def test_wrong_model_source_zip_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'wrong.zip'
            p.write_bytes(Path(self.original).read_bytes()+b'x')
            with self.assertRaises(ValueError):e.load_blind_source(p,self.folds)

    def test_wrong_fold_zip_rejected(self):
        bad=self.folds[:];bad[1]=self.folds[0]
        with self.assertRaises(ValueError):e.load_blind_source(self.original,bad)

    def test_missing_fold_rejected(self):
        with self.assertRaises(ValueError):e.load_blind_source(self.original,self.folds[:3])

    def test_false_promotion_flags_rejected(self):
        b=copy.deepcopy(self.blind);b['production_accepted']=True
        with self.assertRaises(ValueError):e.score_from_labels(b,{})
        b=copy.deepcopy(self.blind);b['real_pretrained_forwards_new']=False
        with self.assertRaises(ValueError):e.score_from_labels(b,{})
        b=copy.deepcopy(self.blind);b['unknown_production_authorizer']=True
        with self.assertRaises(ValueError):e.score_from_labels(b,{})

    def test_original_producer_no_scored_zip_member_read(self):
        seen=[]
        orig=e.ZipFile
        class WatchingZip(orig):
            def read(self,name,*args,**kw):
                seen.append(name)
                if 'scores' in name or 'owner-label' in name:
                    raise AssertionError('scorer/labels must not enter blind stage')
                return super().read(name,*args,**kw)
        with patch.object(e,'ZipFile',WatchingZip):
            self.assertEqual(len(e.load_blind_source(self.original,self.folds)['rows']),33)
        self.assertTrue(seen)

    def test_synthetic_question_metrics_not_real_human_gain(self):
        question_index={}
        labels={}
        for row in self.blind['rows']:
            key=(row['source_group'],row['question_slot'])
            index=question_index.get(key,0)
            labels[row['task_id']]=index%2  # SYNTHETIC LABELS FOR CONTRACT TEST ONLY
            question_index[key]=index+1
        result=e.score_from_labels(self.blind,labels)
        self.assertEqual(len(question_index),8)
        self.assertTrue(all(count>=2 for count in question_index.values()))
        for x in result.values():
            self.assertEqual(x['total'],33)
            self.assertLessEqual(x['complete_question_count'],8)
            self.assertLessEqual(x['complete_passage_count'],4)

    def test_incomplete_or_invalid_labels_rejected(self):
        lab={r['task_id']:0 for r in self.blind['rows']}
        with self.assertRaises(ValueError):e.score_from_labels(self.blind,lab)
        lab.pop(next(iter(lab)))
        with self.assertRaises(ValueError):e.score_from_labels(self.blind,lab)

    def test_fake_probability_and_missing_candidate_rejected(self):
        b=copy.deepcopy(self.blind)
        b['rows'][0]['probs']['learned_linear_5']=float('nan')
        fake={r['task_id']:i%2 for i,r in enumerate(b['rows'])}
        with self.assertRaises(ValueError):e.score_from_labels(b,fake)
        b=copy.deepcopy(self.blind);b['rows'].pop()
        with self.assertRaises(ValueError):e.score_from_labels(b,fake)

    def test_exact_four_cluster_signflip(self):
        self.assertEqual(e.signflip_p([2,0,0,-2]),1.0)
        self.assertGreaterEqual(e.signflip_p([1,1,1,1]),1/8)
        for invalid in ([2,3],[float('nan')]*4,[1,2,3,True]):
            with self.assertRaises(ValueError):e.signflip_p(invalid)

    def test_aggregate_rejects_synthetic_label_masquerade(self):
        # Fake synthetic labels cannot be passed off as original human labels:
        labels={r['task_id']:i%2 for i,r in enumerate(self.blind['rows'])}
        # Force mixed labels on each question, to reach actual independent comparator.
        indices={}
        for row in self.blind['rows']:
            key=(row['source_group'],row['question_slot'])
            count=indices.get(key,0);labels[row['task_id']]=count%2;indices[key]=count+1
        with self.assertRaises(ValueError):e.evaluate(self.blind,labels,*self.scores)

    def test_source_and_merge_head_identity(self):
        for p,(_,expected_sha,expected_head) in zip(self.scores,e.E15_SCORES):
            self.assertEqual(e._sha(Path(p).read_bytes()),expected_sha)
            self.assertEqual(e._zip(p,expected_sha,('source-head.txt',))['source-head.txt'].decode().strip(),expected_head)

    def test_write_once_fails_closed(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'new.json'
            h=e.once(p,{'authority':'DENY_ALL'})
            self.assertEqual(h,hashlib.sha256(p.read_bytes()).hexdigest())
            with self.assertRaises(FileExistsError):e.once(p,{'authority':'DENY_ALL'})


if __name__=='__main__':unittest.main()
