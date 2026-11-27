"""Contract regressions only; no real HPCA task evidence."""
import unittest
from dataclasses import replace
from study import ARMS, ContractError, paired_evidence
from test_study import row

def panel(seed, family, episode):
    return [row(arm,episode_id=episode,seed=seed,family=family,
                gross_value=2.0 if arm=="routed" else 1.0) for arm in ARMS]

class CohortRetentionTests(unittest.TestCase):
    def test_mismatched_family_population_rejected(self):
        with self.assertRaisesRegex(ContractError,"family/episode roster"):
            paired_evidence(panel(11,"dense_ACT","a11")+panel(17,"sparse_CTRL","c17"))
    def test_unequal_episode_counts_rejected(self):
        with self.assertRaisesRegex(ContractError,"family/episode roster"):
            paired_evidence(panel(11,"ACT","a11")+panel(11,"ACT","extra11")+panel(17,"ACT","a17"))
    def test_balanced_family_roster_keeps_seed_randomization_unit(self):
        x=[r for seed in (11,17) for family in ("dense_ACT","sparse_CTRL")
           for r in panel(seed,family,f"{seed}-{family}")]
        got=paired_evidence(x)
        self.assertEqual((got["blocks"],got["seed_clusters"]),(4,2))
        self.assertAlmostEqual(got["mean_net_difference"],1.0)
        self.assertEqual(got["one_sided_exact_signflip_p"],0.25)
    def test_missing_scalar_retention_is_incomplete(self):
        x=[replace(r,retention_value=None) if r.arm=="scalar" else r
           for r in panel(11,"ACT","a11")]
        self.assertIsNone(paired_evidence(x)["mean_retention_difference"])
    def test_missing_no_eligibility_retention_is_incomplete(self):
        x=[replace(r,retention_value=None) if r.arm=="no_eligibility" else r
           for r in panel(11,"ACT","a11")]
        self.assertIsNone(paired_evidence(x)["mean_retention_difference"])
    def test_complete_four_arm_retention_unmodified(self):
        x=paired_evidence(panel(11,"ACT","a11"))
        self.assertEqual(x["mean_retention_difference"],0.0)
        self.assertEqual(x["qualification"],"RECEIPTS_NOT_EXTERNALLY_ATTESTED")

if __name__=="__main__": unittest.main()
