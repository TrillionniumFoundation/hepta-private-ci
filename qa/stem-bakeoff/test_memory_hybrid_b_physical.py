"""Strict contract and synthetic original-weight-port tests; NEVER a real-model result."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

import memory_hybrid_b_physical as h
from memory_retrieval_data import Corpus, Gold, Query, Turn


def census():
    corpus, queries, gold = {}, [], {}
    # Exactly the historical heldout shape, but these are fake local fixtures.
    n = [224, 200, 210, 210, 250, 237]
    assert sum(n) == 1331
    for group, count in zip(h.EVALUATION, n):
        corpus[group] = Corpus(group, (
            Turn("D1:1", "session_1", 0, "Ada", "3 May 2023", "I planted the oak on Tuesday.", False),
            Turn("D1:2", "session_1", 1, "Ben", "3 May 2023", "The oak was in the park.", False),
        ))
        for i in range(count):
            qid = f"{group}:qa:{i:04d}"
            queries.append(Query(qid, group, "When was oak planted?"))
            gold[qid] = Gold(2, ("D1:1",), (), False)
    return corpus, tuple(queries), gold


class TinyFakeOriginal:
    """For fixture mechanism tests only; never used for actual qualification."""

    def __init__(self, *_):
        self.dense_calls = 0
        self.rerank_calls = 0
        self.dense_files = []
        self.rerank_files = []

    def encode(self, texts):
        self.dense_calls += 1
        return np.array([[1., 0.] for _ in texts], dtype=np.float32)

    def score(self, q, docs):
        self.rerank_calls += 1
        return list(range(len(docs)))


class HybridBTests(unittest.TestCase):
    def test_source_only_projection_omits_every_gold_field(self):
        corpora, queries, _ = census()
        w = h._project(corpora, queries)
        blob = json.dumps(w)
        self.assertEqual(len(h._input_corpus(w)[1]), 1331)
        for forbidden in ('"answer"', '"evidence"', '"category"', '"observation"'):
            self.assertNotIn(forbidden, blob)
        w['groups'][0]['queries'][0]['gold_answer'] = 'Tuesday'
        with self.assertRaisesRegex(h.HybridError, 'source-only query fields'):
            h._input_corpus(w)

    def test_rrf_pool_deduplicates_and_ties_by_source_index(self):
        self.assertEqual(h._rrf_pool([0, 1], [1, 0]), [0, 1])
        self.assertEqual(h._rrf_pool([2], [1]), [1, 2])
        with self.assertRaisesRegex(h.HybridError, 'nonfinite'):
            h._ordered_rerank([0, 1], [float('nan'), 1])

    def test_local_model_pin_rejects_symlink_and_missing_safetensors(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / 'config.json').write_text('{}')
            with self.assertRaisesRegex(h.HybridError, 'safetensors'):
                h.hash_tree(root)
            (root / 'model.safetensors').write_bytes(b'fixture-not-weights')
            digest, inventory = h.hash_tree(root)
            self.assertEqual(len(digest), 64)
            self.assertEqual(len(inventory), 2)
            (root / 'link').symlink_to(root / 'config.json')
            with self.assertRaisesRegex(h.HybridError, 'symlink'):
                h.hash_tree(root)

    def _fixture_execution(self):
        corpora, queries, gold = census()
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            worker = root/'worker.json'; manifest = root/'manifest.json'; pred = root/'predictions.jsonl'
            w = h._project(corpora, queries)
            worker.write_bytes(h.canonical(w))
            manifest.write_bytes(h.canonical({
                'schema':h.SCHEMA+'.manifest','source_sha256':h.SOURCE_SHA,
                'projected_input_sha256':h.sha(h.canonical(w)),
                'arms':['A_FTS5','B_FTS5_DENSE_RERANK'],
                'dense_revision':h.DENSE_REV, 'reranker_revision':h.RERANK_REV}))
            with patch.object(h, 'OriginalTransformers', TinyFakeOriginal):
                result=h.physical_run(worker, manifest, '.', '.', 'f'*64, 'e'*64, pred)
            self.assertEqual(result['prediction_rows'],2662)
            with patch.object(h, 'load_source', return_value=(corpora, queries, gold)):
                report=h.audit(root/'source-not-actually-read.json', worker, manifest, pred)
            self.assertFalse(report['science_superiority_established'])
            self.assertEqual(report['query_arm_rows_verified'],2662)
            rows=pred.read_text().splitlines()
            sample=json.loads(rows[1])
            self.assertGreater(sample['reranker_forwards'],0)
            sample['reranker_pairs']=0
            rows[1]=json.dumps(sample)
            pred.write_text('\n'.join(rows)+'\n')
            with patch.object(h, 'load_source', return_value=(corpora, queries, gold)):
                with self.assertRaisesRegex(h.HybridError, 'skipped physical'):
                    h.audit(root/'source-not-actually-read.json', worker, manifest, pred)

    def test_real_sqlite_bm25_plus_synthetic_neural_port_and_audit(self):
        self._fixture_execution()

    def test_absent_or_gold_poisoned_worker_rejects_before_neural_execution(self):
        corpora, queries, gold = census()
        w=h._project(corpora,queries)
        del w['groups'][-1]['queries'][-1]
        with self.assertRaisesRegex(h.HybridError,'complete'):
            h._input_corpus(w)
        w=h._project(corpora,queries)
        w['groups'][0]['turns'][0]['category']=2
        with self.assertRaisesRegex(h.HybridError,'turn provenance'):
            h._input_corpus(w)

if __name__=='__main__':unittest.main()
