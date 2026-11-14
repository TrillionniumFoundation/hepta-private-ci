#!/usr/bin/env python3
"""Independently recompute PR #3055's published constant-coefficient LQ case.
No frozen source imported, no hidden holdout, no claim on learned generators.
"""
import json
import platform
from pathlib import Path
import numpy as np
import scipy
from scipy.integrate import solve_ivp, quad
from scipy.linalg import expm, solve

A=np.array([[-.25,.1,1.1,.15],[-.08,-.15,.2,.9],[0,0,0,0],[0,0,0,0]], dtype=np.float64)
B=np.diag([.65,.55,.9,.85])
Q=np.array([[1.16,.1,-.55,.05],[.1,1.19,-.11,-.5],[-.55,-.11,.5175,-.0025],[.05,-.5,-.0025,.4925]],dtype=np.float64)
R=np.diag([1,1.3,.4,.45])
H=np.array([[3,.2,-.7,.1],[.2,2.5,0,-.6],[-.7,0,.8,.1],[.1,-.6,.1,.9]],dtype=np.float64)
Sigma=np.array([[.2,.04],[0,.15],[0,0],[0,0]],dtype=np.float64)
x0=np.array([1.2,-.7,.8,-1.1]); T=2.0
BRB=B @ solve(R,B.T,assume_a='pos')

def dre(t,flat):
    S=flat.reshape(4,4)
    return -(A.T@S +S@A +Q -S@BRB@S).reshape(-1)

res=solve_ivp(dre,(T,0),H.ravel(),rtol=4e-12,atol=3e-13,dense_output=True,method='DOP853')
assert res.success, res.message
S0=res.y[:,-1].reshape(4,4)
V0=float(.5*x0@S0@x0)

def trace_term(t):
    st=res.sol(t).reshape(4,4)
    return float(.5*np.trace(Sigma@Sigma.T@st))
noise=quad(trace_term,0,T,epsabs=1e-11,epsrel=1e-11)[0]

# Independently solve the constant-coefficient Hamiltonian BVP with a single
# block matrix exponential, not by sampling the Riccati control policy.
M=np.block([[A,-BRB],[-Q,-A.T]])
F=expm(M*T)
F11,F12,F21,F22=F[:4,:4],F[:4,4:],F[4:,:4],F[4:,4:]
lambda0=solve(F22-H@F12,(H@F11-F21)@x0)
sol=solve_ivp(lambda t,y:M@y,(0,T),np.r_[x0,lambda0],rtol=1e-12,atol=1e-13,dense_output=True)
xt,lt=sol.y[:4,-1],sol.y[4:,-1]

# Independently integrate the Hamiltonian cost along the boundary-satisfying
# state/costate trajectory.
def running(t):
    y=sol.sol(t); x=y[:4]; p=y[4:]; u=-solve(R,B.T@p,assume_a='pos')
    return .5*(x@Q@x+u@R@u)
V_bvp=quad(running,0,T,epsabs=1e-11,epsrel=1e-11)[0]+.5*xt@H@xt

# Euler multiple-shooting direct uncondensed QP: construct the full impulse
# response of states from each control column; solve its normal equations.

def direct_qp(N):
    dt=T/N;F_step=np.eye(4)+dt*A;G_step=dt*B
    n=N*4; states=np.zeros(((N+1)*4,n)); baseline=np.zeros((N+1,4));baseline[0]=x0
    for k in range(N):
        baseline[k+1]=F_step@baseline[k]
        states[(k+1)*4:(k+2)*4]=F_step@states[k*4:(k+1)*4]
        states[(k+1)*4:(k+2)*4,k*4:(k+1)*4]+=G_step
    m=np.zeros((n,n));r=np.zeros(n); constant=0.
    for k in range(N):
        G=states[k*4:(k+1)*4]; x=baseline[k]
        m+=dt*G.T@Q@G
        r+=dt*G.T@Q@x
        constant+=.5*dt*x@Q@x
        m[k*4:(k+1)*4,k*4:(k+1)*4]+=dt*R
    G=states[N*4:(N+1)*4];x=baseline[N]
    m+=G.T@H@G;r+=G.T@H@x;constant+=.5*x@H@x
    u=solve(m,-r,assume_a='pos')
    return {'cost':float(.5*u@m@u+r@u+constant), 'stationarity_max':float(np.max(np.abs(m@u+r))), 'n_controls':n}

qp={str(k):direct_qp(k) for k in [16,32,64,128]}
reported={'S0':[[1.0810687838520323,-.013335808278117811,.2986830943346957,.052725249462510095],[-.013335808278117818,1.4837894847672188,.07347974175652859,.4639241728751009],[.2986830943346956,.07347974175652854,.7683144441356075,.09075228588659778],[.052725249462510025,.463924172875101,.0907522858865978,.8971791869246017]], 'V_no_noise':2.3951034447285897,'V_with_noise':2.5007707845830267, 'QP16':2.5536429674063448,'QP32':2.4732041060422265,'QP64':2.433863549625628,'QP128':2.4144112373394573}
checks={
 'riccati_S0_vs_published':float(np.max(np.abs(S0-np.array(reported['S0'])))),
 'cost_with_noise_vs_published':float(abs(V0+noise-reported['V_with_noise'])),
 'cost_without_noise_vs_published':float(abs(V0-reported['V_no_noise'])),
 'Hamiltonian_BVP_cost_vs_Riccati':float(abs(V_bvp-V0)),
 'Hamiltonian_initial_costate_vs_Riccati':float(np.max(np.abs(lambda0-S0@x0))),
 'Hamiltonian_terminal_boundary':float(np.max(np.abs(lt-H@xt))),
 'QP16_cost_vs_published':float(abs(qp['16']['cost']-reported['QP16'])),
 'QP32_cost_vs_published':float(abs(qp['32']['cost']-reported['QP32'])),
 'QP64_cost_vs_published':float(abs(qp['64']['cost']-reported['QP64'])),
 'QP128_cost_vs_published':float(abs(qp['128']['cost']-reported['QP128'])),
}
allowed={k:(1e-7 if k.startswith('QP') else 1e-7) for k in checks}
passed=all(np.isfinite(v) and v<=allowed[k] for k,v in checks.items())
out={'schema':'hepta-p0-independent-lq-recomputation-v1','parent_paper_scope':'known_linear_quadratic_system_only','source_reference':'TrillionniumFoundation/hepta-private-ci PR 3055 / oracle/development_results.json','execution_tier':'current_session_cpu_independent_implementation','runtime':{'python':platform.python_version(),'scipy':scipy.__version__,'numpy':np.__version__},'results':{'S0':S0.tolist(),'V0_no_noise':V0,'V0_with_noise':V0+noise,'Hamiltonian_cost':V_bvp,'qp_mesh':qp},'absolute_differences':checks,'checks_passed':passed,'experimental_heldout_completed':False,'dedicated_cloud_accepted':False,'full_P0_qualified':False}
path=Path(__file__).with_name('p0_independent_recomputation.json');path.write_text(json.dumps(out,indent=2)+'\n')
print(json.dumps({'checks_passed':passed,'results':{'V0_no_noise':V0,'V0_with_noise':V0+noise,'Hamiltonian_cost':V_bvp},'absolute_differences':checks,'receipt':str(path)},indent=2))
raise SystemExit(0 if passed else 1)
