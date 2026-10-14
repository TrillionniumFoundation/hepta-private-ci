import hashlib
import math
import struct
import unittest

import e0_feature_normalization as m


class NormalizationTests(unittest.TestCase):
    def test_raw_range_above_8_is_scaled_without_clipping(self):
        raw = struct.pack('>4f', 0.25, 31.0, -17.0, 0.5)
        norm, meta = m.normalize_feature_bytes(raw)
        self.assertEqual(meta['shift'], 3)
        self.assertEqual(struct.unpack('>4f', norm), (0.03125, 3.875, -2.125, 0.0625))
        self.assertNotEqual(meta['raw_sha256'], meta['normalized_sha256'])
        self.assertFalse(meta['lossless_or_semantically_neutral'])
        self.assertFalse(meta['production_authorized'])

    def test_repeated_raw_bytes_are_deterministic(self):
        raw = struct.pack('>4f', 12.0, -6.0, 2.0, 0.25)
        self.assertEqual(m.normalize_feature_bytes(raw), m.normalize_feature_bytes(raw))

    def test_shift_is_smallest_safe_dyadic_exponent(self):
        for x, expected in [(4.0,0), (4.0+1/1024,1), (8.0,1),
                            (8.0+1/1024,2), (16.0,2), (16.01,3)]:
            with self.subTest(x=x):
                raw = struct.pack('>f', x)
                _, mta = m.normalize_feature_bytes(raw)
                self.assertEqual(mta['shift'], expected)

    def test_nonfinite_float32_refused(self):
        for value in (math.nan, math.inf, -math.inf):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, 'nonfinite raw'):
                    m.normalize_feature_bytes(struct.pack('>f', value))

    def test_bad_geometry_and_types_refused(self):
        for raw in (b'', b'abc', 'text', b'\0' * (4*(m.MAX_WIDTH+1))):
            with self.subTest(length=len(raw)):
                with self.assertRaisesRegex(ValueError, 'geometry'):
                    m.normalize_feature_bytes(raw)

    def test_observed_tail_not_silently_truncated(self):
        raw=struct.pack('>768f', *([0.0]*767+[32.0]))
        normalized, meta=m.normalize_feature_bytes(raw)
        self.assertEqual(meta['shift'], 3)
        self.assertEqual(m.choose_diagnostic_tail_index(normalized, 256), 767)

    def test_zero_tail_refused_for_diagnostic(self):
        normalized = struct.pack('>768f', *([0.0]*768))
        with self.assertRaisesRegex(ValueError, 'no Q24-representable'):
            m.choose_diagnostic_tail_index(normalized, 256)

    def test_tail_selected_from_actual_maximum_not_hardcoded_last(self):
        source=[0.0]*768
        source[600]=-0.2
        source[767]=0.000001
        normalized,_=m.normalize_feature_bytes(struct.pack('>768f', *source))
        self.assertEqual(m.choose_diagnostic_tail_index(normalized, 256), 600)

    def test_policy_digest_matches_fixed_domain(self):
        self.assertEqual(m.POLICY_DIGEST, hashlib.sha256(m.POLICY_DOMAIN).hexdigest())
        self.assertNotEqual(m.POLICY_DIGEST, '0'*64)

if __name__ == '__main__':
    unittest.main()
