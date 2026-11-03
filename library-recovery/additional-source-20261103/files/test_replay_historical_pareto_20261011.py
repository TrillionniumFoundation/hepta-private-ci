"""Non-LLM regression checks for SHA-pinned historical Pareto accounting."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import replay_historical_pareto_20261011 as m

ROOT=Path('/mnt/data')

class FrozenReaderParetoTests(unittest.TestCase):
 def test_original_96_executions_and_manifest_identity(self):
  info=m.build(ROOT)
  self.assertEqual(set(info['model_pairs']),set(m.MODELS))
  self.assertEqual(sum(z['model_answer_count'] for z in info['model_pairs'].values()),96)
  self.assertEqual(sum(z['manifest_items'] for z in info['model_pairs'].values()),42)
  self.assertFalse(info['production_accepted'])

 def test_same_reader_both_outcomes_and_costs_reconcile(self):
  q=m.build(ROOT)['model_pairs']['qwen-3b']
  d={v['arm']:v for v in q['arms']}
  self.assertEqual((d['organized']['strict_correct'],d['organized']['correct_with_full_chain']),(8,4))
  self.assertEqual(d['hybrid']['input_tokens'],10806)
  self.assertEqual(d['organized']['input_tokens'],5179)
  self.assertEqual(set(q['descriptive_pareto']['non_dominated']),{'empty','organized'})
  self.assertFalse(d['program_support']['eligible_annotation_blind'])

 def test_duplicate_or_edited_scored_rows_fail(self):
  n='qwen-3b'; fn,checksum=m.MODELS[n]
  files=m.read_archive(ROOT/fn,checksum)
  tampered=dict(files)
  rows=json.loads(files['run/scored-answers.json'])
  rows[0]['answer']='fabricated answer [E999]'
  tampered['run/scored-answers.json']=json.dumps(rows).encode()
  with patch.object(m,'read_archive',return_value=tampered):
   with self.assertRaises(ValueError):
    m.extract(ROOT/fn,checksum)

 def test_rejects_unpinned_outer_archive(self):
  fn,expected=m.MODELS['smol-1.7b']
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/fn
   p.write_bytes((ROOT/fn).read_bytes()+b'X')
   with self.assertRaises(ValueError):
    m.read_archive(p,expected)

if __name__=='__main__':unittest.main()
