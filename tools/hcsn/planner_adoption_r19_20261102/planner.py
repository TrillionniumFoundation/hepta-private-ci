"""Owned projection buffers and terminal workspace; no probability/time changes."""

import numpy as np

from ..planner_fastpath_r18_20261101.planner import BatchedPlanner, validate_rows
from ..support_retention_r16_20261101.compression import COLLECT, SPREAD, GROUP
from .bounded import Workspace


class WorkspacePlanner(BatchedPlanner):
    """Consume private temporary buffers, retaining every original arithmetic shape."""

    def __init__(self,*args,workspace=None,**kwargs):
        super().__init__(*args,**kwargs);self.workspace=Workspace() if workspace is None else workspace

    def _project_many(self,arrays):
        merged=(arrays[0].reshape(-1,40) if len(arrays)==1 else
                np.concatenate([p.reshape(-1,40) for p in arrays],axis=0))
        if self.projection=="full":
            validate_rows(merged,40,-1e-13)
            return [p if p.flags.c_contiguous else p.copy() for p in arrays]
        if any(not p.flags.owndata or not p.flags.writeable for p in arrays):
            return super()._project_many(arrays)
        validate_rows(merged,40,0.)
        packed=[p@COLLECT for p in arrays]
        merged_packed=(packed[0].reshape(-1,8) if len(packed)==1 else
                       np.concatenate([p.reshape(-1,8) for p in packed],axis=0))
        validate_rows(merged_packed,8,0.)
        outputs=[]
        for packed_p,original in zip(packed,arrays,strict=True):
            flat=original.ravel(order="K")
            if not np.shares_memory(flat,original):
                return super()._project_many(arrays)
            outputs.append(flat.reshape(original.shape))
        for p,result in zip(packed,outputs,strict=True):
            np.matmul(p,SPREAD,out=result)
            if np.any((p[...,GROUP]>0)&(result==0)):
                raise ValueError("Positive support is unrepresentable at this floating-point scale")
        return outputs

    def _forest(self,frames,remaining):
        if remaining:return super()._forest(frames,remaining)
        frames=[np.asarray(p,dtype=float).reshape(-1,40) for p in frames]
        self.belief_evaluations+=sum(len(p) for p in frames)
        return [self.workspace.terminal(p,self.reward_at[0]) for p in frames]
