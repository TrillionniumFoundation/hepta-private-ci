"""Boundary tests for inherited execution; these fixtures never claim real training."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import llm_inherited_runtime as inherited
import llm_runtime_pilot as runtime


class InheritedRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.inputs = dict(schema='hepta-smollm-training-input-v1',
            scope='public-smoke-fixtures', records=[dict(prompt='fixture query', expected_output='yes')])
        pilot = runtime.experiment_plan({'fixture': 'not material'})
        pilot['tasks'] = inherited.training_rows(self.inputs)
        self.parent = dict(schema=inherited.PARENT_SCHEMA, generation=3, operation_id='previous',
            directory='/explicit/parent', contract='a'*64, adapter='b'*64, file_sha256='c'*64)
        self.plan = dict(schema=inherited.SCHEMA, phase='train', operation_id='op-4', generation=4,
            parent=self.parent, runtime=pilot, inputs=self.inputs,
            inputs_sha256=hashlib.sha256(runtime.canonical(self.inputs)).hexdigest(),
            source_pins=inherited.source_pins(), authority=inherited.NO_AUTHORITY.copy())

    def test_exact_generation_and_explicit_bootstrap(self):
        inherited.validate_plan(self.plan)
        for bad in (1, 3, 5, True):
            value = copy.deepcopy(self.plan); value['generation'] = bad
            with self.subTest(generation=bad), self.assertRaises(ValueError):
                inherited.validate_plan(value)
        value = copy.deepcopy(self.plan); value.update(parent=None, generation=1)
        inherited.validate_plan(value)
        value['phase'] = 'infer'
        with self.assertRaisesRegex(ValueError, 'BOOTSTRAP_ONLY'):
            inherited.validate_plan(value)

    def test_inference_uses_parent_generation_and_original_request(self):
        value = copy.deepcopy(self.plan)
        value.update(phase='infer', generation=3,
                     inputs=dict(schema='hepta-smollm-inference-input-v1', request_id='op-4', prompt='next task'))
        inherited.validate_plan(value)
        for change in ({'request_id': 'different'}, {'expected_output': 'yes'}, {'prompt': ''}):
            bad = copy.deepcopy(value); bad['inputs'].update(change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                inherited.validate_plan(bad)

    def test_authority_source_gpu_and_budget_changes_refuse(self):
        for change in (lambda p:p['authority'].update(installation_authorized=True),
                       lambda p:p['authority'].update(installation_authorized=0),
                       lambda p:p['source_pins'].update(extra='a'*64),
                       lambda p:p['runtime'].update(backend='cuda'),
                       lambda p:p['runtime'].update(threads=5),
                       lambda p:p['runtime']['training_budget'].update(rss_bytes=17*1024**3)):
            bad = copy.deepcopy(self.plan); change(bad)
            with self.subTest(change=change), self.assertRaises(ValueError):
                inherited.validate_plan(bad)

    def test_parent_independent_pins_and_closed_descriptor(self):
        for change in ({'generation': True}, {'directory': '../relative'}, {'adapter': 'B'*64},
                       {'hepta_final_use': True}, {'schema': 'anything'}):
            value = dict(self.parent, **change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                inherited.validate_parent(value)

    def test_training_input_scope_duplicate_and_label_binding(self):
        bad = copy.deepcopy(self.inputs); bad['scope'] = 'independent-future-accepted'
        with self.assertRaises(ValueError): inherited.training_rows(bad)
        bad = copy.deepcopy(self.inputs); bad['records'] *= 2
        with self.assertRaisesRegex(ValueError, 'DUPLICATE'): inherited.training_rows(bad)
        bad = copy.deepcopy(self.plan); bad['inputs']['records'][0]['expected_output'] = 'no'
        with self.assertRaisesRegex(ValueError, 'DATASET_BINDING'): inherited.validate_plan(bad)

    def test_checked_input_rejects_hash_rewrite_and_duplicate_json(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)/'input.json'
            path.write_bytes(runtime.canonical(self.inputs))
            expected = runtime.file_sha(path)
            self.assertEqual(inherited.checked_json(path, expected), self.inputs)
            path.write_bytes(path.read_bytes()+b' ')
            with self.assertRaisesRegex(ValueError, 'INPUT_IDENTITY'):
                inherited.checked_json(path, expected)
            path.write_text('{"key":1,"key":2}')
            with self.assertRaisesRegex(ValueError, 'DUPLICATE_JSON'):
                inherited.checked_json(path, runtime.file_sha(path))


if __name__ == '__main__':
    unittest.main()
