"""Prospective selection, uncertainty and pre-generation freeze gates."""
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from .campaign import choose_q24, parameter_hash, protocol
from .confirmation import confirm, interval


class CampaignTests(unittest.TestCase):
    def test_forced_nonzero_preserves_better_zero_and_fails_validation_gate(self):
        weights = dict(w=np.zeros((65,1)).tolist(), b=[0.], v=np.zeros((1,4)).tolist(), c=[0.]*4)
        checkpoint = dict(norm=dict(mean=[0.]*65,scale=[1.]*65),weights=weights)
        candidates = []
        for update in (0,100,300,1000,6000):
            current = dict(weights,c=[0.,0.,.01 if update else 0.,0.])
            candidates.append(dict(update=update, weights=current, parameter_sha256=parameter_hash(current),
                                   validation_regret=.4 if update else 0.))
        receipt = dict(candidates=candidates,selected_update=0)
        data = dict(rows=[dict(features=[0.]*65, prior=[0.,.5,.5,.1], teacher=[0.,.7,.3,.2], feasible=[True]*4)])
        models, selection = choose_q24(checkpoint,receipt,data)
        self.assertEqual(selection["overall_update"],0)
        self.assertEqual(selection["nonzero_update"],100)
        self.assertFalse(selection["nonzero_improves_zero"])
        self.assertEqual(models["update6000"]["selected_update"],6000)

    def test_seed_t_interval_uses_training_replications(self):
        result = interval([1.,2.,3.,4.,5.])
        self.assertEqual(result["df"],4)
        self.assertAlmostEqual(result["mean"],3.)
        self.assertAlmostEqual(result["standard_error"],np.sqrt(.5))
        self.assertAlmostEqual(result["lower"],1.036756838522439,places=10)

    def test_confirm_requires_freeze_before_creating_output(self):
        with tempfile.TemporaryDirectory() as directory:
            prepared = Path(directory)/"prepared"
            prepared.mkdir()
            (prepared/"PREPARED_MANIFEST.json").write_text(json.dumps(dict(files={},source_sha256={})))
            receipt = Path(directory)/"unverified.json"
            receipt.write_text(json.dumps(dict(repository="TrillionniumFoundation/hepta-private-ci",commit="0"*40)))
            out = Path(directory)/"confirmation"
            with self.assertRaises(ValueError):
                confirm(prepared,out,receipt)
            self.assertFalse(out.exists())

    def test_prespecified_campaign_is_complete(self):
        spec = protocol()
        self.assertEqual(len(spec["seeds"]),5)
        self.assertEqual(spec["test_sessions"]*len(spec["seeds"])*len(spec["policies"])*2,3840)
        self.assertEqual(spec["primary_cpu_price"],1.)
        self.assertEqual(spec["amortization_sessions"],[128,1000,10000])


if __name__ == "__main__":
    unittest.main()
