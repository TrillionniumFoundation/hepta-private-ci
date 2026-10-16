"""Adversarial source-cluster research tests; historical ZIP run is separate."""
import copy
import json
import math
from pathlib import Path
import tempfile
import unittest

from bridge_original_effect_v76 import (
    ARMS, SEEDS, V6_SHA256, _json, _f1, demand, score, validate_panel,
    validate_natural, original_old_binding, paired_source_bootstrap,
    original_archive, cid,
)


def sample_case(group, number, answer, label):
    return dict(source_split="train", paragraph_id=str(group),
                question_id=str(number),answer_id=str(answer),
                label=label,source_hash=f"{group+1:064x}")


def original_shape_fixture():
    # This *is not* original MultiRC: 16 source groups / 827 candidates / 194
    # complete questions, source-specific labels and repeated seed observations.
    rows=[]
    qs=[12]*14+[13]*2
    assert sum(qs)==194
    per_src_cases=[51]*15+[62]
    # each question gets a fixed number of candidates, with last questions
    # absorbing the nonuniform total; never cross a source's question boundary.
    for g,(q_count,n_cases) in enumerate(zip(qs,per_src_cases)):
        for q in range(q_count):
            size=2+(n_cases-2*q_count)//q_count+(q < (n_cases-2*q_count)%q_count)
            for a in range(size):
                rows.append(sample_case(g,q,a,int((g+q+a)%3==0)))
    assert len(rows)==827
    return rows


class IndependentClusterTests(unittest.TestCase):
    def test_counts_questions_and_group_identity(self):
        r=original_shape_fixture()
        g=validate_natural(r)
        self.assertEqual(len(g["groups"]),16)
        self.assertEqual(len(g["questions"]),194)
        self.assertEqual(len(g["ids"]),827)
        self.assertEqual(sum(map(len,g["group_to_indices"].values())),827)

    def test_duplicate_source_id_or_multiple_paragraphs_same_source_fails(self):
        rows=original_shape_fixture()
        rows[1]=copy.deepcopy(rows[0])
        with self.assertRaisesRegex(ValueError,"duplicate"):
            validate_natural(rows)
        rows=original_shape_fixture()
        rows[0]["source_hash"] = rows[1+51]["source_hash"]
        with self.assertRaisesRegex(ValueError,"sixteen independent"):
            validate_natural(rows)

    def test_same_questions_and_labels_are_required_in_panel(self):
        rows=original_shape_fixture()
        g=validate_natural(rows)
        p=[1. if x["label"] else 0. for x in rows]
        model=dict(parameter_count=42562,execution_parameter_sha256="a"*64)
        observed=score(rows,p)
        panel=dict(case_ids=g["ids"],model_execution_parameter_sha256="a"*64,
                   scope="old_training_source_internal_tune_not_fresh",
                   threshold_selected=False,probabilities=p,metrics=observed)
        self.assertEqual(validate_panel(panel,rows,g["ids"],model)["f1_a"],1.)
        forged=copy.deepcopy(panel)
        forged["model_execution_parameter_sha256"]="b"*64
        with self.assertRaisesRegex(ValueError,"source/weight"):
            validate_panel(forged,rows,g["ids"],model)
        forged=copy.deepcopy(panel)
        forged["metrics"]["f1_a"] = 0.
        with self.assertRaisesRegex(ValueError,"metric"):
            validate_panel(forged,rows,g["ids"],model)
        forged=copy.deepcopy(panel)
        forged["case_ids"]=forged["case_ids"][::-1]
        with self.assertRaisesRegex(ValueError,"source/weight"):
            validate_panel(forged,rows,g["ids"],model)

    def test_probability_poison_nan_inf_bool_rejected(self):
        r=original_shape_fixture()
        for poison in (True,float("nan"),float("inf"),-0.1,1.1):
            values=[0.5]*len(r)
            values[0]=poison
            with self.subTest(poison=str(poison)), self.assertRaises(ValueError):
                score(r,values)

    def test_f1_positive_and_non_additivity(self):
        self.assertEqual(_f1([(1,1),(0,0),(1,1)],1),1)
        self.assertEqual(_f1([(0,0),(0,1)],1),0)
        rows=original_shape_fixture()
        result=score(rows,[1.]*827)
        self.assertAlmostEqual(result["f1_a"],2*sum(r["label"] for r in rows)/(827+sum(r["label"] for r in rows)))
        self.assertEqual(result["exact_match"],0.)

    def test_full_three_seed_cohort_reuses_one_original_source_draw(self):
        rows=original_shape_fixture()
        g=validate_natural(rows)
        probs={(seed,arm):[float((seed+len(arm)+r["label"])%3==0) for r in rows]
               for seed in SEEDS for arm in ARMS}
        b=paired_source_bootstrap(rows,g,probs,repeats=100,seed=41)
        self.assertEqual(b["original_source_groups"],16)
        self.assertTrue(b["resampled_source_groups_once_across_all_three_seeds"])
        self.assertEqual(len(b["paired_effects"]),7)
        c=paired_source_bootstrap(rows,g,probs,repeats=100,seed=41)
        self.assertEqual(c,b)
        del probs[41,"contrastive"]
        with self.assertRaisesRegex(ValueError,"complete 12"):
            paired_source_bootstrap(rows,g,probs,repeats=100,seed=41)

    def test_old_binding_pairs_and_failed_retention(self):
        rows=[]
        for g in range(32):
            for world in (0,1):
                for ans in (0,1):
                    rows.append(dict(source_split="train",
                                     paragraph_id=f"binding-v4/train/41/{g}/world-{world}",
                                     question_id="0",answer_id=str(ans), label=int(ans==world)))
        probabilities=[float(r["label"]) for r in rows]
        baseline=dict(accuracy=1.,both_worlds_correct=1.)
        panel=dict(case_ids=[cid(r) for r in rows],probabilities=probabilities,
                   metrics=dict(accuracy=1.,both_worlds_correct=1.))
        accepted=original_old_binding(rows,panel,baseline,dict(passed=True,fresh_selection=False))
        self.assertTrue(accepted["retention_train_only"])
        altered=copy.deepcopy(panel)
        altered["probabilities"][:8] = [1-v for v in altered["probabilities"][:8]]
        altered["metrics"]={"accuracy":120/128,"both_worlds_correct":60/64}
        with self.assertRaisesRegex(ValueError,"retention gate"):
            original_old_binding(rows,altered,baseline,dict(passed=True,fresh_selection=False))

    def test_duplicate_json_and_unbounded_resamples(self):
        with self.assertRaisesRegex(ValueError,"duplicate"):
            _json(b'{"a":1,"a":2}')
        with self.assertRaises(ValueError):
            _json(b'{"a":NaN}')
        rows=original_shape_fixture()
        g=validate_natural(rows)
        probs={(seed,arm):[.5]*827 for seed in SEEDS for arm in ARMS}
        with self.assertRaisesRegex(ValueError,"bounded resampling"):
            paired_source_bootstrap(rows,g,probs,repeats=999999)

    def test_archive_wrong_or_symlinked_source_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            p=Path(root)/"fake.zip"
            p.write_bytes(b"fake archive")
            with self.assertRaises(ValueError):
                original_archive(p)
            link=Path(root)/"link.zip"
            link.symlink_to(p)
            with self.assertRaisesRegex(ValueError,"symlink"):
                original_archive(link)


if __name__=="__main__":
    unittest.main()
