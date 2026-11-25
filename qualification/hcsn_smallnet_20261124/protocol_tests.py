"""Small protocol controls; every data request is mapped to smoke sources.

This fixture tests source/receipt custody and fresh checkpoint loading. Its
explicit data substitution is not a claim about formal holdout independence.
"""

from copy import copy, deepcopy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import torch

from . import train


class ProtocolTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(1)
        temporary = tempfile.TemporaryDirectory(prefix='hcsn-protocol-smoke-only-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.original_data = train.make_data

    def protocol(self):
        config = json.loads((train.HERE / 'protocol.json').read_text())
        config['experiment_id'] = 'TEST-ONLY-PROTOCOL-SMOKE-SUBSTITUTE'
        config['test_fixture'] = {
            'source_mapping': {'train': 'smoke_train', 'dev': 'smoke_dev', 'test': 'smoke_dev'},
            'formal_holdout_constructed': False,
            'claim': 'custody mechanics only; dev and test deliberately share smoke data'}
        config['independent_neurons'], config['seeds'] = [8], [1101]
        config['arms'] = [deepcopy(config['arms'][0])]
        config['precision'], config['backend'] = 'float64', 'dense'
        config['data'].update(length=10, train_per_source=2, dev_per_source=2,
                              test_per_source=2, train_sources=4, dev_sources=2, test_sources=2)
        config['training'].update(batch_size=2, max_updates=1, development_every=1,
                                  train_cpu_seconds=10.)
        self.manifest = self.root / 'manifest.json'
        (self.root / 'protocol.json').write_text(json.dumps(config))
        with patch.object(train, 'HERE', self.root):
            return train.freeze(self.manifest)

    def smoke_data(self, split, **kwargs):
        mapping = {'train': 'smoke_train', 'dev': 'smoke_dev', 'test': 'smoke_dev'}
        if split not in mapping:
            raise AssertionError('unexpected data request in protocol-only test')
        return self.original_data(mapping[split], **kwargs)

    def fitted(self):
        p = self.protocol()
        output = self.root / 'runs'
        attempt = output / train.expected_attempts(p)[0]
        with patch.object(train, 'make_data', side_effect=self.smoke_data):
            result = train.fit(p, attempt, arm=p['arms'][0], neurons=8, seed=1101)
        self.assertEqual(result['status'], 'completed', result['error'])
        train.seal(p, output)
        return p, output, attempt

    def test_frozen_one_slot_seals_and_reloads_before_smoke_only_test(self):
        p, output, attempt = self.fitted()
        reloaded = train.load_protocol(self.manifest)
        self.assertEqual(train.protocol_digest(reloaded), train.protocol_digest(p))
        with patch.object(train, 'make_data', side_effect=self.smoke_data) as data_reader, \
                patch.object(train, 'SmallHCSN', wraps=train.SmallHCSN) as constructors:
            train.final_test(reloaded, output)
        constructors.assert_called_once()
        self.assertEqual([call.args[0] for call in data_reader.call_args_list], ['test'])
        raw = json.loads((attempt / 'test_predictions.json').read_text())
        self.assertTrue(all(value.startswith('smoke_dev:') for value in raw['ids']))
        self.assertEqual(len(raw['prefix_logits']), 10)
        self.assertEqual(len(raw['initial_prefix_logits']), 10)
        self.assertEqual(len(raw['late_step']), len(raw['labels']))
        self.assertEqual(raw['protocol_sha256'], train.protocol_digest(p))
        self.assertTrue((output / 'FINAL_CLAIM').exists())
        final = json.loads((output / 'FINAL_RESULTS.json').read_text())
        self.assertEqual(final['experiment_id'], 'TEST-ONLY-PROTOCOL-SMOKE-SUBSTITUTE')
        self.assertEqual(final['results'][0]['status'], 'evaluated')

    def test_changed_checkpoint_refused_before_any_test_data_or_claim(self):
        p, output, attempt = self.fitted()
        with (attempt / 'checkpoint.pt').open('ab') as handle:
            handle.write(b'test-only-post-seal-byte-change')
        with patch.object(train, 'make_data', side_effect=AssertionError('test data opened')) as data_reader:
            with self.assertRaisesRegex(ValueError, 'checkpoint changed'):
                train.final_test(p, output)
        data_reader.assert_not_called()
        self.assertFalse((output / 'FINAL_CLAIM').exists())
        self.assertFalse((output / 'FINAL_RESULTS.json').exists())

    def test_dependency_byte_change_is_detected_without_touching_upstream(self):
        p = self.protocol()
        module = 'qualification.hcsn_training.population_generator'
        self.assertIn(module, p['source_hashes'])
        self.assertIn('qualification.hcsn_smallnet_20261124.campaign', p['source_hashes'])
        self.assertFalse(any('editing' in name or 'adaptation' in name for name in p['source_hashes']))
        original_find = importlib.util.find_spec
        spec = original_find(module)
        altered = self.root / 'changed_population_generator.py'
        altered.write_bytes(Path(spec.origin).read_bytes() + b'\n# Test-only dependency byte change.\n')

        def changed_spec(name, package=None):
            if name == module:
                result = copy(spec)
                result.origin = str(altered)
                return result
            return original_find(name, package)

        with patch.object(importlib.util, 'find_spec', side_effect=changed_spec):
            with self.assertRaisesRegex(ValueError, 'dependency changed'):
                train.load_protocol(self.manifest)


if __name__ == '__main__':
    unittest.main()
