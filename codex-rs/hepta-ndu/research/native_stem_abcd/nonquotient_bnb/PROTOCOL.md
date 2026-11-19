# R19 frozen research protocol — genuinely non-quotient forward parameters

Parent R18 Draft PR #2073 HEAD `02c2bd45592dbe4c4156cd08fb52f58811336f1a`. This is an exploratory continuation; previous R18 outcomes/negative results and global CI failures remain unchanged.

### Scientific question and actual model
Retain R18's fully enumerated known two-step finite stochastic law: 16 equiprobable (X,P0,epsilon1,epsilon2) elementary leaves; X and both epsilons in {−1,+1}, P0 in {0,1}; P1=P0 xor [epsilon1=+1], P2=P1 xor [epsilon2=+1]. Two nested positive entropic preferences rho0=1/2,rho1=1; gamma9/10; stage P1/20, terminal (H2-X-1)^2+P2/50; parameter penalty (a²+b²)/4 outside risk.

H1=a X, H2=b H1+(a-b)^2/4+epsilon2/10 + eta*a/(1+a²).
Compare eta=1/25 to eta=0, everything else identical. The eta term is bounded, smooth, nonlinear in an INDIVIDUAL weight: simultaneous negation (a,b)->(-a,-b) preserves t=ab and d=(a-b)^2/4, but changes the output. Hence R18's **exact 2D convex quotient is not valid** for eta>0. Positive entropic recursion and the same actual finite target remain.

### Certification method, no fitted optimality oracle
Let q(a)=eta*a/(1+a²), t=ab, u=(a-b)^2/4+q(a). Write J_eta(a,b)=F(t,u)-q(a), where F(t,u)=C(t,u)+t/2+u is R18's globally m=81/50 strongly convex function on ALL real (t,u). The q term introduces a nonconvex, non-quotient constraint. For a frozen rational candidate theta_c, calculate rational zc=(tc,uc), qc, and interval-certified |gradient F(zc)| via R18's independent outward-10^65 exponential/log arithmetic. This is NOT an exact convex reduction of J_eta.

For all theta, the exact globally valid tangent bound is
J_eta(theta)-J_eta(theta_c) >= qc-q(a) -||g||²/(2m)
  +(m/2)*|| z-zc+g/m ||².
With interval g enclosing the full-population derivative, outward rational upper bound E on ||g||_1, obtain a safe box bound
J_eta(theta)-J_eta(theta_c) >= qc-q_max(box)-E²/(2m)+(m/2)*dist(box_z,ball(zc,E/m))².
q_max(box) is bounded analytically via endpoints and the a=1 critical point, with exact rational arithmetic. A branch-and-bound search on [-3,3]² must retain every leaf and certify a GLOBAL COST-REGRET upper bound. Outside [-3,3]², J>= (a²+b²)/4 >=9/4, while candidate J<9/4 via a finite-branch rational terminal-cost upper bound (risk CE<=maximum branch). Stop after at most 50,000 nodes and report remaining global gap and full frontier. Predeclared useful result threshold: global gap bound <=0.001. If it fails do NOT claim a 0.001 certificate or change node cap. No numerical root, stationary condition or B&B heuristic is a proof premise. Strength of certificate is contingent on the actual bound.

### Frozen matched efficacy census
2 architecture arms eta in {0,1/25} x8 INITIALS exactly R18 [(0,0),(.1,.1),(-.1,-.1),(1,1),(-1,-1),(2,-2),(1,-1),(2,2)] x4 optimizers [Adam lr .03,BFGS,L-BFGS-B,trust-exact] =64 fresh-process fits, 0.75 CPU-second fit cap and explicit whole-child wall/CPU costs. Identity of initial bytes, risk/integration law and target must be checked. Exact 16-leaf full-population objective and analytic gradients/Hessian are supplied to both structured and generic baselines. No optimum or certificate fed to training. Save all initial and terminal weights, all optimizer checkpoints, complete stage/pref branches, errors/logs and after-cap work.

Primary: compare endpoint *certified global regret upper* under eta=1/25, for all 32 solvers/runs, using a common rigorous lower bound and numerical upper scores with explicit FP64 guard. Fixed qualitative pass threshold global upper regret <.001, never replace by gradient stationarity; report all failures including origin saddle. Eta=0 is contemporary known R18 global-reference control, not a different input law.

### Independent auditing and scope
Test algebraic loss identity, symmetry breaking, gradient/Hessian finite differences, independent 16-leaf evaluator, interval q bounds, box-cover correctness, rational gradient versus independently calculated high-precision values. Audit all cases and every checkpoint, adversarially reject source/weight/score/time mutation, retain complete census and negatives. Source and results to stacked draft PR after actual tests; no main merge, production/current/native contract change. CPU-only source slice; FLOPs/energy/GPU/project cloud unavailable.

A global suboptimality **bound** is not a proof of unique global optimizer, nor a general certificate for arbitrary nonconvex deep/FBSDE networks or any LLM/world model. If strict bound remains loose, publish honest failure. Hosted global CI may remain blocked independently.
