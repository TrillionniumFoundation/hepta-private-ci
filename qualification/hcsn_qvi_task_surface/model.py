"""Drive the existing finite population from the retrieval task's observed obstacle."""
import torch

from qualification.hcsn_qvi_retrieval.dynamics import RetrievalFlow


class _IntervalBoundaries:
    """Ephemeral execution view, keeping the incumbent module reentrant."""

    def __init__(self, model, boundary):
        self.model, self.interval_boundary = model, boundary

    def __getattr__(self, key):
        return getattr(self.model, key)

    def boundaries(self, drift):
        if self.interval_boundary.shape != drift.shape:
            raise ValueError("surface and finite flow clocks differ")
        return self.interval_boundary


class TaskSurface(RetrievalFlow):
    def __init__(self, input_size, edges, action_values):
        super().__init__(input_size,mode="fixed")
        edges = torch.as_tensor(edges,dtype=torch.float64)
        q = torch.as_tensor(action_values,dtype=torch.float64)
        if (edges.shape!=(3,) or q.ndim!=3 or q.shape[1:]!=(4,3) or q.shape[0]<2
                or not bool((edges[1:]>=edges[:-1]).all())
                or not bool(torch.isfinite(edges).all() & torch.isfinite(q).all())):
            raise ValueError("invalid time-by-margin retrieval task surface")
        self.register_buffer("margin_edges",edges.detach().clone())
        self.register_buffer("action_values",q.detach().clone())
        self.mode = "task_surface"

    def task_boundaries(self, raw_margin):
        horizon = self.action_values.shape[0]
        if (raw_margin.ndim!=2 or not 1<=raw_margin.shape[1]<=horizon
                or not torch.isfinite(raw_margin).all() or bool((raw_margin<0).any())):
            raise ValueError("a finite nonnegative current margin for each observable prefix is required")
        prefix = torch.arange(raw_margin.shape[1],device=raw_margin.device)
        cell = torch.bucketize(raw_margin.contiguous(),self.margin_edges,right=False)
        q = self.action_values[prefix[None,:],cell]
        advantage = q[:,:,:2].max(-1).values - q[:,:,2]
        offset = torch.where(prefix==horizon-1, torch.ones_like(advantage), advantage.tanh())
        gap = self.task[3]-self.nominal_boundary
        radius = 0.9*torch.minimum(gap-self.flow.centers[0],self.flow.centers[-1]-gap)
        return self.nominal_boundary + radius*offset

    def forward(self, x, dt, raw_margin):
        view = _IntervalBoundaries(self,self.task_boundaries(raw_margin))
        return RetrievalFlow.forward(view,x,dt)

    def features_with_edit(self, theta, x, dt, raw_margin):
        if theta.shape!=(2,) or theta.dtype!=torch.float64:
            raise ValueError("two FP64 physical bias edit coordinates required")
        return torch.func.functional_call(self,{
            "flow.drive.bias":self.flow.drive.bias+theta[0],
            "flow.writer.bias":self.flow.writer.bias+self.mark_direction*theta[1],
        },(x,dt,raw_margin))
