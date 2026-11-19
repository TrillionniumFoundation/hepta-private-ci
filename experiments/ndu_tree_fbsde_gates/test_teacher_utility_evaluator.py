import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from teacher_utility_evaluator import evaluate
from teacher_study import emit

class TeacherUtilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory()
        cls.f=Path(cls.temp.name,'future.json');cls.s=Path(cls.temp.name,'seal.json')
        emit(str(cls.f),str(cls.s))
        cls.f_sha=hashlib.sha256(cls.f.read_bytes()).hexdigest()
        cls.s_sha=hashlib.sha256(cls.s.read_bytes()).hexdigest()
    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()
    def test_replayed_and_oracle_dominates(self):
        r=evaluate(self.f,self.f_sha,self.s,self.s_sha)
        self.assertEqual(r['n'],160)
        self.assertEqual(set(r['arms']),{'no_search','fixed_depth_1','exact_tree','frozen_gate','cheap_linear','learned_gate'})
        self.assertEqual(r['arms']['exact_tree']['expected_regret_to_exact_tree'],0.)
        self.assertTrue(all(v['expected_regret_to_exact_tree']>=-1e-13 for v in r['arms'].values()))
        self.assertFalse(r['production_accepted'])
        self.assertEqual(r['arms']['frozen_gate']['unsupported_class_abstentions'],90)
        self.assertEqual(r['arms']['learned_gate']['unsupported_class_abstentions'],0)
        self.assertEqual(r['arms']['cheap_linear']['unsupported_class_abstentions'],0)
    def test_unsupported_class_not_relabelled_as_stop(self):
        p=Path(self.temp.name,'unknown_output.json')
        s=json.loads(self.s.read_text());s['predictions']['learned_gate']['future-0']=7
        p.write_text(json.dumps(s))
        new_hash=hashlib.sha256(p.read_bytes()).hexdigest()
        scored=evaluate(self.f,self.f_sha,p,new_hash)
        self.assertEqual(scored['arms']['learned_gate']['unsupported_class_abstentions'],1)
        self.assertFalse(scored['p3_qualified'])
    def test_modified_seal_refused(self):
        p=Path(self.temp.name,'altered.json')
        s=json.loads(self.s.read_text());s['predictions']['learned_gate']['future-0']=1-s['predictions']['learned_gate']['future-0']
        p.write_text(json.dumps(s))
        with self.assertRaises(ValueError):evaluate(self.f,self.f_sha,p,self.s_sha)
    def test_invalid_scope_extra_label_refused(self):
        p=Path(self.temp.name,'future_mod.json')
        f=json.loads(self.f.read_text());f[0]['hidden_true_world']=[1,1];p.write_text(json.dumps(f))
        with self.assertRaises(ValueError):evaluate(p,hashlib.sha256(p.read_bytes()).hexdigest(),self.s,self.s_sha)
    def test_negative_authority_flag_refused(self):
        p=Path(self.temp.name,'flag.json')
        s=json.loads(self.s.read_text());s['production_accepted']=True;p.write_text(json.dumps(s))
        with self.assertRaises(ValueError):evaluate(self.f,self.f_sha,p,hashlib.sha256(p.read_bytes()).hexdigest())
    def test_duplicate_future_predictions_refused(self):
        p=Path(self.temp.name,'missing.json')
        s=json.loads(self.s.read_text());del s['predictions']['learned_gate']['future-0'];p.write_text(json.dumps(s))
        with self.assertRaises(ValueError):evaluate(self.f,self.f_sha,p,hashlib.sha256(p.read_bytes()).hexdigest())

if __name__=='__main__':unittest.main()
