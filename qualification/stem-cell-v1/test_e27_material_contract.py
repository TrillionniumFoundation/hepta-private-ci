"""E27 material owner must work without Torch or whole legacy Stem checkout."""

from pathlib import Path
import os
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parent
DONOR_SHA = '50f9a77cecb1ddc18b4d674db15a22a873726663'


class IsolatedMaterialOwnerContract(unittest.TestCase):
    def test_material_owner_import_and_original_slate_without_site_packages(self):
        script = '''
import sys
import e27_reader_owner as owner
assert 'torch' not in sys.modules
assert 'transformers' not in sys.modules

def rows(role, count):
    return [dict(paragraph=f'{role}-{i}', question=f'q-{q}',
                 answer=f'a-{a}', label=int(a == 1),
                 idx=dict(paragraph=i, question=q, answer=a))
            for i in range(count) for q in range(2) for a in range(3)]
train, held, gold, meta = owner.material_owner(rows('train',48),rows('validation',8))
assert len(train['groups']) == 48 and len(held['groups']) == 8
assert len(gold['cases']) == 48
assert not any('label' in c for g in held['groups'] for q in g['questions']
               for c in q['candidates'])
assert 'torch' not in sys.modules
'''
        env = {**os.environ, 'PYTHONPATH': str(ROOT), 'PYTHONNOUSERSITE': '1'}
        completed = subprocess.run([sys.executable, '-S', '-c', script],
                                   env=env, capture_output=True, text=True,
                                   timeout=20, check=False)
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_real_workflow_requires_pinned_external_reader_source_closure(self):
        workflow = (ROOT/'hepta-e27-original-answer-token-cell.yml').read_text()
        self.assertEqual(workflow.count(f'ref: {DONOR_SHA}'), 4)
        self.assertEqual(workflow.count(f'" = {DONOR_SHA}'), 4)
        self.assertIn('python "$DONOR_ROOT/public_encoder_probe.py" --acquire-public',workflow)
        self.assertIn('PYTHONPATH: qualification/stem-cell-v1:e27-donor/qualification/stem-cell-v1',workflow)
        self.assertIn("assert 'torch' not in sys.modules",workflow)


if __name__ == '__main__':
    unittest.main()
