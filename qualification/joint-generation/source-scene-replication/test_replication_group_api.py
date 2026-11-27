import unittest
from replication_group_data import heldout_dataset
class ReplicationGroupAPI(unittest.TestCase):
    def test_reject_arbitrary_or_old_noise_before_generation(self):
        for fold,seed in ((0,2701),(1,2711),(0,3711),(1,3701),(0,1701),(0,True),(0,3701.),(0,'3701')):
            with self.assertRaises(ValueError):heldout_dataset(fold,seed)
    def test_reject_fold_and_variant_before_generation(self):
        for fold,seed,variants in ((True,3701,6),(-1,3701,6),(2,3721,6),(0,3701,6.),(0,3701,1)):
            with self.assertRaises(ValueError):heldout_dataset(fold,seed,variants)
