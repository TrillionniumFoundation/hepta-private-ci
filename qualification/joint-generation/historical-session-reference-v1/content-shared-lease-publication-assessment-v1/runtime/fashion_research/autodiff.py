"""Small float64 reverse-mode array graph used by the research model."""

import numpy as np


def _unbroadcast(gradient, shape):
    while gradient.ndim > len(shape):
        gradient = gradient.sum(axis=0)
    for axis, size in enumerate(shape):
        if size == 1 and gradient.shape[axis] != 1:
            gradient = gradient.sum(axis=axis, keepdims=True)
    return gradient.reshape(shape)


class Tensor:
    def __init__(self, data, requires_grad=False, parents=()):
        self.data = np.asarray(data, dtype=np.float64)
        self.requires_grad = bool(requires_grad)
        self.parents = tuple(parents) if self.requires_grad else ()
        self.grad = None

    @staticmethod
    def as_tensor(value):
        return value if isinstance(value, Tensor) else Tensor(value)

    @classmethod
    def operation(cls, data, *edges):
        edges = tuple((node, vjp) for node, vjp in edges if node.requires_grad)
        return cls(data, bool(edges), edges)

    def __add__(self, other):
        other = self.as_tensor(other)
        return self.operation(self.data + other.data,
                              (self, lambda g: _unbroadcast(g, self.data.shape)),
                              (other, lambda g: _unbroadcast(g, other.data.shape)))

    __radd__ = __add__

    def __neg__(self):
        return self * -1.0

    def __sub__(self, other):
        return self + -self.as_tensor(other)

    def __rsub__(self, other):
        return self.as_tensor(other) - self

    def __mul__(self, other):
        other = self.as_tensor(other)
        return self.operation(self.data * other.data,
                              (self, lambda g: _unbroadcast(g * other.data, self.data.shape)),
                              (other, lambda g: _unbroadcast(g * self.data, other.data.shape)))

    __rmul__ = __mul__

    def __truediv__(self, other):
        other = self.as_tensor(other)
        return self.operation(self.data / other.data,
                              (self, lambda g: _unbroadcast(g / other.data, self.data.shape)),
                              (other, lambda g: _unbroadcast(
                                  -g * self.data / (other.data * other.data), other.data.shape)))

    def __rtruediv__(self, other):
        return self.as_tensor(other) / self

    def __matmul__(self, other):
        other = self.as_tensor(other)
        if self.data.ndim < 2 or other.data.ndim != 2:
            raise ValueError("matmul requires a batched array and a matrix")
        return self.operation(self.data @ other.data,
                              (self, lambda g: g @ other.data.T),
                              (other, lambda g: self.data.reshape(-1, self.data.shape[-1]).T
                               @ g.reshape(-1, g.shape[-1])))

    def __getitem__(self, index):
        def vjp(g):
            result = np.zeros_like(self.data)
            np.add.at(result, index, g)
            return result
        return self.operation(self.data[index], (self, vjp))

    def reshape(self, *shape):
        return self.operation(self.data.reshape(*shape),
                              (self, lambda g: g.reshape(self.data.shape)))

    def transpose(self, *axes):
        inverse = tuple(np.argsort(axes))
        return self.operation(self.data.transpose(*axes),
                              (self, lambda g: g.transpose(*inverse)))

    def sum(self, axis=None, keepdims=False):
        def vjp(g):
            if axis is not None and not keepdims:
                axes = (axis,) if isinstance(axis, int) else axis
                for a in sorted(x % self.data.ndim for x in axes):
                    g = np.expand_dims(g, a)
            return np.broadcast_to(g, self.data.shape)
        return self.operation(self.data.sum(axis=axis, keepdims=keepdims), (self, vjp))

    def mean(self, axis=None, keepdims=False):
        axes = range(self.data.ndim) if axis is None else (
            (axis,) if isinstance(axis, int) else axis)
        count = int(np.prod([self.data.shape[a] for a in axes]))
        return self.sum(axis, keepdims) / count

    def tanh(self):
        value = np.tanh(self.data)
        return self.operation(value, (self, lambda g: g * (1.0 - value * value)))

    def exp(self):
        value = np.exp(self.data)
        return self.operation(value, (self, lambda g: g * value))

    def log(self):
        return self.operation(np.log(self.data), (self, lambda g: g / self.data))

    def clip(self, low, high):
        mask = (self.data > low) & (self.data < high)
        return self.operation(np.clip(self.data, low, high), (self, lambda g: g * mask))

    def broadcast_to(self, shape):
        return self.operation(np.broadcast_to(self.data, shape),
                              (self, lambda g: _unbroadcast(g, self.data.shape)))

    def backward(self):
        if self.data.size != 1:
            raise ValueError("backward requires a scalar loss")
        visited, order = set(), []

        def visit(node):
            if id(node) not in visited:
                visited.add(id(node))
                for parent, _ in node.parents:
                    visit(parent)
                order.append(node)

        visit(self)
        for node in order:
            node.grad = None
        self.grad = np.ones_like(self.data)
        for node in reversed(order):
            if node.grad is not None:
                for parent, vjp in node.parents:
                    contribution = vjp(node.grad)
                    parent.grad = contribution if parent.grad is None else parent.grad + contribution


def concatenate(values, axis=-1):
    values = tuple(Tensor.as_tensor(value) for value in values)
    axis %= values[0].data.ndim
    offset, edges = 0, []
    for value in values:
        index = [slice(None)] * value.data.ndim
        index[axis] = slice(offset, offset + value.data.shape[axis])
        edges.append((value, lambda g, index=tuple(index): g[index]))
        offset += value.data.shape[axis]
    return Tensor.operation(np.concatenate([v.data for v in values], axis=axis), *edges)


def posterior(logits):
    # Keep the normalization graph for a terminal CE without eagerly computing logs.
    # The constant shift cancels algebraically; its derivative is unnecessary.
    shifted = logits - logits.data.max(axis=-1, keepdims=True)
    weights = shifted.exp()
    denominator = weights.sum(axis=-1, keepdims=True)
    probabilities = weights.data / denominator.data

    def vjp(g):
        # Pairwise differences retain the small dominant-class derivative:
        # p[j] * sum_i p[i] * (g[j] - g[i]), without subtracting 1 - p[j].
        differences = g[..., :, None] - g[..., None, :]
        return probabilities * (probabilities[..., None, :] * differences).sum(axis=-1)

    return Tensor.operation(probabilities, (logits, vjp)), shifted, denominator
