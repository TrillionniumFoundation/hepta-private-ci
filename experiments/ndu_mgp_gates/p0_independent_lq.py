#!/usr/bin/env python3
"""Independent P0 LQ recomputation using the frozen published matrices.

Not a rerun of the frozen generator, independent heldout, stochastic NDU
FBSDE, or dedicated-cloud acceptance. No P0 experiment source imported.
"""
import json
import numpy as np
from scipy.integrate import solve_ivp, quad
from scipy.linalg import expm, solve

A = np.array([[-.25,.1,1.1,.15],[-.08,-.15,.2,.9],[0,0,0,0],[0,0,0,0]])
B = np.diag([.65,.55,.9,.85])
Q = np.array([[1.16,.1,-.55,.05],[.1,1.19,-.11,-.5],
              [-.55,-.11,.5175,-.0025],[.05,-.5,-.0025,.4925]])
R = np.diag([1.,1.3,.4,.45])
H = np.array([[3,.2,-.7,.1],[.2,2.5,0,-.6],
              [-.7,0,.8,.1],[.1,-.6,.1,.9]])
SIGMA = np.array([[.2,.04],[0,.15],[0,0],[0,0]])
X0 = np.array([1.2,-.7,.8,-1.1])
T = 2.
RB = B @ solve(R, B.T, assume_a="pos")
REFERENCE = {
    "no_noise": 2.3951034447285897,
    "with_noise": 2.5007707845830267,
    "qp": [2.5536429674063448, 2.4732041060422265,
           2.433863549625628, 2.4144112373394573]
}
REFERENCE_S0 = np.array([
 [1.0810687838520323,-.013335808278117811,.2986830943346957,.052725249462510095],
 [-.013335808278117818,1.4837894847672188,.07347974175652859,.4639241728751009],
 [.2986830943346956,.07347974175652854,.7683144441356075,.09075228588659778],
 [.052725249462510025,.463924172875101,.0907522858865978,.8971791869246017]
])

def independent_direct_qp(n):
    """Eliminate Euler state equations and solve the complete control normal system."""
    dt = T/n
    F, G = np.eye(4)+dt*A, dt*B
    baseline = np.zeros((n+1,4))
    baseline[0] = X0
    effect = np.zeros((n+1,4,4*n))
    for k in range(n):
        baseline[k+1] = F @ baseline[k]
        effect[k+1] = F @ effect[k]
        effect[k+1,:,4*k:4*k+4] += G
    M = np.zeros((4*n,4*n))
    b = np.zeros(4*n)
    constant = 0.
    for k in range(n):
        E, x = effect[k], baseline[k]
        M += dt * E.T @ Q @ E
        b += dt * E.T @ Q @ x
        constant += .5*dt*x@Q@x
        M[4*k:4*k+4,4*k:4*k+4] += dt*R
    E,x = effect[n],baseline[n]
    M += E.T@H@E
    b += E.T@H@x
    constant += .5*x@H@x
    controls = solve(M,-b,assume_a="pos")
    return float(.5*controls@M@controls + b@controls + constant)

def main():
    def backward(t,flat):
        S = flat.reshape(4,4)
        return -(A.T@S + S@A + Q - S@RB@S).reshape(-1)
    solution = solve_ivp(backward,(T,0),H.reshape(-1),rtol=4e-12,atol=3e-13,
                         dense_output=True,method="DOP853")
    if not solution.success: raise ValueError(solution.message)
    S0 = solution.y[:,-1].reshape(4,4)
    no_noise = float(.5*X0@S0@X0)
    add_noise = quad(lambda t:.5*np.trace(
        SIGMA@SIGMA.T@solution.sol(t).reshape(4,4)),0,T,epsabs=1e-11)[0]
    # Independent Hamiltonian fundamental-matrix boundary solve, never using S0.
    M = np.block([[A,-RB],[-Q,-A.T]])
    transition = expm(M*T)
    f11,f12,f21,f22 = transition[:4,:4],transition[:4,4:],transition[4:,:4],transition[4:,4:]
    adjoint0 = solve(f22-H@f12,(H@f11-f21)@X0)
    trajectory = solve_ivp(lambda t,y:M@y,(0,T),np.r_[X0,adjoint0],
                           rtol=1e-12,atol=1e-13,dense_output=True)
    def running(t):
        y = trajectory.sol(t)
        x,p = y[:4],y[4:]
        u = -solve(R,B.T@p,assume_a="pos")
        return .5*(x@Q@x+u@R@u)
    terminal = trajectory.y[:4,-1]
    bvp_cost = quad(running,0,T,epsabs=1e-11)[0]+.5*terminal@H@terminal
    qp = [independent_direct_qp(n) for n in (16,32,64,128)]
    errors = {
        "riccati_S0":float(np.max(np.abs(S0-REFERENCE_S0))),
        "no_noise":abs(no_noise-REFERENCE["no_noise"]),
        "with_noise":abs(no_noise+add_noise-REFERENCE["with_noise"]),
        "Hamiltonian_cost":abs(bvp_cost-no_noise),
        "Hamiltonian_costate":float(np.max(np.abs(adjoint0-S0@X0))),
        "Hamiltonian_boundary":float(np.max(np.abs(
            trajectory.y[4:,-1]-H@terminal)))
    }
    errors.update({"QP_"+str(n):abs(value-target) for n,value,target
                   in zip((16,32,64,128),qp,REFERENCE["qp"])})
    accepted = len(errors)==10 and all(np.isfinite(x) and x < 1e-7
                                      for x in errors.values())
    result = {"scope":"published_known_LQ_only","independent":True,
              "execution_tier":"host_or_local_preflight_not_dedicated",
              "check_count":len(errors),"pass":accepted,
              "numerical_errors":errors,"P0_heldout_qualified":False}
    print(json.dumps(result,indent=2))
    return 0 if accepted else 1

if __name__ == "__main__":
    raise SystemExit(main())
