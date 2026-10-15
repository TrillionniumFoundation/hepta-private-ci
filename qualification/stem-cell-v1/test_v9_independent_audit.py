"""Synthetic fail-closed V9 independent auditor regression suite.

No public model files, evidence labels or task success implied by passing these.
"""
from pathlib import Path
import copy
import json
import tempfile
import unittest

from stem_v9_original_continual import HELD, OLD, NEW, SCHEMA, jbytes
from v9_independent_original_audit import (
    ORIGINAL_CORPUS_SHA, SHA_PRODUCER, check_documents,
    hash_path, independent_publisher_recount, require, safe_tree,
)


class AuditSourceTests(unittest.TestCase):
    def test_pin_exact_original_producer_digest(self):
        self.assertEqual(len(SHA_PRODUCER), 64)
        self.assertEqual(len(ORIGINAL_CORPUS_SHA), 64)

    def test_safe_tree_refuses_missing_inventory(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):
                safe_tree(d)

    def test_safe_tree_refuses_extra_files(self):
        with tempfile.TemporaryDirectory() as d:
            for f in ('source-only.json','train-only-labels.json','precommit.json',
                      'original-predictions.json','private-vectors.npy',
                      'physical-receipt.json','postseal-weak-score.json'):
                (Path(d)/f).write_bytes(b'x')
            self.assertEqual(safe_tree(d),Path(d))
            (Path(d)/'hidden-gold.json').write_text('null')
            with self.assertRaises(ValueError):
                safe_tree(d)

    def test_safe_tree_refuses_aliases(self):
        with tempfile.TemporaryDirectory() as d:
            for f in ('source-only.json','train-only-labels.json','precommit.json',
                      'original-predictions.json','private-vectors.npy',
                      'physical-receipt.json','postseal-weak-score.json'):
                (Path(d)/f).write_bytes(b'1')
            (Path(d)/'private-vectors.npy').unlink()
            (Path(d)/'private-vectors.npy').symlink_to('source-only.json')
            with self.assertRaises(ValueError):
                safe_tree(d)

    def test_independent_publisher_score_requires_exact_families(self):
        with tempfile.TemporaryDirectory() as d:
            # Only HELD is consumed by independent score; artificial source
            # documents and labels are not original task evidence.
            raw = []
            source = {"families": {}}
            predictions = {"rankings": {}}
            per = {}
            for fam in HELD:
                ids = ["D1:1", "D1:2", "D1:3"]
                source["families"][fam] = {"passages": [{"id": v} for v in ids],
                                           "questions": [{"id": f"{fam}/q0"}]}
                raw.append({"sample_id": fam, "qa": [{"evidence": ["D1:1"]}]})
                predictions["rankings"][f"{fam}/q0"]={"bm25_full": ["D1:1","D1:2","D1:3"]}
                per[fam] = {"total_questions":1,"weak_supported":1,
                            "unknown_annotation":0,"any_support_top3":1,"all_support_top3":1}
            path=Path(d)/'mock.json';path.write_bytes(jbytes(raw))
            post={"per_arm_source_root_aggregates":{"bm25_full":per}}
            self.assertEqual(independent_publisher_recount(path,source,predictions,post),4)

    def test_independent_score_rejects_forged_gain(self):
        with tempfile.TemporaryDirectory() as d:
            raw=[];source={"families":{}};pred={"rankings":{}};data={}
            for fam in HELD:
                source["families"][fam] = {"passages":[{"id":i} for i in ("S1","S2","S3")],"questions":[{"id":fam+"/q0"}]}
                raw.append({"sample_id":fam,"qa":[{"evidence":["S1"]}]})
                pred["rankings"][fam+"/q0"]={"bm25_full":["S2","S3","S1"]}
                data[fam]={"total_questions":1,"weak_supported":1,"unknown_annotation":0,"any_support_top3":1,"all_support_top3":1}
            path=Path(d)/'mock.json';path.write_bytes(jbytes(raw))
            post={"per_arm_source_root_aggregates":{"bm25_full":data}}
            self.assertEqual(independent_publisher_recount(path,source,pred,post),4)
            post["per_arm_source_root_aggregates"]["bm25_full"][HELD[0]]["any_support_top3"]=0
            with self.assertRaises(ValueError):
                independent_publisher_recount(path,source,pred,post)

    def test_requirement_survives_python_optimized_mode(self):
        with self.assertRaises(ValueError):
            require(False,"must fail even with -O")

    def test_check_documents_denies_fake_results(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):
                check_documents(Path(d),{"schema":SCHEMA+".source-only",
                          "source_contains_publisher_gold": True}, {}, {}, {}, {}, {})

    def test_hash_is_real_file_bytes(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'test';path.write_bytes(b'abc')
            self.assertEqual(hash_path(path),
                             'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad')
            path.write_bytes(b'abC')
            self.assertNotEqual(hash_path(path),
                                'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad')


if __name__ == '__main__':
    unittest.main()
