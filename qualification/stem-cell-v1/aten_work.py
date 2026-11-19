"""Versioned eager CPU arithmetic formulas, NOT hardware instruction counts.

A multiply-add counts as two; exp/log/sqrt/erf each as one primitive. Sort,
comparison, indexing, allocation, copies, PRNG and integer work are recorded
operators but contribute no floating arithmetic under this profile. Their time,
CPU time and memory are still observed. Unknown operators NEVER count as known
zero: observe mode leaves the complete phase count null; strict mode refuses
before dispatch. This profile does not cover compiled/custom/GPU kernels.
"""
from __future__ import annotations

import math

import torch

PROFILE = "hepta.cpu-eager-aten-formula-work.v1"
# Exact overloads only. A new overload needs a reviewed rule, not prefix matching.
ZERO = frozenset("""
aten._local_scalar_dense.default aten.item.default
aten.detach.default aten.detach_.default aten.lift_fresh.default
aten.t.default aten.transpose.int aten.permute.default aten.view.default
aten.view.dtype aten.reshape.default aten._unsafe_view.default aten.expand.default
aten.unsqueeze.default aten.squeeze.dim aten.squeeze.default aten.slice.Tensor
aten.select.int aten.unbind.int aten.resolve_conj.default aten.resolve_neg.default
aten.empty.memory_format aten.empty_strided.default aten.empty_like.default
aten.new_zeros.default aten.new_empty.default aten.ones_like.default aten.zeros_like.default
aten.zeros.default aten.ones.default aten.full.default aten.full_like.default
aten.fill_.Scalar aten.zero_.default aten.clone.default aten.copy_.default
aten._to_copy.default aten.alias.default aten.cat.default aten.stack.default
aten.gather.default aten.index.Tensor aten.index_select.default
aten.index_copy.default aten.index_copy_.default aten.nonzero.default
aten.where.default aten.where.self aten.masked_fill.Scalar aten.masked_fill_.Scalar
aten.eq.Scalar aten.eq.Tensor aten.ne.Scalar aten.ne.Tensor
aten.lt.Scalar aten.lt.Tensor aten.le.Scalar aten.le.Tensor
aten.gt.Scalar aten.gt.Tensor aten.ge.Scalar aten.ge.Tensor
aten.all.default aten.all.dim aten.any.default aten.any.dim
aten.isfinite.default aten.isnan.default aten.isinf.default
aten.argsort.stable aten.sort.stable aten.sort.default aten.argmax.default
aten.max.default aten.min.default aten.amax.default aten.amin.default
aten.clamp.default aten.clamp_.default aten.clamp_min.default aten.clamp_max.default
aten.randint.generator aten.randint.default aten.arange.default aten.arange.start
aten.arange.start_step aten.scalar_tensor.default
aten.equal.default profiler._record_function_enter_new.default
profiler._record_function_exit._RecordFunction
""".split())


def _float(tensor):
    return isinstance(tensor, torch.Tensor) and tensor.is_floating_point()


def _n(value):
    return value.numel() if _float(value) else 0


def _broadcast(args):
    shapes = [x.shape for x in args if isinstance(x, torch.Tensor)]
    return math.prod(torch.broadcast_shapes(*shapes)) if any(_float(x) for x in args) else 0


def _reduction(tensor, dims):
    if dims is None or dims == [] or dims == ():
        return tensor.numel(), 1
    if type(dims) is int:
        dims = [dims]
    reduced = math.prod(tensor.shape[d] for d in set(dims))
    groups = tensor.numel() // reduced if reduced else 0
    return reduced, groups


def cost(operator, args, kwargs):
    """Return pre-dispatch scalar-equivalent work, or None for unknown semantics.

    Fused GELU rules use its erf definition: 5 primitives forward, 13 backward.
    Softmax uses shift/exp/sum/divide (4N-G); log-softmax uses shift/exp/sum/log/
    subtract (4N); maximum selection is comparison, not floating arithmetic.
    No unregistered weighted/ignored-label NLL or masked attention approximation.
    """
    name = str(operator)
    if name in ZERO:
        return 0
    if name in ("aten.mm.default", "aten.bmm.default"):
        left, right = args[:2]
        return 2 * math.prod(left.shape[:-1]) * left.shape[-1] * right.shape[-1]
    if name in ("aten.addmm.default", "aten.baddbmm.default"):
        _, left, right = args[:3]
        outputs = math.prod(left.shape[:-1]) * right.shape[-1]
        # alpha/beta scalings are charged unless exactly one/zero; no value probes.
        alpha, beta = kwargs.get("alpha", 1), kwargs.get("beta", 1)
        return (2 * outputs * left.shape[-1] + outputs * (alpha != 1)
                + outputs * (beta != 0) + outputs * (beta not in (0, 1)))
    if name == "aten.linear.default":
        x, weight = args[:2]
        outputs = math.prod(x.shape[:-1]) * weight.shape[0]
        bias = args[2] if len(args) > 2 else kwargs.get("bias")
        return 2 * outputs * weight.shape[1] + (outputs if bias is not None else 0)
    if name in ("aten.add.Tensor", "aten.add_.Tensor", "aten.sub.Tensor", "aten.sub_.Tensor"):
        return _broadcast(args[:2]) * (1 + (kwargs.get("alpha", 1) != 1))
    if name in ("aten.mul.Tensor", "aten.mul_.Tensor", "aten.div.Tensor", "aten.div_.Tensor"):
        return _broadcast(args[:2])
    if name in ("aten.neg.default", "aten.abs.default", "aten.sqrt.default",
                "aten.exp.default", "aten.log.default", "aten.reciprocal.default", "aten.erf.default"):
        return _n(args[0])
    if name == "aten.rsqrt.default":
        return 2 * _n(args[0])
    if name in ("aten.addcdiv_.default", "aten.addcmul_.default", "aten.addcdiv.default", "aten.addcmul.default"):
        return 3 * _broadcast(args[:3])
    if name in ("aten.lerp_.Scalar", "aten.lerp.Scalar"):
        return 3 * _broadcast(args[:2])
    if name in ("aten._foreach_mul_.Tensor", "aten._foreach_mul_.Scalar"):
        return sum(_n(x) for x in args[0])
    if name in ("aten._foreach_norm.Scalar", "aten.linalg_vector_norm.default"):
        order = args[1] if len(args) > 1 else kwargs.get("ord", 2)
        if order != 2:
            return None
        if name.startswith("aten._foreach"):
            return sum(2 * _n(x) for x in args[0])
        if (len(args) > 2 and args[2] is not None) or kwargs.get("dim") is not None:
            return None
        return 2 * _n(args[0])
    if name in ("aten.sum.default", "aten.sum.dim_IntList", "aten.mean.default", "aten.mean.dim"):
        if not _float(args[0]):
            return 0
        dims = args[1] if len(args) > 1 else kwargs.get("dim")
        reduced, groups = _reduction(args[0], dims)
        return max(0, reduced - 1) * groups + (groups if "mean" in name else 0)
    if name in ("aten._softmax.default", "aten.softmax.int", "aten._log_softmax.default"):
        dimension = args[1] if len(args) > 1 else kwargs.get("dim", -1)
        n, g = _reduction(args[0], dimension)
        if n == 0:
            return 0
        # Subtract-max: N; exponent: N; sum: N-G; divide: N.
        return 4 * n * g if "log_softmax" in name else 4 * n * g - g
    if name in ("aten._softmax_backward_data.default", "aten._log_softmax_backward_data.default"):
        n, g = _reduction(args[0], args[2])
        return max(0, 4 * n * g - g)
    if name in ("aten.gelu.default", "aten.gelu_backward.default"):
        if kwargs.get("approximate", "none") != "none":
            return None
        return (13 if "backward" in name else 5) * _n(args[0])
    if name in ("aten.index_add.default", "aten.index_add_.default", "aten.scatter_add.default", "aten.scatter_add_.default"):
        return _n(args[3]) * (1 + (kwargs.get("alpha", 1) != 1))
    if name in ("aten.index_put.default", "aten.index_put_.default"):
        accumulate = args[3] if len(args) > 3 else kwargs.get("accumulate", False)
        return _n(args[2]) if accumulate else 0
    if name in ("aten.nll_loss_forward.default", "aten.nll_loss_backward.default"):
        offset = 1 if "backward" in name else 0
        x, target, weights, reduction, ignore = args[offset:offset + 5]
        # Workload admission provides nonnegative labels, so -100 is unused.
        if weights is not None or reduction != 1 or ignore != -100 or x.ndim != 2:
            return None
        return 2 * target.numel()
    if name == "aten.uniform_.default":
        return 2 * _n(args[0])  # Floating scaling only; PRNG integer work excluded.
    return None
