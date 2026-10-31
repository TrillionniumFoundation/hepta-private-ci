"""Fail-closed finite-volume geometry/rate admission, not event-quality proof.

These regressions concern only the declared torch dtype, not a completed
physical memory/Selective Copy/MQAR or native Rust/GPU admission gate.
"""
import math
import unittest

import torch

from .distribution_kernel import Grid, make_flow


class GridDtypeResolutionTests(unittest.TestCase):
    def test_float32_adjacent_boundary_collapses_eight_cells(self):
        # One representable step above lower still cannot encode eight cells.
        low=torch.tensor(-2.,dtype=torch.float32)
        boundary=torch.nextafter(low,torch.tensor(float('inf'),dtype=low.dtype))
        with self.assertRaisesRegex(ValueError,'Cell grid is unresolved'):
            make_flow(torch.tensor(.1,dtype=low.dtype),.5,boundary,low,.3,Grid())

    def test_even_two_cells_must_be_distinguishable(self):
        low=torch.tensor(-2.,dtype=torch.float32)
        boundary=torch.nextafter(low,torch.tensor(float('inf'),dtype=low.dtype))
        with self.assertRaisesRegex(ValueError,'Cell grid is unresolved'):
            make_flow(torch.tensor(.1,dtype=low.dtype),.5,boundary,low,.3,
                      Grid(cells=2))

    def test_float32_distinct_grid_with_infinite_diffusion_rate_refuses(self):
        grid=Grid(lower=0.)
        b=torch.tensor(1e-35,dtype=torch.float32)
        reset=torch.tensor(4e-36,dtype=torch.float32)
        with self.assertRaisesRegex(ValueError,'Nonfinite finite-volume rate'):
            make_flow(torch.tensor(.1,dtype=torch.float32),.5,b,reset,.3,grid)

    def test_small_positive_refractory_mean_does_not_return_infinite_rate(self):
        p=torch.tensor(.1,dtype=torch.float32)
        with self.assertRaisesRegex(ValueError,'Nonfinite finite-volume rate'):
            make_flow(p,.5,.8,-.1,torch.tensor(1e-40,dtype=torch.float32),
                      Grid())

    def test_one_bad_batch_member_invalidates_whole_flow(self):
        dtype=torch.float32
        low=torch.tensor(-2.,dtype=dtype)
        bad=torch.nextafter(low,torch.tensor(float('inf'),dtype=dtype))
        boundary=torch.stack((bad,torch.tensor(.8,dtype=dtype)))
        reset=torch.stack((low,torch.tensor(-.1,dtype=dtype)))
        with self.assertRaisesRegex(ValueError,'Cell grid is unresolved'):
            make_flow(torch.tensor(.1,dtype=dtype),.5,boundary,reset,.3,Grid())

    def test_nominal_f32_f64_and_no_diffusion_preserve_valid_flow(self):
        for dtype in (torch.float32,torch.float64):
            for sigma in (0.,.5):
                with self.subTest(dtype=dtype,sigma=sigma):
                    out=make_flow(torch.tensor(.1,dtype=dtype),sigma,.8,-.1,.3,Grid())
                    self.assertTrue(bool((out['edges'][...,1:]>out['edges'][...,:-1]).all()))
                    self.assertTrue(bool((out['centers'][...,1:]>out['centers'][...,:-1]).all()))
                    self.assertTrue(all(bool(torch.isfinite(out[k]).all()) for k in
                                        ('up','down','active_out','phase_rate','reset_weights')))
                    self.assertAlmostEqual(float(out['reset_weights'].sum()),1.,
                                           delta=8*torch.finfo(dtype).eps)

    def test_float64_large_interval_overflow_fails_closed(self):
        grid=Grid(lower=-1e308)
        with self.assertRaisesRegex(ValueError,'Cell grid is unresolved'):
            make_flow(torch.tensor(.1,dtype=torch.float64),.5,1e308,0.,.3,grid)


if __name__=='__main__':
    unittest.main()
