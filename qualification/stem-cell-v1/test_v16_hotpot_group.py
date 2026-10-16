"""Synthetic mechanistic and adversarial tests, NOT a real HotpotQA result."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import v15_hotpot_source as base
import v16_hotpot_group as writer
import v16_hotpot_group_review as reader


def fake_rows():
    rows=[]
    for idx in range(8):
        rows.append(dict(_id=f'unit-row-{idx:02}',
          question='Where did the artist live after the school moved?',
          answer='Aster',type='comparison' if idx%2 else 'bridge',
          level=('easy','medium','hard')[idx%3],
          context=[['Art school', ['The Art school moved to New City.',
                      'A painter from River Hall studied there.',
                      'The artist lived in Aster.',
                      'An unrelated annual parade is well known.']],
                   ['River Hall', ['The River Hall is named for a painter.',
                      'The artist held a class at Art school.',
                      'Their community includes the county.']],
                   ['Another town', ['A train links the city to its neighbors.',
                                     'An unnamed person was there once.']]],
          supporting_facts=[['Art school', 2],['River Hall', 1]]))
    return rows


class GroupExperiment(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory()
        cls.root=Path(cls.tmp.name)
        cls.raw=cls.root/'source.json'
        cls.raw.write_text(json.dumps(fake_rows()),encoding='utf-8')
        with patch.object(base,'N_EXPECTED',8),patch.object(base,'SOURCE_SHA256',hashlib.sha256(cls.raw.read_bytes()).hexdigest()):
            base.source_owner(cls.raw,cls.root/'owned')
        cls.public=cls.root/'owned'/'public.json'
        cls.owner=cls.root/'owned'/'manifest.json'
        cls.gold=cls.root/'owned'/'hidden-restricted.json'
        with patch.object(base,'N_EXPECTED',8):
            cls.plan=writer.make_plan(cls.public,cls.owner,cls.root/'plan.json')
            cls.seal=writer.propose(cls.public,cls.owner,cls.root/'plan.json',cls.root/'seal.json')
            cls.review=reader.audit(cls.public,cls.owner,cls.gold,
                                    cls.root/'plan.json',cls.root/'seal.json',cls.root/'review.json')

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def _mutated_review(self, **changes):
        trial=copy.deepcopy(self.seal)
        trial.update(changes)
        trial['records_sha256']=base.digest(trial['records'])
        with tempfile.TemporaryDirectory() as d, patch.object(base,'N_EXPECTED',8):
            p=Path(d)/'candidate.json';p.write_text(json.dumps(trial))
            return reader.audit(self.public,self.owner,self.gold,
                 self.root/'plan.json',p,Path(d)/'audit.json')

    def test_full_original_fixture_source_and_held_separation(self):
        public=base.load(self.public)
        self.assertEqual(len(public),8)
        self.assertFalse(any('answer' in r or 'supporting_facts' in r for r in public))
        self.assertEqual(self.review['reviewed_questions'],8)
        self.assertEqual(self.review['authority'],'DENY_ALL')
        self.assertFalse(self.review['actual_final_answers_generated'])

    def test_all_eight_policies_and_stable_full_inputs(self):
        self.assertEqual(tuple(self.seal['records'][public['id']]['policies'] for public in base.load(self.public))[0].keys(),
            set(writer.POLICIES))
        for row in base.load(self.public):
            self.assertEqual(self.seal['records'][row['id']],writer.run_one(row))
            self.assertEqual(self.seal['records'][row['id']],reader.replay_one(row))

    def test_same_profile_cannot_claim_ghost_accuracy(self):
        for r in self.seal['records'].values():
            self.assertEqual(r['policies']['ndu_shadow'],r['policies']['ordinary_same_profile'])
        self.assertTrue(self.review['ndu_and_ordinary_same_profile_identical'])

    def test_source_bound_citation_hashes(self):
        for row in base.load(self.public):
            r=self.seal['records'][row['id']]
            mapping={(t,i):s for t,para in row['context'] for i,s in enumerate(para)}
            for p in r['policies'].values():
                self.assertEqual(p['input_sha256'],base.digest([[t,i,mapping[t,i]] for t,i in p['citations']]))
                self.assertIn(p['operations'][-1],('STOP',))
                self.assertEqual(p['citation_slots'],len(p['citations']))

    def test_full_scan_is_charged_even_when_stop_at_two(self):
        for r in self.seal['records'].values():
            self.assertGreater(r['candidate_sentence_count'],5)
            self.assertEqual(r['policies']['bm25_2']['citation_slots'],2)
            self.assertEqual(r['policies']['bm25_5']['citation_slots'],5)
        self.assertEqual(self.review['original_shared_sentence_scans'],
                         self.seal['unique_shared_source_scans'])
        self.assertTrue(self.review['complete_lifecycle_cost_unverified'])

    def test_both_graph_branches_have_explicit_provenance(self):
        for row in base.load(self.public):
            r=writer.run_one(row)
            self.assertEqual(r['policies']['graph_5']['operations'][0], 'BIND')
            self.assertIn(r['policies']['lesion_5']['operations'][1],('NO_OBSERVED_EDGE',))
            self.assertEqual(r['policies']['graph_5'],reader.replay_one(row)['policies']['graph_5'])

    def test_pub_mutation_rejected_before_plan(self):
        bad=base.load(self.public);bad[0]['answer']='publisher secret'
        self.assertRaises(ValueError,writer.run_one,bad[0])
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'leak.json';p.write_text(json.dumps(bad))
            with patch.object(base,'N_EXPECTED',8):
                with self.assertRaises(ValueError):writer.make_plan(p,self.owner,Path(d)/'plan.json')

    def test_changed_hidden_truth_denied(self):
        with tempfile.TemporaryDirectory() as d,patch.object(base,'N_EXPECTED',8):
            secret=base.load(self.gold);first=next(iter(secret))
            secret[first]['supporting_facts']=[['Art school',0]]
            p=Path(d)/'gold.json';p.write_text(json.dumps(secret))
            with self.assertRaises(ValueError):reader.audit(self.public,self.owner,p,
                self.root/'plan.json',self.root/'seal.json',Path(d)/'review.json')

    def test_rehashed_forged_citation_denied_by_replay(self):
        x=copy.deepcopy(self.seal);key=next(iter(x['records']))
        x['records'][key]['policies']['graph_5']['citations'][0]=['Fake',777]
        with self.assertRaises(ValueError): self._mutated_review(records=x['records'])

    def test_rehashed_forged_utility_denied_by_replay(self):
        x=copy.deepcopy(self.seal);key=next(iter(x['records']))
        x['records'][key]['policies']['ndu_shadow']['reward_proxy_units']+=9999
        with self.assertRaises(ValueError): self._mutated_review(records=x['records'])

    def test_false_ndu_or_production_denied(self):
        with self.assertRaises(ValueError):self._mutated_review(no_NDU_FBSDE_solver=False)
        with self.assertRaises(ValueError):self._mutated_review(production_accepted=True)
        with self.assertRaises(ValueError):self._mutated_review(no_pretrained_reader_calls=False)

    def test_partial_corpus_rejected(self):
        x=copy.deepcopy(self.seal);del x['records'][next(iter(x['records']))]
        with self.assertRaises(ValueError):self._mutated_review(records=x['records'])

    def test_source_shares_only_one_rank_calculation_per_question(self):
        self.assertTrue(self.seal['single_shared_rank_calculation_per_question'])
        self.assertEqual(len(self.review['summary']),8)
        self.assertEqual(self.review['summary'][5]['support_recall_macro'],
                         self.review['summary'][6]['support_recall_macro'])

    def test_changed_plan_rejected_before_inference(self):
        data=copy.deepcopy(self.plan);data['tariff_units']=1
        data['plan_sha256']=base.digest({k:v for k,v in data.items() if k!='plan_sha256'})
        with tempfile.TemporaryDirectory() as d,patch.object(base,'N_EXPECTED',8):
            p=Path(d)/'plan.json';p.write_text(json.dumps(data))
            with self.assertRaises(ValueError):writer.propose(self.public,self.owner,p,Path(d)/'sealed.json')

    def test_create_only_seals_prevent_overwrite(self):
        with patch.object(base,'N_EXPECTED',8):
            with self.assertRaises(FileExistsError):writer.propose(
                self.public,self.owner,self.root/'plan.json',self.root/'seal.json')


if __name__=='__main__':unittest.main()
