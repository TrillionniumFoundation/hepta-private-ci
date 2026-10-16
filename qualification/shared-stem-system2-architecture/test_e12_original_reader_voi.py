"""Actual original pretrained ZIP-backed and adversarial tests, no synthetic efficacy."""
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import e12_original_reader_voi as blind
import e12_original_reader_review as judge


class OriginalReaderVOITest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        names = ("HEPTA_VOI_GRANITE", "HEPTA_VOI_MMBERT", "HEPTA_VOI_MULTIRC",
                 "HEPTA_VOI_PHYSICAL_ZIP", "HEPTA_VOI_LABEL_ZIP", "HEPTA_VOI_MULTIRC_ZIP")
        paths = [os.environ.get(n) for n in names]
        if any(not s or not Path(s).is_file() for s in paths):
            raise RuntimeError("six exact ORIGINAL sources are mandatory; NO SKIP/fixture replacement")
        cls.granite, cls.mmbert, cls.multirc, cls.physical_zip, cls.label_zip, cls.multirc_zip = paths
        cls.source = [blind.read_source(p, key) for p, key in zip(paths, ("granite", "mmbert", "multirc"))]

    def _blind(self, output):
        return blind.produce(self.granite, self.mmbert, self.multirc, output)

    def _two(self, temp):
        prelabel = str(Path(temp) / "prelabel.json")
        sha = self._blind(prelabel)
        review = str(Path(temp) / "review.json")
        judge.review(prelabel, sha, self.physical_zip, self.label_zip, self.multirc_zip, review)
        return prelabel, sha, review

    def test_frozen_three_archive_hashes_and_original_model_files(self):
        for key, path in (("physical", self.physical_zip),
                          ("labels", self.label_zip), ("multirc", self.multirc_zip)):
            self.assertEqual(hashlib.sha256(Path(path).read_bytes()).hexdigest(), judge.ZIPS[key])
        for key, path in (("granite", self.granite),
                          ("mmbert", self.mmbert), ("multirc", self.multirc)):
            self.assertEqual(hashlib.sha256(Path(path).read_bytes()).hexdigest(), blind.SOURCE_SHA[key])

    def test_original_128_cases_are_physically_matched_without_labels(self):
        g = blind.physical(self.source[0], "granite97")
        m = blind.physical(self.source[1], "mmbert_small")
        self.assertEqual(set(g), set(m))
        self.assertEqual(len(g), 128)
        self.assertEqual({(g[k]["group_id"],g[k]["joint_input_digest"]) for k in g},
                         {(m[k]["group_id"],m[k]["joint_input_digest"]) for k in m})
        self.assertTrue(all("label" not in v for v in g.values()))

    def test_original_multirc_answer_information_negative(self):
        s = blind.multirc_blind(self.source[2])
        self.assertEqual((s["answers"],s["questions"],s["source_groups"]),(33,8,4))
        self.assertEqual(s["questions_with_span_at_most_001"],8)
        self.assertAlmostEqual(s["mean_conditioned_span"],2.21954608757291e-05, places=13)
        self.assertFalse(s["answer_sufficient_for_fbsde_admission"])

    def test_all_original_task_metrics_costs_and_no_go(self):
        with tempfile.TemporaryDirectory() as temp:
            prelabel, sealed_sha, reviewed = self._two(temp)
            p = json.loads(Path(prelabel).read_text())
            r = json.loads(Path(reviewed).read_text())
            self.assertEqual(len(p["rows"]),128)
            self.assertEqual(r["prelabel_sha256"],sealed_sha)
            self.assertEqual([(k, v["correct"],v["switches"]) for k,v in sorted(r["policy_outcomes"].items())],
                             [("always_mmbert",73,128),("stop",122,0),
                              ("uncertain_060",122,6),("uncertain_075",118,16)])
            self.assertEqual((r["two_model_oracle_correct_upper_bound"],r["oracle_recoverable_granite_errors"]),(126,4))
            self.assertTrue(r["accuracy_first_additional_computation_no_go"])
            self.assertFalse(r["system2_full_fbsde_admitted"])
            self.assertEqual(r["original_model_forwards_during_this_replay"],0)
            self.assertEqual(r["authority"],"DENY_ALL")

    def test_prelabel_emits_no_ground_truth_or_correctness(self):
        with tempfile.TemporaryDirectory() as temp:
            path = str(Path(temp)/"a.json")
            self._blind(path)
            p = json.loads(Path(path).read_text())
            self.assertFalse(p["system2_full_fbsde_admitted"])
            self.assertFalse(p["neural_continuation_real_task_gain_qualified"])
            self.assertTrue(all(not any(k in v for k in ("label","correct","truth")) for v in p["rows"]))
            self.assertEqual({k for row in p["rows"] for k in row["arms"]},set(blind.POLICIES))

    def test_prelabel_create_only_not_overwrite(self):
        with tempfile.TemporaryDirectory() as temp:
            path = str(Path(temp)/"sealed.json")
            first = self._blind(path)
            with self.assertRaises(FileExistsError):
                self._blind(path)
            self.assertEqual(hashlib.sha256(Path(path).read_bytes()).hexdigest(),first)

    def test_label_seal_must_match(self):
        with tempfile.TemporaryDirectory() as temp:
            path = str(Path(temp)/"a.json")
            sha = self._blind(path)
            with self.assertRaises(ValueError):
                judge.review(path,"0"*64,self.physical_zip,self.label_zip,self.multirc_zip,
                             str(Path(temp)/"bad.json"))
            self.assertFalse((Path(temp)/"bad.json").exists())

    def test_resigned_ghost_answer_is_independently_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/"a.json"
            self._blind(str(path))
            payload=json.loads(path.read_text())
            payload["rows"][0]["arms"]["stop"]["probability"] = .99
            path.unlink()
            path.write_text(json.dumps(payload))
            with self.assertRaises(ValueError):
                judge.review(str(path),hashlib.sha256(path.read_bytes()).hexdigest(),
                             self.physical_zip,self.label_zip,self.multirc_zip,str(Path(temp)/"review.json"))

    def test_resigned_hidden_outcome_in_prelabel_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/"a.json"
            self._blind(str(path))
            payload=json.loads(path.read_text())
            payload["rows"][0]["label"] = 1
            path.unlink();path.write_text(json.dumps(payload))
            with self.assertRaises(ValueError):
                judge.review(str(path),hashlib.sha256(path.read_bytes()).hexdigest(),
                             self.physical_zip,self.label_zip,self.multirc_zip,str(Path(temp)/"review.json"))

    def test_resigned_cost_forgery_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/"a.json"
            self._blind(str(path))
            payload=json.loads(path.read_text())
            payload["rows"][0]["arms"]["always_mmbert"]["additional_observed_forward_ns"] = 0
            path.unlink();path.write_text(json.dumps(payload))
            with self.assertRaises(ValueError):
                judge.review(str(path),hashlib.sha256(path.read_bytes()).hexdigest(),
                             self.physical_zip,self.label_zip,self.multirc_zip,str(Path(temp)/"review.json"))

    def test_resigned_authority_production_fraud_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            for field, val in (("production_authorized",True),
                               ("system2_full_fbsde_admitted",True),
                               ("neural_continuation_real_task_gain_qualified",True)):
                path=Path(temp)/(field+".json")
                self._blind(str(path))
                payload=json.loads(path.read_text());payload[field] = val
                path.unlink();path.write_text(json.dumps(payload))
                with self.subTest(field=field),self.assertRaises(ValueError):
                    judge.review(str(path),hashlib.sha256(path.read_bytes()).hexdigest(),
                                 self.physical_zip,self.label_zip,self.multirc_zip,str(Path(temp)/(field+".review.json")))

    def test_changed_input_source_fails_before_prelabel_publication(self):
        with tempfile.TemporaryDirectory() as temp:
            src=Path(temp)/"altered.json"
            data=Path(self.mmbert).read_bytes()
            src.write_bytes(data[:-1]+b" ")
            with self.assertRaises(ValueError):
                blind.produce(self.granite,str(src),self.multirc,str(Path(temp)/"out.json"))
            self.assertFalse((Path(temp)/"out.json").exists())

    def test_cross_model_source_alias_is_rejected(self):
        corrupted=copy.deepcopy(self.source[1]);
        next(v for v in corrupted["future_predictions"] if v["split"]=="new_holdout")["joint_input_digest"] = "b"*64
        with tempfile.TemporaryDirectory() as temp, patch.object(blind,"read_source",side_effect=[self.source[0],corrupted,self.source[2]]):
            with self.assertRaises(ValueError):
                blind.produce(self.granite,self.mmbert,self.multirc,str(Path(temp)/"x.json"))

    def test_duplicate_original_question_candidate_rejected(self):
        wrong=copy.deepcopy(self.source[2]);wrong["rows"][1]["task_id"] = wrong["rows"][0]["task_id"]
        with self.assertRaises(ValueError):blind.multirc_blind(wrong)

    def test_forged_multirc_label_availability_is_denied(self):
        wrong=copy.deepcopy(self.source[2]);wrong["evaluation_labels_loaded"] = True
        with self.assertRaises(ValueError):blind.multirc_blind(wrong)

    def test_injected_nonfinite_and_duplicate_json_rejected(self):
        for raw in (b'{"a":1,"a":2}',b'{"p": NaN}', b'{"q":Infinity}'):
            with self.subTest(raw=raw),self.assertRaises(ValueError):
                blind.exact_json(raw)

    def test_labels_zip_modified_is_rejected_even_if_prelabel_unchanged(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/"altered-original.zip"
            raw=Path(self.label_zip).read_bytes()
            p.write_bytes(raw[:-1]+bytes([raw[-1]^1]))
            with self.assertRaises(ValueError):
                judge.load_archives(self.physical_zip,str(p),self.multirc_zip)

    def test_original_multirc_member_manifest_is_independent_of_proposer(self):
        original=judge.load_archives(self.physical_zip,self.label_zip,self.multirc_zip)
        self.assertEqual(original["multirc_scores"]["results"]["conditioned"]["correct"],16)
        self.assertEqual(original["multirc_scores"]["results"]["conditioned"]["near_invariant_native_answer_question_count"],8)


if __name__=="__main__":
    unittest.main()
