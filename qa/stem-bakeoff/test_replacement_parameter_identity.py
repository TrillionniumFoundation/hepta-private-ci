"""Synthetic tensors and receipt validation; no pretrained model execution."""
import copy
import unittest
from unittest.mock import patch

import replacement_parameter_identity as identity


def receipt():
    before = dict(sha256='a'*64, parameter_bytes=16,
                  parameter_objects=1, parameter_names=2)
    return dict(method=identity.METHOD, scope=identity.SCOPE, before=before,
                after=copy.deepcopy(before), bytes_hashed=32, hash_cpu_ns=0,
                hash_wall_ns=1, chunk_bytes=identity.CHUNK_BYTES,
                byte_cap=identity.MAX_PARAMETER_BYTES)


class ReceiptTests(unittest.TestCase):
    def test_self_reported_consistency_only(self):
        self.assertTrue(identity.validate_identity_receipt(receipt()))
        # A fabricated equal digest is structurally valid, not authenticated.
        row = receipt()
        row['before']['sha256'] = row['after']['sha256'] = 'b'*64
        self.assertTrue(identity.validate_identity_receipt(row))

    def test_mismatch_and_cost_tampering_rejected(self):
        changes = [('after', {}), ('bytes_hashed', 16), ('byte_cap', 0),
                   ('chunk_bytes', True), ('hash_cpu_ns', -1),
                   ('hash_wall_ns', False), ('scope', 'attested')]
        for key, value in changes:
            with self.subTest(key=key):
                row = receipt()
                row[key] = value
                self.assertFalse(identity.validate_identity_receipt(row))

    def test_invalid_census_rejected(self):
        for key, value in [('parameter_bytes', 0), ('parameter_bytes', 17),
                           ('parameter_bytes', identity.MAX_PARAMETER_BYTES+4),
                           ('parameter_names', 0), ('parameter_objects', True),
                           ('sha256', 'z'*64)]:
            with self.subTest(key=key, value=value):
                row = receipt()
                row['before'][key] = row['after'][key] = value
                self.assertFalse(identity.validate_identity_receipt(row))

    def test_after_census_strict_types(self):
        for key in ('parameter_bytes', 'parameter_objects', 'parameter_names'):
            row = receipt()
            row['after'][key] = float(row['after'][key])
            self.assertFalse(identity.validate_identity_receipt(row))
        row = receipt()
        row['after']['parameter_objects'] = True
        self.assertFalse(identity.validate_identity_receipt(row))

    def test_nonempty_object_payload_lower_bound(self):
        row = receipt()
        row['before']['parameter_objects'] = row['after']['parameter_objects'] = 5
        row['before']['parameter_names'] = row['after']['parameter_names'] = 5
        self.assertFalse(identity.validate_identity_receipt(row))


class TensorTests(unittest.TestCase):
    """Requires real CPU torch. Intentionally no fake/stub or silent skip."""
    def setUp(self):
        import torch
        self.torch = torch

    def model(self, tensor):
        model = self.torch.nn.Module()
        model.register_parameter('weight', self.torch.nn.Parameter(tensor))
        return model

    def test_alias_order_and_value_identity(self):
        t = self.torch
        first = self.model(t.arange(8, dtype=t.float32))
        first.register_parameter('alias', first.weight)
        second = t.nn.Module()
        second.register_parameter('alias', t.nn.Parameter(t.arange(8, dtype=t.float32)))
        second.register_parameter('weight', second.alias)
        a = identity.parameter_identity(first)
        self.assertEqual(a, identity.parameter_identity(second))
        self.assertEqual((a['parameter_bytes'], a['parameter_names'], a['parameter_objects']), (32, 2, 1))
        with t.no_grad():
            second.weight[0] += 1
        self.assertNotEqual(a['sha256'], identity.parameter_identity(second)['sha256'])

    def test_unsupported_and_cap_before_read(self):
        t = self.torch
        for tensor in [t.empty(0), t.ones(2, dtype=t.float64), t.ones(2, 3).T,
                       t.empty(2, device='meta')]:
            with self.subTest(shape=tuple(tensor.shape), dtype=tensor.dtype):
                with self.assertRaises(ValueError):
                    identity.parameter_identity(self.model(tensor))
        with patch.object(identity, 'MAX_PARAMETER_BYTES', 4):
            with self.assertRaisesRegex(ValueError, 'cap'):
                identity.parameter_identity(self.model(t.ones(2)))

    def test_chunking_does_not_change_digest(self):
        model = self.model(self.torch.arange(20, dtype=self.torch.float32))
        expected = identity.parameter_identity(model)
        with patch.object(identity, 'CHUNK_BYTES', 7):
            self.assertEqual(expected, identity.parameter_identity(model))


if __name__ == '__main__':
    unittest.main()
