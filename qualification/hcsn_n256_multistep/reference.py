"""Independent method-of-steps BDF reference, without packet realizations."""

import math
from fractions import Fraction as F

import numpy as np
from scipy import sparse
from scipy.integrate import solve_ivp


def run(authentic, metadata, rtol, queries):
    nodes = np.frombuffer(authentic.nodes_payload, dtype="<f8")
    n, channels, width = len(nodes) - 2, 5, len(nodes) + 2
    mu, sigma, discount = (metadata["physics"][key] for key in ("mu", "sigma", "discount"))
    # Assemble the transpose of the spatial generator directly, without the
    # candidate's CSR, block assembler, source identities or packet selectors.
    q = np.zeros((n, n))
    lower, upper = np.zeros(n), np.zeros(n)
    for i in range(n):
        left, right = nodes[i + 1] - nodes[i], nodes[i + 2] - nodes[i + 1]
        down = (sigma*sigma - mu*right) / (left*(left+right))
        up = (sigma*sigma + mu*left) / (right*(left+right))
        q[i, i] = -(down + up)
        if i:
            q[i - 1, i] = down
        else:
            lower[i] = down
        if i + 1 < n:
            q[i + 1, i] = up
        else:
            upper[i] = up
    reset = np.zeros(n)
    position = metadata["reset_distance"]
    k = next(i for i, node in enumerate(nodes) if node > position)
    fraction = (position - nodes[k - 1]) / (nodes[k] - nodes[k - 1])
    reset[k - 2], reset[k - 1] = 1 - fraction, fraction
    q = sparse.csr_matrix(q)
    initial = np.column_stack((np.frombuffer(authentic.active_payload, dtype="<f8"),
        np.frombuffer(authentic.signed_content_payload, dtype="<f8").reshape(n + 2, 4))).T
    seed = np.zeros((channels, width))
    seed[:, :n] = initial[:, 1:-1]
    records, history = [], [[], []]

    def jacobian(time, values):
        del values
        factor = math.exp(-discount * time)
        rows = sparse.vstack((sparse.csr_matrix(upper), sparse.csr_matrix(lower),
            sparse.csr_matrix(factor * lower), sparse.csr_matrix(np.full(n, factor))))
        last = sparse.lil_matrix((4, 4))
        last[3, 0] = factor
        single = sparse.bmat(((q, sparse.csr_matrix((n, 4))), (rows, last.tocsr())), format="csr")
        return sparse.kron(sparse.eye(channels, format="csr"), single, format="csc")

    def sample(generation, time):
        if generation == 1 and time <= .2:
            return np.zeros((channels, width))
        for left, right, solution in history[generation]:
            if left - 1e-14 <= time <= right + 1e-14:
                return solution.sol(min(right, max(left, time))).reshape(channels, width)
        raise ValueError("DDE history domain")

    def solve(generation, left, right, current, source):
        def rhs(time, values):
            values = values.reshape(channels, width)
            result = np.zeros_like(values)
            factor = math.exp(-discount * time)
            result[:, :n] = (q @ values[:, :n].T).T + source(time)[:, None] * reset
            result[:, n] = values[:, :n] @ upper
            result[:, n + 1] = values[:, :n] @ lower
            result[:, n + 2] = factor * result[:, n + 1]
            result[:, n + 3] = factor * (values[:, :n].sum(axis=1) + values[:, n])
            return result.ravel()
        solution = solve_ivp(rhs, (left, right), current.ravel(), method="BDF",
            jac=jacobian, rtol=rtol, atol=rtol * 1e-3, dense_output=True)
        if not solution.success or not np.isfinite(solution.y).all():
            raise ValueError("independent BDF failure: " + solution.message)
        history[generation].append((left, right, solution))
        records.append({"generation": generation + 1, "left": left, "right": right,
            "nfev": solution.nfev, "njev": solution.njev, "nlu": solution.nlu,
            "accepted_mesh_points": len(solution.t), "message": solution.message})
        return solution.y[:, -1].reshape(channels, width)

    current = seed
    for _, left, right, rates in authentic.phase_packets:
        rate = np.array([float(value) for value in rates])
        current = solve(0, float(left), float(right), current, lambda time, rate=rate: rate)
    current = solve(0, .2, .36, current, lambda time: np.zeros(channels))
    current = np.zeros((channels, width))
    boundaries = [float(value) for value in (F(1, 5), F(9, 40), F(1, 4), F(11, 40), F(3, 10), F(13, 40), F(7, 20), F(9, 25))]
    for left, right in zip(boundaries, boundaries[1:]):
        current = solve(1, left, right, current, lambda time: sample(0, time - .2)[:, :n] @ lower)
    values = []
    for time in queries:
        if time == 0:
            first, second = seed, np.zeros_like(seed)
        else:
            first, second = sample(0, float(time)), sample(1, float(time))
        active = np.stack((first[:, :n], second[:, :n]), axis=1)
        escaped = np.column_stack((initial[:, -1], first[:, n], second[:, n]))
        hit = np.column_stack((first[:, n + 1], second[:, n + 1]))
        discounted_hit = np.column_stack((first[:, n + 2], second[:, n + 2]))
        permanent = initial[:, -1] * -math.expm1(-discount * float(time)) / discount
        occupation = np.column_stack((permanent, first[:, n + 3], second[:, n + 3]))
        values.append(np.concatenate([array.ravel() for array in (active, escaped, hit, discounted_hit, occupation)]))
    raw = {f"g{generation}_s{index}_{key}": getattr(solution, key)
        for generation in (0, 1) for index, (_, _, solution) in enumerate(history[generation])
        for key in ("t", "y")}
    return np.asarray(values), records, raw
