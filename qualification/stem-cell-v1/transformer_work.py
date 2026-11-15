"""Opt-in V2 scalar-equivalent work for eager frozen Transformer inference.

V1 arithmetic semantics remain unchanged. These formulas do not count hardware
instructions. LayerNorm uses centered population variance: 5N+3G, plus N for
weight scaling and N for bias. Sin, cos and general power each count one primitive.
Embedding/reshape/mask operations move/select data and have zero floating
arithmetic, not zero time or memory. Unsupported fused attention remains unknown.
"""
import math

from aten_work import cost as legacy_cost

PROFILE = 'hepta.cpu-eager-transformer-formula-work.v2'
ZERO = frozenset('''
aten.embedding.default aten.as_strided.default aten.split.Tensor aten.split_with_sizes.default
aten.chunk.default aten.contiguous.default aten.logical_not.default
aten.bitwise_not.default aten.bitwise_and.Tensor aten.bitwise_or.Tensor
aten.triu.default aten.tril.default aten._reshape_alias.default
'''.split())


def cost(operator, args, kwargs):
    name = str(operator)
    if name in ZERO:
        return 0
    if name in ('aten.sin.default', 'aten.cos.default', 'aten.pow.Tensor_Scalar',
                'aten.pow.Scalar', 'aten.pow.Tensor_Tensor'):
        import torch
        tensors = [v for v in args if isinstance(v, torch.Tensor)]
        if not tensors or not any(v.is_floating_point() for v in tensors):
            return None  # Integer pow can produce floats; no dtype assumption.
        return math.prod(torch.broadcast_shapes(*(v.shape for v in tensors)))
    if name in ('aten.native_layer_norm.default', 'aten.layer_norm.default'):
        x, shape = args[:2]
        weight = args[2] if len(args) > 2 else kwargs.get('weight')
        bias = args[3] if len(args) > 3 else kwargs.get('bias')
        eps = args[4] if len(args) > 4 else kwargs.get('eps', 1e-5)
        if (not isinstance(shape, (list, tuple)) or not shape
                or any(type(v) is not int or v <= 0 for v in shape)
                or tuple(x.shape[-len(shape):]) != tuple(shape)
                or type(eps) not in (int, float) or not math.isfinite(eps) or eps <= 0):
            return None
        width, count = math.prod(shape), x.numel()
        if any(w is not None and tuple(w.shape) != tuple(shape) for w in (weight, bias)):
            return None
        return 5 * count + 3 * (count // width) + count * (weight is not None) + count * (bias is not None)
    if name == 'aten.cumsum.default':
        x, dimension = args[:2]
        if not x.is_floating_point():
            return 0
        size = x.shape[dimension]
        return (size - 1) * (x.numel() // size) if size else 0
    if name == 'aten.dropout.default':
        training = args[2] if len(args) > 2 else kwargs.get('train')
        return 0 if training is False else None
    return legacy_cost(operator, args, kwargs)
