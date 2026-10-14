"""Add exact CPU FP32 token-Reader backward scatter to the existing V3 formulas.

The zero floating arithmetic for select_backward is NOT zero memory traffic:
PyTorch constructs an input-shaped zero gradient and copies the selected output
slice into it. The operation has no floating multiplication/addition. This is
an explicit NEW arithmetic profile; no V3 historical work is reinterpreted.
"""
from __future__ import annotations

import torch
from transformer_work_v3 import cost as previous_cost

PROFILE='hepta.cpu-fp32-eager-conditional-reader-work.v1'


def cost(op,args,kwargs):
    if str(op)!='aten.select_backward.default':
        return previous_cost(op,args,kwargs)
    if kwargs or not isinstance(args,(tuple,list)) or len(args)!=4:
        return None
    gradient, sizes, dim, index=args
    if (not isinstance(gradient,torch.Tensor) or gradient.dtype!=torch.float32
            or gradient.device.type!='cpu' or gradient.is_sparse
            or not isinstance(sizes,(tuple,list)) or not 1<=len(sizes)<=6
            or any(type(n) is not int or not 0<=n<=4096 for n in sizes)
            or type(dim) is not int or type(index) is not int):
        return None
    normalized=dim%len(sizes)
    if not -len(sizes)<=dim<len(sizes) or not 0<=index<sizes[normalized]:
        return None
    projected=tuple(s for i,s in enumerate(sizes) if i!=normalized)
    if tuple(gradient.shape)!=projected:
        return None
    return 0
