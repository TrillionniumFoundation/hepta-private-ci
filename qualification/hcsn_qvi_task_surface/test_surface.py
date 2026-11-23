import unittest

import numpy as np
import torch

from qualification.hcsn_qvi_retrieval.dynamics import RetrievalFlow
from .model import TaskSurface


class SurfaceTests(unittest.TestCase):
    def test_surface_changes_real_flow_and_preserves_nominal_controls(self):
        edges=np.array([.05,.2,.3])
        q=np.zeros((4,4,3))
        q[:,:,0]=np.linspace(-1,1,4)[None,:]
        torch.manual_seed(123)
        model=TaskSurface(3,edges,q)
        torch.manual_seed(123)
        fixed=RetrievalFlow(3,mode="fixed")
        for a,b in zip(model.flow.parameters(),fixed.flow.parameters(),strict=True):
            torch.testing.assert_close(a,b)
        x=torch.zeros((2,4,3),dtype=torch.float64)
        dt=torch.full((2,4),.48,dtype=torch.float64)
        margins=torch.tensor([[.01,.01,.01,.01],[.4,.4,.4,.4]],dtype=torch.float64)
        b=model.task_boundaries(margins)
        torch.testing.assert_close(b[0,:3],model.nominal_boundary.expand(3))
        self.assertTrue(bool((b[1,:3] > b[0,:3]).all()))
        torch.testing.assert_close(b[0,-1],b[1,-1])
        y=model(x,dt,margins)
        torch.testing.assert_close(y[:1,:3],fixed(x[:1,:3],dt[:1,:3]))
        self.assertGreater(float((y[0,:3]-y[1,:3]).detach().abs().max()),1e-5)
        torch.testing.assert_close(y[:,:2],model(x[:,:2],dt[:,:2],margins[:,:2]))
        theta=model.initial_edit_vector().requires_grad_()
        self.assertTrue(torch.autograd.gradcheck(lambda t:model.features_with_edit(t,x,dt,margins),
                        (theta,),eps=1e-5,atol=2e-6,rtol=2e-4,fast_mode=True))

    def test_terminal_force_uses_true_deadline_and_exact_quartile_convention(self):
        edges=np.array([.1,.2,.3])
        q=np.zeros((4,4,3))
        q[:,:,1]=np.array([.0,.4,.8,1.2])
        model=TaskSurface(2,edges,q)
        m=torch.tensor([[.1,.2,.3,.005]],dtype=torch.float64)
        b=model.task_boundaries(m)
        gap=model.task[3]-model.nominal_boundary
        rad=.9*torch.minimum(gap-model.flow.centers[0],model.flow.centers[-1]-gap)
        expected=model.nominal_boundary+rad*torch.tensor([0.,np.tanh(.4),np.tanh(.8),1.],dtype=torch.float64)
        torch.testing.assert_close(b[0],expected)
        torch.testing.assert_close(model.task_boundaries(m[:,:2]),b[:,:2])


if __name__=="__main__":
    unittest.main()
