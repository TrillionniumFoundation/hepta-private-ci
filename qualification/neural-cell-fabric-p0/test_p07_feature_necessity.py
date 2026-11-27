"""P0.7 fail-closed, independent-custody and real historical feature tests."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import tempfile
import unittest

import numpy as np

from fabric import Denied
import p07_feature_necessity as p

AG = os.getenv("HEPTA_P07_AGNEWS")
BANK = os.getenv("HEPTA_P07_BANK_DIR")


def minimal_train(classes=2, dim=4):
    rows = []
    for c in range(classes):
        for i in range(3):
            v = np.zeros(dim, dtype=float)
            v[c] = p.SCALE
            rows.append({"id":f"train-{c}-{i}","cell":i%2,"x":v.tolist(),"target":c})
    return rows


class SourceOnlyTests(unittest.TestCase):
    def test_train_only_loo_has_paid_cost(self):
        centers, info=p.prototype_train(minimal_train(),2)
        self.assertEqual(centers.shape,(2,4))
        self.assertEqual(info["paid_loo_evaluations"],48)
        self.assertIn(info["selected_temperature"],p.TEMPERATURES)

    def test_loo_does_not_read_held_targets(self):
        rows=minimal_train()
        first=p.prototype_train(rows,2)
        other=copy.deepcopy(rows)
        self.assertEqual(first[1],p.prototype_train(other,2)[1])
        other[0]["target"]=1
        self.assertNotEqual(first[1]["train_only_loo_nll"],p.prototype_train(other,2)[1]["train_only_loo_nll"])

    def test_identity_permutation_is_invariant(self):
        rows=minimal_train(dim=4)
        centers,info=p.prototype_train(rows,2)
        x=np.asarray([r["x"] for r in rows])
        base=p.softmax(info["selected_temperature"]*(x@centers.T))
        order=np.array([3,1,0,2])
        permuted=p.softmax(info["selected_temperature"]*(x[:,order]@centers[:,order].T))
        self.assertTrue(np.allclose(base,permuted,atol=1e-14))

    def test_shift_breaks_some_predictions(self):
        x=np.asarray([r["x"] for r in minimal_train()]); centers,_=p.prototype_train(minimal_train(),2)
        a=p.softmax(centers@x[0]); b=p.softmax(centers@x[3]);self.assertGreater(float(np.max(abs(a-b))),.5)

    def test_wrong_original_archive_denied(self):
        with tempfile.TemporaryDirectory() as d:
            f=Path(d)/"hdcf-original-features.zip";f.write_bytes(b"PK\x03\x04not original")
            with self.assertRaises(Denied):p.bank_member(f,"hdcf-original-features.zip")

    def test_duplicate_keys_denied(self):
        with self.assertRaises(Denied):p.strict_json(b'{"a":1,"a":2}')

    def test_nonfinite_denied(self):
        with self.assertRaises(Denied):p.strict_json(b'{"nan":NaN}')

    def test_bad_dimension_denied(self):
        with self.assertRaises(Denied):p.normalise([0]*3,4)
        with self.assertRaises(Denied):p.normalise([0]*4,4)

    def test_held_gold_never_admissible(self):
        # The source verifier must reject extra target fields even with a
        # syntactically valid publisher case ID and normalized feature vector.
        task={"classes":2,"dimension":768,"source_sha256":p.BANK_ARCHIVES["hdcf-original-features.zip"][0],
              "model_sha256":"f"*64,"train":[],"heldout":[]}
        bundle={"schema":p.SCHEMA,"tasks":{"agnews_mmbert_384":task,
                 "banking77_modernbert_768":task},"provenance":{}}
        with self.assertRaises(Denied):p.verify(bundle)

    def test_seal_rejects_changed_bytes(self):
        with tempfile.TemporaryDirectory() as d:
            priv=Path(d)/"private";priv.mkdir(mode=0o700)
            v={"schema":p.SCHEMA,"source_digest":"f"*64,
                "disposition":"HOLD_NO_GO","held_labels_in_producer":False}
            s=p.commit(priv/"pre.json",v)
            p.commit(priv/"seal.json",{"schema":p.SCHEMA,"authority":"DENY_ALL",
                       "held_labels_opened":False,"source_digest":v["source_digest"],"prelabel_sha256":s})
            self.assertEqual(p.seal_read(priv/"pre.json",priv/"seal.json"),v)
            (priv/"pre.json").write_text((priv/"pre.json").read_text()+" ")
            with self.assertRaises(Denied):p.seal_read(priv/"pre.json",priv/"seal.json")

    def test_rewrite_forbidden_even_if_same_bytes(self):
        with tempfile.TemporaryDirectory() as d:
            priv=Path(d)/"private";priv.mkdir(mode=0o700)
            p.commit(priv/"test.json",{"x":1})
            with self.assertRaises(Denied):p.commit(priv/"test.json",{"x":1})

    def test_nonprivate_output_denied(self):
        with tempfile.TemporaryDirectory() as d:
            # tempfile normally creates a 0700 directory; deliberately make it
            # world-searchable to exercise the negative owner boundary.
            os.chmod(d,0o755)
            with self.assertRaises(Denied):p.commit(Path(d)/"test.json",{"x":1})

    def test_symlinked_output_denied(self):
        with tempfile.TemporaryDirectory() as d:
            priv=Path(d)/"priv";priv.mkdir(mode=0o700)
            (priv/"link.json").symlink_to(Path(d)/"target")
            with self.assertRaises(Denied):p.commit(priv/"link.json",{"x":1})

    def test_numerical_oracle_detects_prediction_attack(self):
        centers=np.array([[4.,0,0,0],[0,4,0,0]])
        x=np.array([[4.,0,0,0],[0,4,0,0]])
        z=p.score_features(centers,x,1)
        p.audit_vector(centers,x,1,z)
        z[0,0]=.1
        with self.assertRaises(Denied):p.audit_vector(centers,x,1,z)

    def test_text_duplicate_and_near_duplicate_detection(self):
        train=["one two three four five"]+[f"unique example {i} token" for i in range(63)]
        held=["ONE  TWO three four FIVE"]+[f"novel article {i} terms" for i in range(31)]
        r=p.text_overlap_audit(train,held)
        self.assertEqual(r["exact_cross_split_normalized_text_duplicates"],1)
        self.assertGreaterEqual(r["held_with_train_text_jaccard_at_least_0_80"],1)
        self.assertFalse(r["text_or_case_ids_exported"])

    def test_brier_and_predictions_tie(self):
        actual=np.array([[1.,0.],[0.,1.]])
        self.assertEqual(p.ncorrect(actual,np.array([0,1])),2)
        self.assertEqual(p.brier(actual,np.array([0,1])),0.)


@unittest.skipUnless(AG and BANK, "original independently pinned historical ZIPs not supplied")
class OriginalArchiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ag=Path(AG)
        cls.bank=Path(BANK)
        cls.source=p.stage(cls.ag,cls.bank)
        p.verify(cls.source)
        cls.pred=p.produce(cls.source)

    def test_only_train_labels_exposed(self):
        for task in self.source["tasks"].values():
            self.assertEqual(len(task["train"]),64)
            self.assertEqual(len(task["heldout"]),32)
            self.assertTrue(all("target" in r for r in task["train"]))
            self.assertTrue(all("target" not in r for r in task["heldout"]))

    def test_archival_encoder_provenance(self):
        self.assertEqual(self.source["tasks"]["agnews_mmbert_384"]["dimension"],384)
        self.assertEqual(self.source["tasks"]["banking77_modernbert_768"]["dimension"],768)
        self.assertFalse(self.source["provenance"]["same_encoder_for_both_tasks"])

    def test_real_cyclic_mismatch_identity(self):
        for task in self.pred["runs"].values():
            self.assertEqual(len(task["all_cyclic_mismatches"]),31)
            self.assertEqual(len(task["normal"]),32)
            self.assertEqual(len(task["all_cyclic_mismatches"][0]),32)
            self.assertEqual(len(task["route_preserving_mismatches"]),p.ROUTE_SHIFTS)
            self.assertEqual(len(task["route_preserving_mismatches"][0]),32)
            self.assertLess(task["temperature_selection"]["paid_loo_evaluations"],513)
            self.assertEqual(task["authority"],"DENY_ALL")

    def test_authentic_full_postseal_review(self):
        with tempfile.TemporaryDirectory() as d:
            priv=Path(d)/"private";priv.mkdir(mode=0o700)
            p.commit(priv/"source.json",self.source)
            digest=p.commit(priv/"prelabel.json",self.pred)
            p.commit(priv/"seal.json",{"schema":p.SCHEMA,"authority":"DENY_ALL",
                       "held_labels_opened":False,"source_digest":self.pred["source_digest"],
                       "prelabel_sha256":digest})
            report=p.review(self.ag,self.bank,priv/"source.json",priv/"prelabel.json",priv/"seal.json")
            self.assertEqual(report["tasks"]["agnews_mmbert_384"]["original_aligned_correct"],28)
            self.assertEqual(report["tasks"]["banking77_modernbert_768"]["original_aligned_correct"],22)
            self.assertEqual(report["tasks"]["agnews_mmbert_384"]["cyclic_at_least_aligned"],0)
            self.assertEqual(report["tasks"]["banking77_modernbert_768"]["cyclic_at_least_aligned"],7)
            self.assertEqual(report["tasks"]["agnews_mmbert_384"]["within_cell_at_least_aligned"],0)
            self.assertEqual(report["tasks"]["banking77_modernbert_768"]["within_cell_at_least_aligned"],0)
            self.assertEqual(report["tasks"]["agnews_mmbert_384"]["source_text_overlap_audit"]["exact_cross_split_normalized_text_duplicates"],0)
            self.assertEqual(report["tasks"]["banking77_modernbert_768"]["source_text_overlap_audit"]["held_with_train_text_jaccard_at_least_0_80"],0)
            self.assertEqual(report["disposition"],"HOLD_NO_GO")

    def test_reviewer_rejects_resigned_tampered_probabilities(self):
        with tempfile.TemporaryDirectory() as d:
            priv=Path(d)/"private";priv.mkdir(mode=0o700)
            p.commit(priv/"source.json",self.source)
            attack=copy.deepcopy(self.pred)
            attack["runs"]["agnews_mmbert_384"]["normal"][0]=[1.,0.,0.,0.]
            token=p.commit(priv/"pre.json",attack)
            p.commit(priv/"seal.json",{"schema":p.SCHEMA,"authority":"DENY_ALL",
                       "held_labels_opened":False,"source_digest":attack["source_digest"],
                       "prelabel_sha256":token})
            with self.assertRaises(Denied):p.review(self.ag,self.bank,priv/"source.json",priv/"pre.json",priv/"seal.json")

    def test_reviewer_rejects_resigned_source_feature_drift(self):
        with tempfile.TemporaryDirectory() as d:
            priv=Path(d)/"private";priv.mkdir(mode=0o700)
            attack=copy.deepcopy(self.source)
            row=attack["tasks"]["agnews_mmbert_384"]["heldout"][0]
            row["x"]=attack["tasks"]["agnews_mmbert_384"]["heldout"][1]["x"]
            p.commit(priv/"source.json",attack)
            token=p.commit(priv/"pre.json",p.produce(attack))
            p.commit(priv/"seal.json",{"schema":p.SCHEMA,"authority":"DENY_ALL",
                       "held_labels_opened":False,"source_digest":p.sha(p.canonical(attack)),
                       "prelabel_sha256":token})
            with self.assertRaises(Denied):p.review(self.ag,self.bank,priv/"source.json",priv/"pre.json",priv/"seal.json")

    def test_original_wrong_model_material_denied(self):
        with tempfile.TemporaryDirectory() as d:
            priv=Path(d)/"private";priv.mkdir(mode=0o700)
            fake=priv/"hdcf-original-features.zip";fake.write_bytes(self.bank.joinpath("hdcf-original-features.zip").read_bytes()[:-1]+b"X")
            with self.assertRaises(Denied):p.bank_member(fake,"hdcf-original-features.zip")

    def test_no_future_or_production_authority(self):
        self.assertFalse(self.pred["global_optimization_or_cell_split_proved"])
        self.assertFalse(self.pred["independent_original_issuer_verified"])
        self.assertEqual(self.pred["authority"],"DENY_ALL")
        self.assertEqual(self.pred["disposition"],"HOLD_NO_GO")


if __name__ == "__main__":
    unittest.main()
