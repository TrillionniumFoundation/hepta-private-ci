"""Independent adapted-action quadratic program, not a policy-value recursion."""
import numpy as np


def dense_tree_reference(problem,s0,mode0):
    depth=problem.horizon;nodes=sum(4**k for k in range(depth));nvar=nodes*3
    H=np.zeros((nvar,nvar));b=np.zeros(nvar);c=0.;cursor=0
    frontier=[(np.array(s0),np.zeros((6,nvar)),mode0,1.)]
    for k in range(depth+1):
        successors=[]
        for s,L,p,prob in frontier:
            Q=problem.terminal[p] if k==depth else problem.Q[p]
            weight=problem.gamma**k*prob
            H+=weight*(L.T@Q@L);b+=weight*(L.T@Q@s);c+=weight*(s@Q@s)
            if k==depth:continue
            pick=np.zeros((3,nvar));pick[:,cursor:cursor+3]=np.eye(3);cursor+=3
            H+=weight*(pick.T@problem.R[p]@pick)
            for nxt in range(2):
                for sign in (-1,1):
                    successors.append((problem.F@s+sign*problem.noise[p],problem.F@L+problem.G@pick,
                                       nxt,prob*problem.transition[p,nxt]/2))
        frontier=successors
    u=-np.linalg.solve(H,b)
    return dict(cost=float(c+b@u),first_action=u[:3],kkt_residual=float(np.max(np.abs(H@u+b))),
                minimum_hessian_eigenvalue=float(np.linalg.eigvalsh(H).min()),dimension=nvar)
