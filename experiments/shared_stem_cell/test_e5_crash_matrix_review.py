"""Adversarial non-authoritative receipt checks; no model weights imported."""
from __future__ import annotations
import copy,json,unittest
from pathlib import Path
from e5_crash_matrix_review import review,Invalid
BASE=Path(__file__).parent
class Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.small=json.loads((BASE/'E5_CRASH_ATOMIC_LOCAL_64_20261014.json').read_bytes())
        cls.medium=json.loads((BASE/'E5_CRASH_ATOMIC_LOCAL_256_20261014.json').read_bytes())
    def data(self):return copy.deepcopy(self.small),copy.deepcopy(self.medium)
    def deny(self,modify):
        a,b=self.data();modify(a,b)
        with self.assertRaises((Invalid,ValueError,KeyError,TypeError)):review(a,b)
    def test_valid_but_deny_all(self):
        a,b=self.data();r=review(a,b);self.assertEqual(r['claimed_total_separate_sigkill_children'],14)
        self.assertFalse(r['independently_verified_OS_process_exits']);self.assertFalse(r['production_promotion_permitted'])
    def test_missing_cut(self):self.deny(lambda a,b:a['stage_observations'].pop())
    def test_wrong_signal(self):self.deny(lambda a,b:a['stage_observations'][0].update(child_exit_signal='TERM'))
    def test_wrong_return_code(self):self.deny(lambda a,b:a['stage_observations'][0].update(child_returncode=0))
    def test_early_publish_claim(self):self.deny(lambda a,b:a['stage_observations'][0].update(observed_step_after_crash=4))
    def test_after_commit_rollback(self):self.deny(lambda a,b:a['stage_observations'][-1].update(observed_step_after_crash=2))
    def test_missing_exact_replay(self):self.deny(lambda a,b:b.update(same_seed_four_step_reference_momentum_and_weights_bit_exact=False))
    def test_false_wal_proof(self):self.deny(lambda a,b:b.update(real_future_ndu_verified=True))
    def test_missing_middle_scale(self):self.deny(lambda a,b:b.update(logical_cells=128))
    def test_duplicate_stage(self):self.deny(lambda a,b:a['stage_observations'][2].update(failpoint='blob_partial'))
    def test_bad_signed_origin(self):self.deny(lambda a,b:a.update(independent_model_origin_verified=True))
    def test_nan_cpu(self):self.deny(lambda a,b:a.update(process_wall_ms=float('nan')))
if __name__=='__main__':unittest.main()
