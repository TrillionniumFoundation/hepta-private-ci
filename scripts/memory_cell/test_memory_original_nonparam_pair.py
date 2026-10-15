"""Original-Git-source negative controls; model-free, retrospective only."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from real_source_reader_probe import canonical, digest, real_source
from memory_original_nonparam_pair import (
    ARMS, QUESTIONS, ROOT_COUNTS, TOPK, code_search_candidates, declaration_in_file,
    locked_plan, plan_for, rank_all, read_docs, score_all, source_graph_candidates,
    bm25_candidates, write_once,
)

# Public ORIGINAL project-link labels (read only by scorer-contract tests).
# The ranking algorithm does not import this table. It is NOT an unseen panel.
PUBLISHED = {
    'py-http-01':('Lib/http/client.py',1397),
    'py-http-02':('Lib/http/client.py',1356),
    'py-http-03':('Lib/http/client.py',1091),
    'sk-base-01':('sklearn/linear_model/_base.py',113),
    'sk-base-02':('sklearn/linear_model/_base.py',223),
    'sk-log-01':('sklearn/linear_model/_logistic.py',236),
    'sk-log-02':('sklearn/linear_model/_logistic.py',782),
    'sk-api-01':('sklearn/utils/_array_api.py',966),
    'sk-api-02':('sklearn/utils/_array_api.py',1010),
    'deno-01':('libs/cache_dir/cache.rs',166),
    'deno-02':('libs/cache_dir/cache.rs',48),
    'deno-03':('libs/cache_dir/cache.rs',203),
}

class NonparamOriginalSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source=os.environ.get('MEMORY_REAL_SOURCE_ZIP')
        reopen=os.environ.get('MEMORY_REOPEN_ZIP')
        if not source or not reopen:
            raise unittest.SkipTest('SHA-verified original source archives required')
        cls.sources=real_source(Path(source),Path(reopen))
        cls.plan=plan_for(cls.sources)
        cls.rows=rank_all(cls.sources,cls.plan)
        cls.docs=read_docs(cls.sources)
        cls.query={x['id']:x for x in cls.plan['registered_queries']}

    def test_original_task_and_source_census(self):
        self.assertEqual(len(QUESTIONS),12)
        self.assertEqual(TOPK,1)
        self.assertEqual(set(self.query),set(PUBLISHED))
        self.assertEqual(len(self.rows['rows']),36)
        self.assertEqual(set(self.rows['rows'][i]['arm'] for i in range(36)),set(ARMS))
        self.assertEqual(set(ROOT_COUNTS),set(x['root'] for x in self.plan['registered_queries']))

    def test_frozen_source_only_plan_digest(self):
        self.assertEqual(digest(canonical(self.plan)+b'\n'), '7cb9d4cd47e4b0230ff746228cf238a72845207746061c94bd5eb80627172fa2')
        self.assertTrue(self.plan['no_model_calls'])
        self.assertFalse(self.plan['labels_present'])
        for x in self.plan['registered_queries']:
            self.assertNotIn('implementation_file',x)
            self.assertNotIn('answer',x)
            self.assertNotIn(PUBLISHED[x['id']][0].encode(),canonical(x))

    def test_rank_receipt_is_original_only_and_locked(self):
        self.assertEqual(digest(canonical(self.rows)+b'\n'), '74968aea04b45c595c8d071ee52ab8dab440c8c44e0d24f3449c0ef432ddd6bd')
        self.assertEqual(self.rows,rank_all(self.sources,self.plan))
        self.assertTrue(self.rows['no_gold_during_ranking'])
        self.assertEqual(self.rows['new_model_calls'],0)
        self.assertFalse(self.rows['production_qualified'])

    def test_one_evidence_slot_per_arm_no_padding(self):
        for row in self.rows['rows']:
            self.assertEqual(len(row['source_paths']),1)
            self.assertEqual(len(row['delivered']),1)
            self.assertEqual(row['evidence_bytes'],len(row['delivered'][0]['excerpt'].encode()))
            self.assertLessEqual(row['evidence_bytes'],480)

    def test_original_blob_byte_identity_for_every_delivered_source(self):
        for row in self.rows['rows']:
            for ev in row['delivered']:
                doc=self.docs[(row['root'],ev['path'])]
                self.assertEqual(ev['source_sha256'],doc['sha256'])
                self.assertEqual(ev['git_blob'],doc['blob'])
                self.assertIn(ev['excerpt'],doc['text'])

    def test_original_declaration_line_sha_bound_and_delivered(self):
        for row in self.rows['rows']:
            target,number=PUBLISHED[row['id']]
            original=self.docs[(row['root'],target)]['text'].splitlines()[number-1]
            if row['source_paths'][0]==target:
                self.assertIn(original,row['delivered'][0]['excerpt'].splitlines(),row['id'])

    def test_lexical_control_not_omitted(self):
        baseline=[row for row in self.rows['rows'] if row['arm']==ARMS[0]]
        self.assertEqual(sum(row['source_paths'][0]==PUBLISHED[row['id']][0] for row in baseline),3)
        self.assertEqual(len(baseline),12)

    def test_symbol_aware_control_is_strong(self):
        strong=[row for row in self.rows['rows'] if row['arm']==ARMS[1]]
        self.assertEqual(sum(row['source_paths'][0]==PUBLISHED[row['id']][0] for row in strong),12)
        self.assertEqual(len(strong),12)

    def test_graph_has_no_source_hit_advantage_over_strong_search(self):
        graph=[row for row in self.rows['rows'] if row['arm']==ARMS[2]]
        self.assertEqual(sum(row['source_paths'][0]==PUBLISHED[row['id']][0] for row in graph),12)
        self.assertEqual(len(graph),12)
        self.assertEqual({x['id']:x['source_paths'] for x in graph},
                         {x['id']:x['source_paths'] for x in self.rows['rows'] if x['arm']==ARMS[1]})

    def test_import_lesion_removes_a_graph_reason_not_code_search(self):
        target=self.query['sk-base-01']; root=target['root']
        lexical=bm25_candidates(target,root,self.docs)
        original=source_graph_candidates(target,root,self.docs,lexical)
        self.assertEqual(original[0],PUBLISHED['sk-base-01'][0])
        broken=copy.deepcopy(self.docs)
        source=broken[(root,target['caller_file'])]
        source['text']=source['text'].replace('from sklearn.linear_model._base import (',
                                               'from nowhere.fake import (')
        # Removing actual import witnesses must never still be counted as a proven edge.
        broken_graph=source_graph_candidates(target,root,broken,lexical)
        self.assertNotEqual(broken_graph[0],original[0])
        strong=code_search_candidates(target,root,broken,lexical)
        self.assertEqual(strong[0],original[0])

    def test_wrong_symbol_is_not_semantic_oracle(self):
        example=self.query['sk-log-02']; root=example['root']
        lexical=bm25_candidates(example,root,self.docs)
        bad=copy.deepcopy(example)
        bad['symbol']='not_a_real_function_293765'
        self.assertEqual(code_search_candidates(bad,root,self.docs,lexical),lexical)

    def test_original_static_label_scoring_and_distinct_unknowns(self):
        data=[]
        for item in self.plan['registered_queries']:
            path,line=PUBLISHED[item['id']]
            orig=self.docs[(item['root'],path)]['text'].splitlines()[line-1]
            data.append(dict(id=item['id'],repository_proxy=item['root'],
                             implementation_file=path,definition_site_sha256=digest(orig.encode())))
        oracle=dict(schema='hepta.memory.original-crossfile-dependency.v1',cases=data)
        with patch.dict(sys.modules,{'memory_original_crossfile_trace':types.SimpleNamespace(audit=lambda _s:oracle)}):
            result=score_all(self.sources,self.plan,self.rows,oracle)
            self.assertEqual(result['arms'][ARMS[0]]['exact_source_hit_at_1'],3)
            for arm in ARMS[1:]:
                self.assertEqual(result['arms'][arm]['exact_source_hit_at_1'],12)
                self.assertEqual(result['arms'][arm]['original_declaration_line_delivered'],12)
            self.assertEqual(result['paired_against_lexical'][ARMS[1]]['gained'],9)
            self.assertEqual(result['paired_against_lexical'][ARMS[2]]['gained'],9)
            self.assertIsNone(result['end_to_end_task_success'])
            self.assertIsNone(result['complete_lifecycle_tco'])
            fake=copy.deepcopy(self.rows)
            fake['rows'][0]['source_paths'][0]='fabricated.py'
            with self.assertRaisesRegex(ValueError,'altered or self-scored'):
                score_all(self.sources,self.plan,fake,oracle)
            with self.assertRaisesRegex(ValueError,'original static oracle'):
                score_all(self.sources,self.plan,self.rows,dict(schema='fake',cases=data))

    def test_preexposure_freeze_no_rewrite(self):
        with tempfile.TemporaryDirectory() as td:
            f=Path(td)/'plan.json'
            write_once(f,canonical(self.plan)+b'\n')
            self.assertEqual(canonical(locked_plan(self.sources,f,digest(f.read_bytes()))),canonical(self.plan))
            with self.assertRaisesRegex(ValueError,'must not exist'):
                write_once(f,b'override')
            with self.assertRaisesRegex(ValueError,'changed'):
                locked_plan(self.sources,f,'0'*64)

    def test_registered_caller_or_file_tamper_refused(self):
        changed=copy.deepcopy(self.plan)
        changed['registered_queries'][0]['caller_file']='attacker/changed.py'
        with tempfile.TemporaryDirectory() as td:
            f=Path(td)/'p.json'
            f.write_bytes(canonical(changed)+b'\n')
            with self.assertRaisesRegex(ValueError,'pre-scoring plan changed'):
                locked_plan(self.sources,f,digest(f.read_bytes()))

if __name__=='__main__':
    unittest.main()
