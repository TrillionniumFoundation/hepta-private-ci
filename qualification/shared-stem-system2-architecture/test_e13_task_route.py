"""E13 label-blind producer and independent arithmetic adversarial regression."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from fractions import Fraction as Q
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import tempfile
import unittest

from e13_labelblind_route import (CUT, ARMS, _route_one, canon, produce,
                                 quantized_x0, write_once)
from e13_independent_score import (decode_cert, json_read, mcnemar_p,
                                   original_law, score, take_source)
from e12_independent_audit import audit, reference
from e7_archive import PHYSICAL_SHA, physical_rows, read_zip
from e7_second_opinion import (HIST_SHA, archive, group_labels,
                               model_predictions)


class E13Contracts(unittest.TestCase):
    def test_exact_labelblind_uncertainty(self):
        self.assertEqual(quantized_x0(0.5), "1")
        self.assertEqual(quantized_x0(0.), "0")
        self.assertEqual(quantized_x0(1.), "0")
        self.assertEqual(quantized_x0(.75), "1/2")
        self.assertEqual(original_law(.75).x0, "1/2")

    def test_invalid_probability(self):
        for p in (math.nan, math.inf, -0.1, 1.1, True, None, "0.5"):
            with self.subTest(p=p), self.assertRaises(ValueError):
                quantized_x0(p)

    def test_only_labelblind_inputs_needed(self):
        g={"group_id":"1"*64,"joint_input_digest":"2"*64,
           "probs":{"learned_gate":.75},"encoder_forward_ns":12,
           "head_ns":{"learned_gate":7}}
        m=deepcopy(g);m["probs"]["learned_gate"] = .45
        r=_route_one("a",g,m)
        self.assertNotIn("label",r)
        self.assertEqual(r["granite_archived_ns"],19)
        self.assertEqual(r["x0"],"1/2")
        self.assertEqual(set(r["routes"]),set(ARMS))
        self.assertEqual(r["cert"]["authority"],"DENY_ALL")
        cert=decode_cert(json.loads(json.dumps(r["cert"])))
        self.assertTrue(audit(original_law(.75),cert).certified)
        self.assertEqual(r["cheap_root"],str(reference(original_law(.75),
                        (Q(0),)*3)[2][0]))
        m["group_id"]="bad"
        with self.assertRaises(ValueError):_route_one("a",g,m)

    def test_canonical_write_only(self):
        with tempfile.TemporaryDirectory() as td:
            path=os.path.join(td,"once.json")
            d={"a":1,"b":False}
            sig=write_once(path,d)
            self.assertEqual(sig,sha256(Path(path).read_bytes()).hexdigest())
            with self.assertRaises(FileExistsError):write_once(path,d)

    def test_json_duplicate_nan_and_unbounded(self):
        for raw in (b'{"a":1,"a":2}',b'{"value":NaN}',b'{}'*500001,b''):
            with self.subTest(size=len(raw)),self.assertRaises((ValueError,TypeError)):
                json_read(raw)

    def test_sealed_hash_is_mandatory(self):
        with tempfile.TemporaryDirectory() as td:
            path=os.path.join(td,"file.json")
            Path(path).write_bytes(b'{"x":1}\n')
            with self.assertRaises(ValueError):take_source(path,"0"*64)
            self.assertEqual(take_source(path,sha256(Path(path).read_bytes()).hexdigest()),{"x":1})

    def test_statistical_exact_pairing(self):
        self.assertEqual(mcnemar_p(0,0),Q(1))
        self.assertEqual(mcnemar_p(0,10),Q(1,512))
        with self.assertRaises(ValueError):mcnemar_p(129,0)

    def test_malformed_trace(self):
        with self.assertRaises(ValueError):decode_cert({"trace":{}})


@unittest.skipUnless(os.environ.get("HEPTA_E13_PHYSICAL_ZIP") and
                     os.environ.get("HEPTA_E13_HISTORICAL_ZIP"),
                     "optional real-original ZIPs unavailable; hosted CI requires them")
class E13OriginalRealArchive(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.physical=os.environ["HEPTA_E13_PHYSICAL_ZIP"]
        cls.historical=os.environ["HEPTA_E13_HISTORICAL_ZIP"]
        cls.tmp=tempfile.TemporaryDirectory()
        cls.prelabel=os.path.join(cls.tmp.name,"sealed.json")
        cls.prelabel_sha=produce(cls.physical,cls.prelabel)
        cls.rows=json.loads(Path(cls.prelabel).read_bytes())
        cls.labels=group_labels(archive(cls.historical,HIST_SHA))
        cls.models=model_predictions(archive(cls.physical,PHYSICAL_SHA),cls.labels)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_original_hashes_and_128_real_rows(self):
        self.assertEqual(sha256(Path(self.physical).read_bytes()).hexdigest(),PHYSICAL_SHA)
        self.assertEqual(sha256(Path(self.historical).read_bytes()).hexdigest(),HIST_SHA)
        self.assertEqual(len(self.rows["rows"]),128)
        self.assertFalse(self.rows["human_labels_loaded_by_proposer"])

    def test_original_independent_review_and_negative_status(self):
        r=score(self.rows,self.labels,self.models)
        self.assertEqual(r["scored"]["granite_only"]["correct"],122)
        self.assertEqual(r["scored"]["e12_certified"]["hypothetical_secondary_model_calls"],12)
        self.assertLess(r["scored"]["e12_certified"]["correct"],122)
        self.assertGreater(r["scored"]["e12_certified"]["extra_archived_proxy_ns_vs_granite"],0)
        self.assertFalse(r["future_time_task_outcome"])
        self.assertFalse(r["entire_online_lifecycle_cost_qualified"])
        self.assertFalse(r["model_promotion_allowed"])

    def test_wrong_routes_rejected(self):
        for arm in ("e12_certified","confidence_075","cheap_one_map"):
            with self.subTest(arm=arm):
                proposal=deepcopy(self.rows)
                proposal["rows"][0]["routes"][arm] = not proposal["rows"][0]["routes"][arm]
                with self.assertRaises(ValueError):score(proposal,self.labels,self.models)

    def test_wrong_math_or_evidence_rejected(self):
        mutations=[
            lambda x:x["rows"][0]["cert"]["trace"]["z"].__setitem__(0,"1"),
            lambda x:x["rows"][0]["cert"].__setitem__("evaluations",1),
            lambda x:x["rows"][0]["cert"].__setitem__("fixed_point_error_bound","0"),
            lambda x:x["rows"][0].__setitem__("cheap_root","0"),
            lambda x:x["rows"][0].__setitem__("x0","0"),
            lambda x:x["rows"][0].__setitem__("granite_archived_ns",1),
            lambda x:x["rows"][0].__setitem__("group_id","0"*64),
            lambda x:x["rows"][0].__setitem__("label",1),
            lambda x:x["rows"].append(deepcopy(x["rows"][0])),
        ]
        for index,mutate in enumerate(mutations):
            with self.subTest(index=index):
                p=deepcopy(self.rows); mutate(p)
                with self.assertRaises((ValueError,TypeError,KeyError)):
                    score(p,self.labels,self.models)

    def test_wrong_claim_flags_rejected(self):
        for k in ("production_accepted","online_routing_executed",
                  "human_labels_loaded_by_proposer"):
            with self.subTest(k=k):
                p=deepcopy(self.rows);p[k]=True
                with self.assertRaises(ValueError):score(p,self.labels,self.models)

    def test_reviewer_cannot_be_fooled_by_changed_original_probs(self):
        p=deepcopy(self.rows)
        p["rows"][0]["mmbert_prob"] = .99
        with self.assertRaises(ValueError):score(p,self.labels,self.models)


if __name__=="__main__":unittest.main()
