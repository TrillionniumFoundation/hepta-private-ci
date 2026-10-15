"""Adversarial source-only retrieval and post-seal scoring tests (NO-GO)."""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import amcn_original_full_family_retrieval as study
from amcn_original_locomo_trial import bm25, sealed_write
from amcn_original_text_reader import file_sha

ROOT = Path(os.environ.get('HEPTA_AMCN_ORIGINAL_ROOT','/path/to/pinned-original'))
STUDY = Path(os.environ.get('HEPTA_AMCN_FULL_RETRIEVAL_ROOT','/path/to/frozen-source'))
PUBLIC = STUDY / 'public-sources-only.json'
WITHHELD = STUDY / 'withheld-publisher-weak-labels.json'


class OriginalFullFamilyStudyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not PUBLIC.is_file() or not WITHHELD.is_file() or not (ROOT/'locomo.json').is_file():
            raise unittest.SkipTest('original SHA-pinned LoCoMo material not mounted')
        cls.p=json.loads(PUBLIC.read_bytes())

    def test_exact_original_ten_families_two_process_boundaries(self):
        self.assertEqual(len(self.p['source_families']),10)
        self.assertEqual(len(self.p['cases']),1986)
        self.assertEqual(sum(len(a) for a in self.p['source_families'].values()),5882)
        self.assertEqual(self.p['publisher_targets_not_included'],True)
        self.assertFalse(self.p['production_accepted'])
        self.assertEqual(self.p['calendar_future_windows'],0)
        self.assertNotIn('publisher_support',PUBLIC.read_text())
        self.assertNotIn('publisher_answer',PUBLIC.read_text())
        self.assertEqual(file_sha(ROOT/'locomo.json'),study.CORPUS_SHA256)

    def test_original_bm25_top16_invariant_every_family(self):
        for fam,src in self.p['source_families'].items():
            idx=study.SourceFirstBM25Index(src)
            questions=[x['question'] for x in self.p['cases'] if x['family']==fam]
            for q in questions[:5]:
                self.assertEqual(idx.rank(q)[:16],
                                 [x['id'] for x in bm25(q,src)[:16]])

    def test_composite_weak_support_is_separately_recorded(self):
        support,unresolved=study.split_publisher_support(['D8:6; D9:17','D30:05'])
        self.assertEqual(support,['D30:5','D8:6','D9:17'])
        self.assertEqual(unresolved,[])
        support,unresolved=study.split_publisher_support(['not a dialogue reference'])
        self.assertEqual(support,[])
        self.assertEqual(unresolved,['not a dialogue reference'])

    def test_invalid_support_cannot_be_relabelled(self):
        for data in ('D1:9',{'abc':'D1:9'},[None]):
            with self.assertRaises(ValueError):
                study.split_publisher_support(data)

    def test_rank_gold_smuggling_refused_before_original_encoder(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            altered=json.loads(PUBLIC.read_bytes())
            altered['cases'][0]['publisher_answer']='hidden'
            inp=root/'gold-smuggled.json'
            sealed_write(inp,altered)
            with patch.object(study,'OriginalMiniLMBert') as model:
                with self.assertRaisesRegex(ValueError,'gold-bearing'):
                    study.rank(inp,file_sha(inp),ROOT/'encoder',root/'result.json')
                model.assert_not_called()

    def test_rank_rejects_changed_external_source_sha(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(study,'OriginalMiniLMBert') as model:
                with self.assertRaisesRegex(ValueError,'external exact source SHA'):
                    study.rank(PUBLIC,'0'*64,ROOT/'encoder',Path(tmp)/'no.json')
                model.assert_not_called()

    def test_rank_cannot_overwrite_immutable_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'result.json';path.write_text('{}')
            with patch.object(study,'OriginalMiniLMBert') as model:
                with self.assertRaisesRegex(ValueError,'create-only'):
                    study.rank(PUBLIC,file_sha(PUBLIC),ROOT/'encoder',path)
                model.assert_not_called()

    def test_original_evidence_roots_are_disjoint_and_all_stages_fail_closed(self):
        self.assertEqual(set(study.SPLITS),set(self.p['source_families']))
        for fam, rows in self.p['source_families'].items():
            self.assertTrue(all(x['root']==fam for x in rows))
        holdout={f for f,s in study.SPLITS.items() if s.startswith('retrospective_heldout')}
        self.assertEqual(holdout,{'conv-49','conv-50'})
        self.assertNotIn('official_hf_parity_proven',self.p)

    def test_postseal_score_binds_to_exact_rank_and_withheld_sha(self):
        ranked=STUDY / 'ten-family-real-original-minilm-rank.json'
        if not ranked.is_file():self.skipTest('physical all-family ranking not yet sealed')
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'score.json'
            with self.assertRaisesRegex(ValueError,'external exact source SHA'):
                study.score(PUBLIC,file_sha(PUBLIC),ranked,file_sha(ranked),
                            WITHHELD,'0'*64,out)
            self.assertFalse(out.exists())


if __name__=='__main__':unittest.main()
