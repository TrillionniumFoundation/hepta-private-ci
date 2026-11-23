import unittest

import torch

from .encoders import EconomyEncoder


class EncoderContract(unittest.TestCase):
    def test_causal_prefix_is_unchanged_after_future_x_or_clock_edit(self):
        rng=torch.Generator().manual_seed(519)
        x=torch.randn(4,6,8,dtype=torch.float64,generator=rng)
        dt=torch.full((4,6),.48,dtype=torch.float64)
        for mode in ("lif","attention","audio"):
            model=EconomyEncoder(mode,8,10)
            out=model.features(model.origin(),x,dt)
            xp=x.clone();xp[:,3:]=200
            tp=dt.clone();tp[:,3:]=70
            other=model.features(model.origin(),xp,tp)
            torch.testing.assert_close(out[:,:3],other[:,:3],rtol=0,atol=0)
            if mode=="lif":
                self.assertEqual(set(out[:,:,8:].unique().tolist()),{0.,1.})
            if mode!="audio":
                theta=model.origin().requires_grad_()
                loss=model.features(theta,x,dt)[:,:,8:].square().mean()
                gradient=torch.autograd.grad(loss,theta)[0]
                self.assertTrue(torch.isfinite(gradient).all() and gradient.ne(0).all())

    def test_counts(self):
        data=[("audio",0,27),("lif",72,54),("attention",297,54)]
        for mode,frozen,readout in data:
            counts=EconomyEncoder(mode,8,3).counts("keep")
            self.assertEqual((counts["frozen_projections"],counts["svd_trainable"]),(frozen,readout))
