"""Actual Torch cache/batch contracts; test tensors are NOT pretrained execution."""
import tempfile
import json
from pathlib import Path
import unittest
import torch
from fbsde_tracking_features import ParticipantFeatures, LOCAL, LEGACY
from fbsde_tracking import lexical_vector
from fbsde_tracking_study import run


class CacheTensorTests(unittest.TestCase):
    def store(self, profile=LOCAL):
        self.calls=[]
        def encode(keys):
            self.calls.append(list(keys))
            return torch.tensor([lexical_vector(k) for k in keys])
        return ParticipantFeatures(torch,encode,128,{'encoder':'fixture','scope':'a','generation':1},profile)

    def test_unique_misses_batched_and_original_slots_preserved(self):
        s=self.store(); a='First, SELF and OTHER swap books.'; b='Then, OTHER and SELF swap books.'
        x,r=s.get([a,b,a],s.binding)
        self.assertEqual(len(self.calls),1); self.assertEqual(r['unique_misses'],2)
        self.assertTrue(torch.equal(x[0],x[2])); self.assertEqual(r['slots'],[[0,0],[0,1],[0,0]])
        s.get(['Finally, SELF and OTHER swap books.'],s.binding)
        self.assertEqual(len(self.calls),1)

    def test_legacy_does_not_silently_use_new_quotient(self):
        s=self.store(LEGACY)
        s.get(['First, SELF and OTHER swap books.','Then, SELF and OTHER swap books.'],s.binding)
        self.assertEqual(len(self.calls),2)

    def test_returned_tensor_cannot_mutate_cached_feature(self):
        s=self.store(); keys=['First, SELF and OTHER swap books.']; x,_=s.get(keys,s.binding); expected=x.clone()
        x.zero_(); again,_=s.get(keys,s.binding)
        self.assertTrue(torch.equal(expected,again))

    def test_bad_binding_rejects_before_model_call(self):
        s=self.store()
        with self.assertRaisesRegex(ValueError,'binding'): s.get(['First, SELF and OTHER swap books.'],'stale')
        self.assertEqual(self.calls,[])

    def test_nonfinite_batch_does_not_populate_cache(self):
        s=self.store();s.encode_many=lambda keys: torch.full((len(keys),128),float('nan'))
        with self.assertRaisesRegex(ValueError,'finite'):s.get(['First, SELF and OTHER swap books.'],s.binding)
        self.assertEqual(s.entries,{})
        self.assertEqual(s.batches[0]['status'],'failed')

    def test_actual_generated_study_uses_only_training_features(self):
        with tempfile.TemporaryDirectory() as d:
            r=run(Path(d)/'study',feature_profile=LOCAL)
            self.assertEqual(r['summary']['verified_recurrent']['correct'],192)
            self.assertEqual(r['feature_audit']['proposal_unique_misses'],0)
            self.assertEqual(r['unique_encoded_texts'],15)
            self.assertFalse(r['real_pretrained_executed'])

class SourceAuditTensorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(); cls.root = Path(cls.temp.name)/'study'
        run(cls.root, feature_profile=LOCAL)
        cls.originals = json.loads((cls.root/'originals.json').read_text())

    @classmethod
    def tearDownClass(cls): cls.temp.cleanup()

    def test_saved_source_and_transitions_audit(self):
        from fbsde_tracking_feature_audit import audit
        self.assertEqual(audit(self.root,self.originals)['state_outputs_checked'],1536)

    def test_source_relabelling_even_after_hash_repair_rejects(self):
        from fbsde_tracking_feature_audit import audit
        p = self.root/'proposals.json'; original=p.read_bytes()
        try:
            rows=json.loads(original);rows[0]['source_id']=self.originals[1]['source_id']
            p.write_text(json.dumps(rows))
            with self.assertRaises(ValueError):audit(self.root,self.originals)
        finally:p.write_bytes(original)

    def test_claiming_denied_step_was_applied_rejects(self):
        from fbsde_tracking_feature_audit import audit
        p = self.root/'proposals.json'; original=p.read_bytes()
        try:
            rows=json.loads(original);rows[0].update(returned=False,cpu_ns=100_000_001)
            p.write_text(json.dumps(rows))
            with self.assertRaisesRegex(ValueError,'denied'):audit(self.root,self.originals)
        finally:p.write_bytes(original)

if __name__=='__main__':unittest.main()
