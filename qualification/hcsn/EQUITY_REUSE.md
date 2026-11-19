# Reusing full HX equity expressions inside a sequence

`hx_dual` keeps the original direct evaluation. `hx_dual_prepared` opts into
`ValueKernelCell(..., equity_evaluation="prepared")`, with identical parameter
names, counts and seeded initialization. MatchedGateCell retains its own
feature hook. The original `hx_equity` implementation remains unchanged.

The conditional cell scales coupon, principal and boundary by the same
`s=exp(shift)`. Full HX equity is jointly degree-one homogeneous:
`E(x;s*coupon,s*principal,s*b)=s*E(x;coupon,principal,b)`. The prepared path
uses this identity to keep the base parameters constant within a forward.
It prepares roots, four unshifted log-tail differences and the same eighth
order boundary coefficients once; shifted tails and state-dependent terms
are still evaluated at every step. Normal-tail series, continued fractions,
cutoffs and economic checks retain the existing formulas.

The context belongs to one forward/autograd graph. It is neither detached
nor saved in the module, and is rebuilt after every optimizer update. No
channel is removed and no physical parameter is frozen. Standalone `step`
retains direct evaluation unless an explicit same-graph context is supplied.

The tests compare FP32/FP64 values and all nine physical gradients, supplied
and endogenous boundaries, zero liquidity, near-boundary expansions, the
64 cell parameter corners, complete sequence/input/parameter gradients and
graph rebuilding after weight updates. The 24 existing tensor/Cell tests
and four added tests pass; raw logs are in
[`evidence/equity-reuse-20261119`](evidence/equity-reuse-20261119).

`equity_reuse_study.py` imports the actual frozen baseline sources only
after checking their SHA256. Every timed sample includes a fresh full
forward graph and backward. Raw interleaved wall times are retained;
process CPU times distinguish CPU work from scheduling delay. Short
sequences can pay more preparation overhead, and shared-host wall times
can be noisy. The optional mode is evaluated separately in the task study.

For the next task study's FP32 `B32,T16,H8,input2` shape, attempt003 measured
median full-forward/backward wall times of 0.502s direct and 0.363s prepared
(1.38x); process CPU times were 0.496s and 0.362s (1.37x). Other shapes include
slowdowns: FP64 single-step preparation took about 1.25x the direct cost,
and shared-host runs varied materially. Both complete timing attempts remain
in the evidence directory; no universal speedup or task-quality gain is claimed.

An extended stress probe, outside the Cell's maturity range, remains
unresolved: FP32 `maturity=.05,x=12` returns finite equity but nonfinite
gradients in both frozen direct and prepared evaluation. The paired
shifted log tails round to identical values near -36000, so their
log difference reaches `log(0)` and contaminates backward. The raw value
and all gradients are preserved in the study output; equal NaNs are not
counted as an equivalence pass. No clipping or tail-branch replacement is
introduced by this optimization.

That failure describes the frozen optimization-study source. The subsequent
[tail-stability repair](TAIL_STABILITY.md) retains this original observation
and fixes the reproduced gradient failure separately; it does not revise these
timings or the frozen Cell training results.
