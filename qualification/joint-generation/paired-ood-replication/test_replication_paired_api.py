import unittest
from replication_paired_corruption import check_request,MODE
from paired_corruption import MODE as OLD_MODE
class ReplicationPairedAPITests(unittest.TestCase):
    def test_only_fixed_new_seed_mode_domain_without_generation(self):
        for fold in (0,1):
            for seed in (6701+10*fold,6702+10*fold):self.assertIsNone(check_request(fold,seed,MODE))
        for fold,seed,mode in [(0,4701,MODE),(0,5701,MODE),(0,6711,MODE),(1,6701,MODE),(False,6701,MODE),(0,6701,OLD_MODE),(2,6701,MODE)]:
            with self.assertRaises(ValueError):check_request(fold,seed,mode)
