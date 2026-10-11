"""Actual lexical/Head/control execution on explicit fixture rows, not real mmBERT."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fbsde_acquisition_study import run
from fbsde_acquisition_audit import audit
from fbsde_acquisition_data import INTENTS
from four_gate_common import digest


class AcquisitionTensorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(); cls.root = Path(cls.temp.name)/'run'
        cls.parts = {}
        for split, per_class in (('fit',3),('kernel',3),('selection',1),('validation',1),('test',2)):
            cls.parts[split] = [{'id':f'{split}-{label}-{i}', 'text':f'please {name} request fixture {split} {i}',
                                'label':label, 'text_sha256':digest(f'please {name} request fixture {split} {i}')}
                               for label,name in enumerate(INTENTS) for i in range(per_class)]
        # Only the publisher input is substituted; actual encoding, training,
        # lazy requests, solver and independent arithmetic audit all execute.
        with patch('fbsde_acquisition_study.load_publisher', return_value={}), \
             patch('fbsde_acquisition_study.partition', return_value=cls.parts):
            cls.result = run(cls.root, backend='hashing_reference_v1')

    @classmethod
    def tearDownClass(cls): cls.temp.cleanup()

    def test_complete_model_and_controller_chain(self):
        self.assertEqual(self.result['test_source_count'], 16)
        self.assertEqual(len(self.result['metrics']), 9)
        self.assertTrue(self.result['compiled_vs_bsde_predictions_equal'])
        self.assertFalse(self.result['general_continuous_fbsde_claimed'])
        self.assertFalse(json.loads((self.root/'physical.json').read_text())['real_pretrained_weights_executed'])

    def test_arithmetic_audit_independent_of_models(self):
        checked = audit(self.root, self.parts)
        self.assertTrue(checked['original_arithmetic_recomputed'])
        self.assertFalse(checked['physical_execution_authenticated'])

    def test_unrequested_view_mutant_rejected(self):
        file = self.root/'test-initial_only.jsonl'; old = file.read_bytes()
        try:
            rows = [json.loads(x) for x in old.splitlines()]; rows[0]['events'][0]['view'] = 2
            file.write_text('\n'.join(json.dumps(r) for r in rows)+'\n')
            with self.assertRaisesRegex(ValueError, 'unrequested'):
                audit(self.root, self.parts)
        finally: file.write_bytes(old)

    def test_label_mutant_rejected(self):
        changed = {k: [dict(r) for r in v] for k, v in self.parts.items()}
        changed['test'][0]['label'] = 7
        with self.assertRaisesRegex(ValueError, 'labels differ'): audit(self.root, changed)

    def test_probability_and_cost_mutants_rejected(self):
        file = self.root/'test-full_only.jsonl'; old = file.read_bytes()
        try:
            rows = [json.loads(x) for x in old.splitlines()]; rows[0]['modeled_cost'] = 0
            file.write_text('\n'.join(json.dumps(r) for r in rows)+'\n')
            with self.assertRaisesRegex(ValueError, 'cost'): audit(self.root, self.parts)
        finally: file.write_bytes(old)

    def test_kernel_observation_mutant_rejected(self):
        file = self.root/'kernel-fit-observations.json'; old = file.read_bytes()
        try:
            rows = json.loads(old); rows[0]['symbols'][0] = (rows[0]['symbols'][0]+1)%8
            file.write_text(json.dumps(rows))
            with self.assertRaisesRegex(ValueError, 'kernel symbol'): audit(self.root, self.parts)
        finally: file.write_bytes(old)

    def test_cli_outputs_are_write_once(self):
        with self.assertRaises(FileExistsError): run(self.root)


if __name__ == '__main__': unittest.main()
