"""Algebraic finite-law acceleration shared by HX and ordinary same-matrix HMM."""

import numpy as np
from scipy.linalg import expm

from ..support_retention_r16_20261101.compression import BlockLaw


class UnsupportedSymmetry(ValueError):
    """The exact permutation-symmetric Metzler decomposition is unavailable."""


def decomposition(generator):
    """Return a nonnegative triangular lift, rejecting approximate symmetry.

    With H=D/3, Q=S tensor I + H tensor (J-I).  A=S+3H, B=S-H.
    The upper block of exp([[B,4H],[0,A]]t) is exp(At)-exp(Bt),
    obtained by integration, without subtracting nearly equal exponentials.
    """
    q = np.asarray(generator, dtype=float)
    if q.shape != (40, 40) or not np.isfinite(q).all():
        raise UnsupportedSymmetry("Expected finite 40x40 matrix")
    s, h = q[::4, ::4].copy(), q[::4, 1::4].copy()
    for source in range(4):
        for target in range(4):
            if not np.array_equal(q[source::4, target::4], s if source == target else h):
                raise UnsupportedSymmetry("Generator lacks exact four-content symmetry")
    a, b = s + 3 * h, s - h
    lift = np.block([[b, 4 * h], [np.zeros_like(b), a]])
    off = lift.copy()
    np.fill_diagonal(off, 0)
    if np.any(off < 0) or np.any(h < 0):
        raise UnsupportedSymmetry("Triangular lift is not Metzler")
    qoff = q.copy()
    np.fill_diagonal(qoff, 0)
    if np.any(qoff < 0) or not np.allclose(q.sum(1), 0, rtol=0, atol=5e-12):
        raise UnsupportedSymmetry("Not a conservative row generator")
    lift.setflags(write=False)
    return lift


class SymmetricLaw(BlockLaw):
    """Preserve the original arrays/identities; explicitly fall back when unsupported."""

    def _finish(self):
        super()._finish()
        try:
            self._symmetric_lift = decomposition(self.Q)
        except UnsupportedSymmetry as exc:
            self._symmetric_lift = None
            self.fastpath_status = dict(eligible=False, reason=str(exc))
        else:
            self.fastpath_status = dict(eligible=True, reason=None)

    def transition(self, dt, method="expm"):
        dt = self._duration(dt)
        if method != "expm":
            raise ValueError("Only expm is implemented")
        if self._symmetric_lift is None:
            return super().transition(dt, method)
        if dt not in self._transition_cache:
            value = expm(dt * self._symmetric_lift)
            transition = np.kron(value[:10, :10], np.eye(4))
            transition += np.kron(value[:10, 10:], np.full((4, 4), .25))
            if not np.isfinite(transition).all() or np.any(transition < 0):
                raise ArithmeticError("Representable nonnegative transition contract failed")
            transition.setflags(write=False)
            self._transition_cache[dt] = transition
        return self._transition_cache[dt]
