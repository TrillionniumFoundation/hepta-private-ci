"""Source-only synthetic/adversarial V27 checks: no pretrained or original result claim."""
import copy
import hashlib
import json
from pathlib import Path
import stat
import tempfile
import unittest

import v27_conditional_vision_replay as v


def vectors(leader):
    return [0.7,0.1,0.1,0.1] if leader==0 else [0.1,0.7,0.1,0.1]


def fixture():
    cases=[];sources={};gold={}
    for i in range(64):
        cid=f'{i+1:064x}';group=f'{100+i:064x}'
        triggered=i<21
        text=[0.252,0.250,0.249,0.249] if triggered else vectors(0)
        image=vectors(1) if (i<19 or 21<=i<52) else vectors(0)
        arms={name: (image.copy() if name in {'bridge_image_only','train_gate'} else text.copy())
              for name in v.ARMS}
        cases.append({'id':cid,'group':group,'split':'test','arms':arms})
        sources[cid]={'id':cid,'group':group,'split':'test'}
        gold[cid]=i%4
    published={'source_sha256':v.SOURCE_SHA,'sealed_predictions_sha256':v.PRED_SHA,
               'authority':'DENY_ALL','production_accepted':False,
               'statistical_selection_authorized':False,'stem_winner':None,
               'original_heldout_cases':64,
               'arms':{},'paired_vs_text_only':{}}
    for name in v.ARMS:
        hits=sum(v.pick(c['arms'][name])==gold[c['id']] for c in cases)
        published['arms'][name]={'correct':hits,'accuracy':hits/64,'cases':64}
        if name not in {'text_only','image_masked'}:
            rescue=sum(v.pick(c['arms'][name])==gold[c['id']] and
                       v.pick(c['arms']['text_only'])!=gold[c['id']] for c in cases)
            harm=sum(v.pick(c['arms'][name])!=gold[c['id']] and
                     v.pick(c['arms']['text_only'])==gold[c['id']] for c in cases)
            published['paired_vs_text_only'][name]={
                'rescued_errors_vs_text':rescue,'new_errors_vs_text':harm,
                'discordant_cases':rescue+harm,
                'mcnemar_unadjusted_exact_p':v.exact_p(rescue,harm)}
    pred={'source_sha256':v.SOURCE_SHA,'arms':sorted(v.ARMS),'predictions':cases,
          'held_labels_visible_to_inference':False,'production_accepted':False}
    seals={'private_test_labels_sha256':'a'*64,'source_sha256':v.SOURCE_SHA}
    return pred,published,seals,sources,gold


class SourceTests(unittest.TestCase):
    def good(self):
        p,review,seals,sources,gold=fixture()
        plan=v.make_plan(p,review)
        result=v.review_plan(plan,p,review,seals,sources,gold)
        return result

    def test_replay_recomputes_every_original_arm(self):
        r=self.good()
        self.assertEqual(r['cases'],64)
        self.assertEqual(r['counterfactual_image_lookups'],21)
        self.assertEqual(r['counterfactual_changed_decisions'],19)
        self.assertTrue(5<=r['counterfactual_correct']<=33)
        self.assertEqual(r['original_arm_correct_recount']['text_only'],16)
        self.assertTrue(r['archived_reviewer_all_arms_recomputed'])
        self.assertFalse(r['physical_savings_established'])
        self.assertIsNone(r['physical_conditional_encoder_forwards'])
        self.assertFalse(r['production_authorized'])

    def test_seal_stability_and_create_only_file(self):
        p,r,_,_,_=fixture()
        a=v.make_plan(p,r)
        b=v.make_plan(p,r)
        self.assertEqual(v.canonical(a),v.canonical(b))
        with tempfile.TemporaryDirectory() as d:
            f=Path(d)/'plan.json'
            v.safe_write(f,a)
            self.assertEqual(f.read_bytes(),v.canonical(a))
            self.assertEqual(stat.S_IMODE(f.stat().st_mode),0o600)
            with self.assertRaises(FileExistsError):v.safe_write(f,a)

    def rejection(self, mutate):
        p,r,s,sources,gold=fixture()
        plan=v.make_plan(p,r)
        mutate(p,r,s,sources,gold,plan)
        with self.assertRaises((v.Rejected,ValueError,TypeError,KeyError)):
            v.review_plan(plan,p,r,s,sources,gold)

    def test_injected_route_veto(self):
        self.rejection(lambda p,r,s,so,g,plan:plan['rows'][0].__setitem__('selected_class',2))

    def test_modified_threshold_veto(self):
        self.rejection(lambda p,r,s,so,g,plan:plan.__setitem__('threshold',0.9))

    def test_modified_policy_veto(self):
        self.rejection(lambda p,r,s,so,g,plan:plan.__setitem__('policy','all_visual'))

    def test_injected_source_target_veto(self):
        self.rejection(lambda p,r,s,so,g,plan:g.__setitem__(p['predictions'][0]['id'],9))

    def test_copied_label_group_veto(self):
        self.rejection(lambda p,r,s,so,g,plan:so[p['predictions'][0]['id']].__setitem__('group','f'*64))

    def test_omitted_label_veto(self):
        self.rejection(lambda p,r,s,so,g,plan:g.pop(p['predictions'][0]['id']))

    def test_original_review_score_forgery_veto(self):
        self.rejection(lambda p,r,s,so,g,plan:r['arms']['bridge_image_only'].__setitem__('correct',0))

    def test_pairwise_mcnemar_forgery_veto(self):
        self.rejection(lambda p,r,s,so,g,plan:r['paired_vs_text_only']['train_gate'].__setitem__('mcnemar_unadjusted_exact_p',0))

    def test_missing_original_arm_veto(self):
        self.rejection(lambda p,r,s,so,g,plan:p['predictions'][0]['arms'].pop('train_gate'))

    def test_duplicate_original_case_veto(self):
        self.rejection(lambda p,r,s,so,g,plan:p['predictions'][1].__setitem__('id',p['predictions'][0]['id']))

    def test_bogus_original_source_sha_veto(self):
        self.rejection(lambda p,r,s,so,g,plan:p.__setitem__('source_sha256','b'*64))

    def test_fake_grants_veto(self):
        self.rejection(lambda p,r,s,so,g,plan:r.__setitem__('authority','AUTHORIZED'))

    def test_nan_score_veto(self):
        self.rejection(lambda p,r,s,so,g,plan:p['predictions'][0]['arms']['train_gate'].__setitem__(0,float('nan')))

    def test_boolean_label_veto(self):
        self.rejection(lambda p,r,s,so,g,plan:g.__setitem__(p['predictions'][0]['id'],True))

    def test_jsonl_duplicate_field(self):
        with self.assertRaises(v.Rejected):v.read_jsonl(b'{"a":1,"a":2}\n')

    def test_jsonl_noncanonical_and_nonfinite(self):
        for b in [b'{"x":NaN}\n',b'{"x":1.0} \n',b'{"x":1}\n\n',b'[]\n']:
            with self.subTest(b=b),self.assertRaises((v.Rejected,TypeError,ValueError)):
                v.read_jsonl(b)

    def test_source_label_material_rejects_wrong_original_hash(self):
        with self.assertRaises(v.Rejected):
            v.verify_label_material(b'{}\n',b'{}\n',{'source_sha256':v.SOURCE_SHA,
                                                  'private_test_labels_sha256':v.sha(b'{}\n')})


if __name__=='__main__':unittest.main()
