"""Full saved-file mutation tests; run explicitly after a complete role study."""
import argparse
import json
from pathlib import Path
import unittest
from fbsde_role_audit import audit

ROOT=SOURCE=None

class ArtifactTests(unittest.TestCase):
    def mutate(self,name,change,message):
        p=ROOT/(name+'.json');raw=p.read_bytes()
        try:
            data=json.loads(raw);change(data);p.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError,message):audit(ROOT,SOURCE)
        finally:p.write_bytes(raw)

    def test_missing_cheap_control_rejects(self):
        self.mutate('plan',lambda x:x['arms'].remove('uniform_probe'),'controls')

    def test_alpha_renaming_tamper_rejects(self):
        self.mutate('priors',lambda x:x[0]['descriptions'][0].update(roles=[2,1,0]),'role mapping')

    def test_unobserved_truth_cannot_rewrite_prior(self):
        self.mutate('priors',lambda x:x[0]['head_priors'][0].__setitem__(0,.99),'prior')

    def test_changed_final_answer_rejects(self):
        self.mutate('old_none',lambda x:x[0].update(holder=17),'answer')

    def test_borrowed_source_observation_rejects(self):
        self.mutate('program_uniform_two',lambda x:next(r for r in x if r['checks'])['checks'][0].update(outcome=19),'revelation')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--study',type=Path,required=True);p.add_argument('--source',type=Path,required=True)
    a=p.parse_args();ROOT,SOURCE=a.study,a.source;unittest.main(argv=['role_artifact_checks'])
