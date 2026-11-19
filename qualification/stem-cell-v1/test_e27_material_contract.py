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
        workflow = (ROOT.parents[1]/'.github/workflows/hepta-e27-original-answer-token-cell.yml').read_text()
        self.assertEqual(workflow.count(f'ref: {DONOR_SHA}'), 4)
        self.assertEqual(workflow.count(f'" = {DONOR_SHA}'), 4)
        self.assertIn('python "$DONOR_ROOT/public_encoder_probe.py" --acquire-public',workflow)
        self.assertIn('PYTHONPATH: qualification/stem-cell-v1:e27-donor/qualification/stem-cell-v1',workflow)
        self.assertIn("assert 'torch' not in sys.modules",workflow)

    def test_cost_bounded_train_uses_complete_source_paragraphs_without_labels(self):
        from e27_reader_owner import select_groups
        def rows(n_groups, *, n_questions, n_answers, start=0):
            return [dict(
                paragraph=f'case-{start + i}', question=f'q-{q}',
                answer=f'a-{a}', label=int(a % 2 == 1),
                idx=dict(paragraph=start + i, question=q, answer=a),
            ) for i in range(n_groups)
              for q in range(n_questions)
              for a in range(n_answers)]
        # Old SHA-only selection can overshoot 288 questions and 1,200 answers.
        # Cost-first must retain whole paragraphs, NOT silently cut candidates.
        original = rows(60, n_questions=9, n_answers=8)
        original += rows(52, n_questions=2, n_answers=3, start=1000)
        selected, available = select_groups(original, split='train', limit=48)
        self.assertEqual((len(selected), available), (48, 112))
        self.assertEqual([len(x['questions']) for x in selected], [2] * 48)
        self.assertEqual(sum(len(q['candidates']) for x in selected
                             for q in x['questions']), 288)
        flipped = [dict(r, label=1 - r['label']) for r in original]
        changed, _ = select_groups(flipped, split='train', limit=48)
        self.assertEqual([x['group_id'] for x in selected],
                         [x['group_id'] for x in changed])
        self.assertEqual([[q['question_id'] for q in g['questions']] for g in selected],
                         [[q['question_id'] for q in g['questions']] for g in changed])
        self.assertTrue(all(len(q['candidates']) == 3 for g in selected
                            for q in g['questions']))

    def test_training_budget_remains_fail_closed_when_no_complete_fortyeight(self):
        from e27_reader_owner import select_groups
        full = [dict(paragraph=f'large-{i}', question=f'q-{q}', answer=f'a-{a}',
                     label=int(a == 1),
                     idx=dict(paragraph=i, question=q, answer=a))
                for i in range(48) for q in range(16) for a in range(8)]
        with self.assertRaisesRegex(ValueError, 'within registered 288-question/1200-answer caps'):
            select_groups(full, split='train', limit=48)

if __name__ == '__main__':
    unittest.main()
