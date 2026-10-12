"""Mutation checks consume a complete current study; run AFTER the study in CI.

No source observation or prediction is recomputed by a neural model here. Tests
mutate only a temporary copy; the original observations are never rewritten.
"""
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from fbsde_outcome_audit import audit


class OriginalOutcomeArtifactTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source=Path(os.environ.get('HEPTA_OUTCOME_EVIDENCE','outcome-study'))
        if not (cls.source/'results.json').is_file():raise ValueError('complete current outcome-study required')
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/'copy';shutil.copytree(self.source,self.root)
    def change(self,name,edit):
        p=self.root/(name+'.json');r=json.loads(p.read_text());edit(r);p.write_text(json.dumps(r))
    def test_complete_original_audits(self):
        self.assertEqual(audit(self.root)['audited_outputs'],3024)
    def test_changed_teacher_gain_rejects(self):
        self.change('teacher-train',lambda r:r[0].__setitem__('outcome_gain',2.))
        with self.assertRaisesRegex(ValueError,'teacher gains'):audit(self.root)
    def test_changed_heldout_target_rejects(self):
        def edit(r):k=next(iter(r));r[k]=(r[k]+1)%3
        self.change('targets',edit)
        with self.assertRaisesRegex(ValueError,'targets'):audit(self.root)
    def test_cherry_picked_outputs_reject(self):
        self.change('outcome_outcome',lambda r:r.pop())
        with self.assertRaisesRegex(ValueError,'paired arms'):audit(self.root)
    def test_changed_decoded_answer_rejects(self):
        self.change('one_step',lambda r:r[0].__setitem__('text','Invented.'))
        with self.assertRaisesRegex(ValueError,'decoded answer'):audit(self.root)
    def test_unpaid_final_cpu_rejects(self):
        self.change('results',lambda r:r['summary']['test']['two_step'].__setitem__('cpu_ns',0))
        with self.assertRaisesRegex(ValueError,'score or cost'):audit(self.root)
    def test_relabelled_training_file_rejects(self):
        self.change('teacher-train',lambda r:r[0].__setitem__('source_id','test:0:0'))
        with self.assertRaisesRegex(ValueError,'split leakage'):audit(self.root)

if __name__=='__main__':unittest.main()
