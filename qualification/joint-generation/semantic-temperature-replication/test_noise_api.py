import unittest
from validation_noise import validation_noise
class NoiseAPITests(unittest.TestCase):
    def test_only_two_prespecified_validation_noise_seeds(self):
        for seed in ('test',303,999,True):
            with self.assertRaises(ValueError):validation_noise(seed)
    def test_only_fixed_six_variants(self):
        for variants in (1,0,6.,True):
            with self.assertRaises(ValueError):validation_noise(9001,variants)
