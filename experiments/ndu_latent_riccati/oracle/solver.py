"""Differentiable finite-horizon, unconstrained, risk-neutral LQ Riccati solve.

State dx=(A x+B u)dt+Sigma dW; cost E[int (x'Qx+u'Ru)/2 dt+xT' H xT/2].
Coefficients are constant; Q,H are positive semidefinite and R positive definite.
Sigma is deliberately absent: additive exogenous noise changes the scalar value,
not the full-observation risk-neutral feedback. This is not a general FBSDE solver.
"""

import torch


def torch_dre(A, B, Q, R, H, horizon=2.0, steps=128):
    """Return S and K on an ascending uniform time grid, with u=-K x.

    RK4 integrates dS/ds=A' S+S A+Q-S B R^-1 B' S in reverse time s=T-t.
    Every operation stays in the autograd graph. No inverses or eigenvalue clips
    are used. Callers must enforce the LQ assumptions and inspect convergence.
    Leading batch dimensions are supported by torch's matrix broadcasting.
    """
    if steps < 1 or horizon <= 0:
        raise ValueError("steps and horizon must be positive")
    h = horizon / steps
    M = B @ torch.linalg.solve(R, B.transpose(-1, -2))

    def rhs(S):
        return A.transpose(-1, -2) @ S + S @ A + Q - S @ M @ S

    values = [H]
    for _ in range(steps):
        S = values[-1]
        k1 = rhs(S)
        k2 = rhs(S + 0.5 * h * k1)
        k3 = rhs(S + 0.5 * h * k2)
        k4 = rhs(S + h * k3)
        next_S = S + h * (k1 + 2 * k2 + 2 * k3 + k4) / 6
        values.append((next_S + next_S.transpose(-1, -2)) * 0.5)
    S = torch.stack(list(reversed(values)))
    K = torch.linalg.solve(R, B.transpose(-1, -2) @ S)
    return S, K
