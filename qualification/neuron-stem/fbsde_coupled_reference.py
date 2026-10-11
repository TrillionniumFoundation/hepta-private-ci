"""Independent monolithic Newton oracle for the small binary FBSDE discretization.

No import of local fields, fixed-point map or numerical solver. All ancestral
state sums and the dense analytic Jacobian are rebuilt from the declared model.
This is a high-accuracy floating reference, not an interval-verified exact root.
"""
import math


def _linear(a, b):
    n = len(b)
    m = [list(row)+[float(v)] for row, v in zip(a, b)]
    for k in range(n):
        pivot = max(range(k, n), key=lambda i: abs(m[i][k]))
        if abs(m[pivot][k]) < 1e-14:
            raise ValueError('reference Jacobian singular')
        m[k], m[pivot] = m[pivot], m[k]
        for i in range(k+1, n):
            scale = m[i][k]/m[k][k]
            m[i][k] = 0.
            for j in range(k+1, n+1):
                m[i][j] -= scale*m[k][j]
    x = [0.]*n
    for i in reversed(range(n)):
        x[i] = (m[i][n]-sum(m[i][j]*x[j] for j in range(i+1, n)))/m[i][i]
    return x


def residual_and_jacobian(cfg, x0, y):
    n = cfg['steps']
    if type(n) is not int or not 1 <= n <= 7 or len(y) != 2**n-1:
        raise ValueError('bounded monolithic reference')
    m = len(y)
    h = cfg['horizon']/n
    ah = cfg['a']*h
    sigma = cfg['sigma']*math.sqrt(h)
    ancestors, noise = [], []
    for node in range(2*m+1):
        walk, parents, signed = node, [], 0
        while walk:
            signed += -1 if walk % 2 else 1
            walk = (walk-1)//2
            parents.append(walk)
        ancestors.append(parents)
        noise.append(signed)
    xs = [x0+ah*sum(y[j] for j in parents)+sigma*s for parents, s in zip(ancestors, noise)]
    ys = list(y)+[math.tanh(x) for x in xs[m:]]
    residual, jacobian = [], []
    for i in range(m):
        left, right = 2*i+1, 2*i+2
        residual.append((1+cfg['lam']*h)*y[i] - cfg['beta']*h*math.tanh(xs[i]) -
                        (ys[left]+ys[right])/2)
        row = [0.]*m
        row[i] = 1+cfg['lam']*h
        for j in ancestors[i]:
            row[j] -= cfg['beta']*h*(1-math.tanh(xs[i])**2)*ah
        for child in (left, right):
            if child < m:
                row[child] -= .5
            else:
                for j in ancestors[child]:
                    row[j] -= .5*(1-math.tanh(xs[child])**2)*ah
        jacobian.append(row)
    return residual, jacobian, xs


def monolithic_reference(cfg, x0):
    y = [0.]*(2**cfg['steps']-1)
    for iteration in range(24):
        r, jac, xs = residual_and_jacobian(cfg, x0, y)
        norm = max(map(abs, r))
        if norm < 2e-13:
            return {'y': y, 'x': xs, 'max_equation_residual': norm,
                    'newton_steps': iteration, 'outward_rounding_verified': False}
        update = _linear(jac, [-v for v in r])
        for j in range(16):
            candidate = [a+2**(-j)*b for a, b in zip(y, update)]
            trial = residual_and_jacobian(cfg, x0, candidate)[0]
            if max(map(abs, trial)) < norm:
                y = candidate
                break
        else:
            raise ValueError('monolithic reference line search failed')
    raise ValueError('monolithic reference exhausted')
