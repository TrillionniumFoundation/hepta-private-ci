"""Immutable local continuation predictors; never a substitute for original residuals.

The bank shares solved node vectors and Riccati tangent sensitivities over nearby
initial states. Every consumer must independently check the original equation.
Scope/generation/target are identities, not authorization or native owner receipts.
"""
from dataclasses import asdict, dataclass
import math

from four_gate_common import digest, require
from fbsde_coupled import CoupledProfile, forward, residual_report
from fbsde_riccati import newton_direction, solve_newton

TARGET = 'coupled_binary_tanh.root_y_minus_cost.v1'


def validate_context(scope, generation, objective):
    require(type(scope) is str and 0 < len(scope) <= 128, 'bounded explicit scope')
    require(type(generation) is int and 1 <= generation < 2**63, 'exact generation')
    require(type(objective) is str and len(objective) == 64 and
            all(c in '0123456789abcdef' for c in objective), 'objective SHA256')


def tangent(p, x0, y):
    """Differentiate the discrete solution w.r.t. x0 using node-specific P_i.

    For the homogeneous linearized equations, dY_i=P_i*dX_i and
    dX_child=dX_i+a*h*dY_i, with dX_root=1. Affine Newton defects are NOT reused.
    The derivative is evaluated at the supplied trajectory, exact only at its root.
    """
    slopes = newton_direction(p, x0, y)['node_specific_slopes']
    n = len(y); dx, dy = [1.]+[0.]*(2*n), []
    for i in range(n):
        dy.append(slopes[i]*dx[i])
        dx[2*i+1] = dx[2*i+2] = dx[i]+p.a*p.h*dy[i]
    require(all(math.isfinite(v) for v in dy), 'continuation tangent overflow')
    return dy


@dataclass(frozen=True)
class ContinuationBank:
    """Owner-local immutable in-memory values, not an attested or persistent cache."""
    profile: CoupledProfile
    scope: str
    generation: int
    objective: str
    anchors: tuple
    identity: str

    def payload(self):
        return {'schema': 'hepta.fbsde.continuation-bank.v1', 'target': TARGET,
                'profile': asdict(self.profile), 'scope': self.scope,
                'generation': self.generation, 'objective': self.objective,
                'anchors': [{'x0': x, 'y': list(y), 'dy_dx0': list(d)}
                            for x, y, d in self.anchors]}

    def predict(self, p, x0, *, scope, generation, objective):
        validate_context(scope, generation, objective)
        require(p == self.profile and (scope, generation, objective) ==
                (self.scope, self.generation, self.objective), 'stale or cross-scope continuation')
        require(type(x0) in (int, float) and math.isfinite(x0) and
                self.anchors[0][0] <= x0 <= self.anchors[-1][0], 'outside continuation anchor domain')
        x, y, d = min(self.anchors, key=lambda r: (abs(x0-r[0]), r[0]))
        return {'y': [a+(x0-x)*b for a, b in zip(y, d)], 'anchor_x0': x,
                'bank_sha256': self.identity, 'original_equation_verified': False}


def compile_bank(p, anchors, *, scope, generation, objective):
    p.validate(); validate_context(scope, generation, objective)
    require(type(anchors) is list and 2 <= len(anchors) <= 17 and
            all(type(x) in (int, float) and math.isfinite(x) and abs(x) <= p.radius for x in anchors),
            'bounded anchor inventory')
    require(anchors == sorted(set(anchors)), 'strictly ordered unique anchors')
    require(len(anchors)*(2**p.steps-1) <= 20000, 'continuation storage budget')
    rows = []
    for x in anchors:
        y = solve_newton(p, x, tolerance=1e-12)['y']
        rows.append((x, tuple(y), tuple(tangent(p, x, y))))
    b = ContinuationBank(p, scope, generation, objective, tuple(rows), '')
    return ContinuationBank(p, scope, generation, objective, tuple(rows), digest(b.payload()))


def load_bank(data, *, scope, generation, objective):
    """Validate original equations and derivative recurrences, even after rehashing."""
    validate_context(scope, generation, objective)
    require(set(data) == {'schema','target','profile','scope','generation','objective','anchors','sha256'},
            'complete bank envelope')
    body = {k: v for k, v in data.items() if k != 'sha256'}
    require(data['sha256'] == digest(body) and data['schema'] == 'hepta.fbsde.continuation-bank.v1'
            and data['target'] == TARGET, 'bank identity/target mismatch')
    require((data['scope'],data['generation'],data['objective']) == (scope,generation,objective),
            'bank scope/generation/objective mismatch')
    p = CoupledProfile(**data['profile']).validate(); rows = data['anchors']; n = 2**p.steps-1
    require(type(rows) is list and 2 <= len(rows) <= 17 and len(rows)*n <= 20000, 'bank allocation bound')
    parsed = []
    for row in rows:
        require(set(row) == {'x0','y','dy_dx0'}, 'anchor fields')
        x0, y, d = row['x0'], row['y'], row['dy_dx0']
        require(residual_report(p,x0,y)['y_error_bound_exact_arithmetic'] <= 2e-12, 'anchor equation mismatch')
        require(type(d) is list and len(d) == n and all(type(v) in (int,float) and math.isfinite(v) for v in d),
                'finite tangent inventory')
        full_x = forward(p,x0,y); dx = [1.]+[0.]*(2*n)
        for i in range(n): dx[2*i+1] = dx[2*i+2] = dx[i]+p.a*p.h*d[i]
        full_d = d+[(1-math.tanh(v)**2)*dx[n+i] for i,v in enumerate(full_x[n:])]
        residual = max(abs((1+p.lam*p.h)*d[i]-.5*(full_d[2*i+1]+full_d[2*i+2])-
                       p.beta*p.h*(1-math.tanh(full_x[i])**2)*dx[i]) for i in range(n))
        require(residual <= 1e-10, 'tangent equation mismatch')
        parsed.append((x0,tuple(y),tuple(d)))
    require([r[0] for r in parsed] == sorted(set(r[0] for r in parsed)), 'bank anchor ordering')
    return ContinuationBank(p,scope,generation,objective,tuple(parsed),data['sha256'])
