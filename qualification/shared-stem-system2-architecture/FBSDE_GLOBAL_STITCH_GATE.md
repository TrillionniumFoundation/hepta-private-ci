# P4 global stitching regression — exact deterministic toy profile

This path checker validates the independent continuous *two-sided interface*
requirement for the finite rational boundary problem

`dX=Ydt; dY=0; X(0)=x0; Y(T)=g X(T)`.

It does not solve stochastic FBSDEs, qualify Brownian/martingale filtration,
compute `Z Sigma=B`, guarantee learned coefficients, or prove task gains.
All outputs are `DENY_ALL` and may be used only as structural negative
controls in the #1923 / #2003 research arms.

The checker rejects malformed/noncanonical values, overlong paths,
zero durations, initial mismatch, each local dynamics mismatch, changes
in forward X or backward Y between segments, terminal mismatch,
nonunique/no-solution singular boundary `1-gT=0`, and a positive
global field pole `gT>=1`. In the remaining admitted special cases it
checks the exact globally implied `Y(0)=g*x0/(1-gT)`.

The counterexample `x0=1,g=1,T=1/2` deliberately solves each
`dt=1/4` segment locally but resets Y between `0` and `4/3`.
The second piece reaches its local terminal relation, yet the whole
trajectory is invalid. The admitted comparison has constant Y=2 and
X endpoints 1 → 3/2 → 2.

Research tests:
`python -m unittest discover -s qualification/shared-stem-system2-architecture -p 'test_*.py' -v`
and identically `python -O -m unittest ...`. This is an independent
research admission regression, not a substitute for the original
`stitch_audit.py` inherited from #1923 or the nonlinear binary tree in
#2003. Do not represent a zero rational residual as a stochastic or
continuous-time general existence theorem.

The more difficult remaining experiment needs genuine forward learned
coefficients plus independently qualified filtration/conditional moments,
full task-level Reader+Decoder outcomes, matched cheap Bellman / Critic
baseline, *all* source and execution cost, and future observation-time
selection before any System 2 learning claim.
