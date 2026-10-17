"""Deterministic V26 anti-fabrication tests, no pretrained physical claim."""
from __future__ import annotations
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from PIL import Image

import v26_real_pixel_lesion as p
import v26_original_pixel_review as rev


def fake_prob(j):
    v=[0.1]*4;v[j]=0.7
    return v


def fake_case(i, split='test'):
    ident=f'{i:064x}';return {'id':ident,'group':f'{i+400:064x}',
                            'split':split,'image':f'{i+1:064x}',
                            'question':'question','hint':'',
                            'choices':['A','B','C','D'],'scope':'public-scienceqa-e3-research'}


class SourceOnly(unittest.TestCase):
    def test_canonical_and_digest_repeatable(self):
        self.assertEqual(p.digest(p.canonical({'a':3,'b':4})),p.digest(p.canonical({'b':4,'a':3})))

    def test_nonfinite_serialization_denied(self):
        with self.assertRaises(ValueError):p.canonical({'a':float('nan')})

    def test_reject_malformed_probability(self):
        for a in ([0.5]*4,[0.1,0.2,0.3,float('nan')],[1.],['0.3',0.4,0.2,0.1],[True,0.3,0.3,0.4],None):
            with self.subTest(a=a),self.assertRaises((p.Invalid,TypeError)):
                p.validate_probs(a)

    def test_top1_tie_determinism(self):
        self.assertEqual(p.top1([.25,.25,.25,.25]),0)

    def test_margin_is_not_visual_semantics(self):
        self.assertEqual(p.margin([.25]*4),0.0)
        self.assertAlmostEqual(p.margin([0.5,0.4,0.05,0.05]),0.1)

    def test_boundary_strict(self):
        self.assertLess(p.THRESHOLD,0.006)
        a={str(i):{'arms':{'text_only':[.25]*4}} for i in range(64)}
        self.assertEqual(len(p.route_from_text(a)),64)
        a.pop('0')
        with self.assertRaises(p.Invalid):p.route_from_text(a)

    def test_cross_source_swap_distinct(self):
        held=[fake_case(i) for i in range(64)]
        d=p.shuffled_donors(held)
        self.assertEqual(len(d),64)
        self.assertTrue(all(d[r['id']]['id']!=r['id'] and d[r['id']]['group']!=r['group'] for r in held))

    def test_repeated_source_fails_cold(self):
        a=[fake_case(0),fake_case(0)]
        with self.assertRaises(p.Invalid):p.shuffled_donors(a)

    def test_no_distinct_pixel_donor(self):
        a=[fake_case(0),fake_case(1)];a[1]['image']=a[0]['image'];a[1]['group']=a[0]['group']
        with self.assertRaises(p.Invalid):p.shuffled_donors(a)

    def test_source_roster_requires_192(self):
        with self.assertRaises(p.Invalid):p.validate_source_set([fake_case(1)],{})

    def test_image_is_actual_pixel_black(self):
        b=io.BytesIO();Image.new('RGB',(5,4),(200,40,20)).save(b,'PNG')
        raw=b.getvalue();black=p.black_image(raw)
        self.assertNotEqual(p.digest(raw),p.digest(black))
        with Image.open(io.BytesIO(black)) as im:
            self.assertEqual(im.getpixel((2,2)),(0,0,0))

    def test_black_original_cannot_fake_pixel_lesion(self):
        out=io.BytesIO();Image.new('RGB',(8,8),(0,0,0)).save(out,'PNG')
        with self.assertRaises(p.Invalid):p.black_image(out.getvalue())

    def test_bad_image_bytes_rejected(self):
        with self.assertRaises(Exception):p.black_image(b'not an image')

    def test_source_create_only_fsync(self):
        with tempfile.TemporaryDirectory() as t:
            z=Path(t)/'r.json'
            sha=p.safe_new(z,{'production_authorized':False})
            self.assertEqual(sha,p.digest(z.read_bytes()))
            with self.assertRaises(FileExistsError):p.safe_new(z,{'production_authorized':True})

    def test_score_arm_manual_truth(self):
        rows=[{'id':str(i),'probabilities':fake_prob(i%4)} for i in range(64)]
        scores,truth=rev.score_arm(rows,{str(i):i%4 for i in range(64)})
        self.assertEqual(scores['correct'],64)
        self.assertTrue(all(truth.values()))

    def test_score_arm_missing_case_fails(self):
        rows=[{'id':str(i),'probabilities':fake_prob(0)} for i in range(63)]
        with self.assertRaises(p.Invalid):rev.score_arm(rows,{str(i):0 for i in range(64)})

    def test_exact_mcnemar_symmetry(self):
        self.assertEqual(rev.exact_mcnemar(5,5),1.0)
        self.assertEqual(rev.exact_mcnemar(0,1),1.0)
        self.assertAlmostEqual(rev.exact_mcnemar(0,10),2/1024)

    def test_true_label_injection_denied_before_review(self):
        a={'schema':'forged','production_authorized':True}
        with self.assertRaises((p.Invalid,KeyError)):
            rev.review([],[],a,{}, {})

    def test_shadow_never_uses_unselected_image(self):
        held=[fake_case(i) for i in range(64)]
        src={r['id']:{'arms':{'text_only':fake_prob(1),'train_gate':fake_prob(2),'bridge_image_only':fake_prob(2)}} for r in held}
        selected={held[0]['id'],held[10]['id']}
        rows=p.shadow_scores(held,src,src,selected)
        self.assertEqual(len(rows),64)
        self.assertEqual(sum(x['selected'] for x in rows),2)
        self.assertEqual(next(x for x in rows if x['id']==held[1]['id'])['probabilities'],fake_prob(1))
        self.assertEqual(next(x for x in rows if x['id']==held[0]['id'])['probabilities'],fake_prob(2))

    def test_shadow_mismatched_roster_denied(self):
        held=[fake_case(i) for i in range(64)]
        rows={r['id']:{'arms':{'text_only':fake_prob(1),'train_gate':fake_prob(2),'bridge_image_only':fake_prob(2)}} for r in held}
        with self.assertRaises(p.Invalid):p.shadow_scores(held,rows,rows,{'nonexistent'})

    def test_cross_host_approximation_is_not_exact(self):
        a={str(i):{'arms':{'text_only':fake_prob(0),'train_gate':fake_prob(1),'bridge_image_only':fake_prob(1)}} for i in range(64)}
        self.assertEqual(p.close_to_archived(a,a),0.0)
        b=copy.deepcopy(a);b['1']['arms']['train_gate']=[.1,.6,.2,.1]
        with self.assertRaises(p.Invalid):p.close_to_archived(b,a)

    def test_authority_is_unconditionally_denied(self):
        self.assertEqual(p.DENY,'DENY_ALL')
        self.assertEqual(p.THRESHOLD,.005)
        self.assertEqual(p.SOURCE_SHA,'a561916c7d56b6677c5511c329a49bbeec94879f019d29f159ff59be83359202')


class OriginalArchive(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path=os.environ.get('HEPTA_V26_ORIGINAL_ZIP')
        if not path:raise RuntimeError('Original archive is mandatory in this separate job')
        cls.path=Path(path)

    def test_exact_e3_zip_and_64_physical_predictions(self):
        obj,rows=p.strict_archive(self.path)
        self.assertEqual(len(rows),64)
        self.assertEqual(obj['source_sha256'],p.SOURCE_SHA)
        self.assertEqual(obj['fit']['private_cell_head_parameters'],769)

    def test_frozen_original_21_case_request_set(self):
        _,rows=p.strict_archive(self.path)
        self.assertEqual(len(p.route_from_text(rows)),21)

    def test_full_and_masked_original_equal_text(self):
        _,rows=p.strict_archive(self.path)
        self.assertTrue(all(x['arms']['image_masked']==x['arms']['text_only'] for x in rows.values()))

    def test_old_stats_not_a_new_accuracy_claim(self):
        _,rows=p.strict_archive(self.path)
        changed=sum(p.top1(x['arms']['train_gate'])!=p.top1(x['arms']['text_only']) for x in rows.values())
        self.assertEqual(changed,38)

    def test_byte_flip_fails_closed(self):
        with tempfile.TemporaryDirectory() as d:
            t=Path(d)/'bad.zip'
            data=bytearray(self.path.read_bytes());data[100]^=1;t.write_bytes(data)
            with self.assertRaises(p.Invalid):p.strict_archive(t)

    def test_legacy_original_text_only_v25_is_control(self):
        _,rows=p.strict_archive(self.path)
        routed=p.route_from_text(rows)
        self.assertEqual(len(routed),21)
        self.assertEqual(sum(p.top1(rows[rid]['arms']['bridge_image_only'])!=p.top1(rows[rid]['arms']['text_only']) for rid in routed),19)


if __name__=='__main__':unittest.main()
