# HCSN P0 scalar QVI numerical gate

Status: RESEARCH_ONLY / DRAFT / DENY_ALL.
all_blockers_closed=false; production_activation_allowed=false.

## Exact parent and defect
Based on #4428 HEAD adf8da8330bca79383c3dd80c878cf90acc9b73a.
Original stopping.py Git blob cd76744cdd67afd3fec8c71e087ceb704c23cc10.

At Stop(drift=-1, diffusion=1e200, discount=.1, cost=0, reset=-1, refractory=0),
the old scalar QVI raises OverflowError from diffusion**2, despite a finite
renewal value and an exact zero continuation generator. Naive subtraction
of nearly equal huge continuation/intervention values also returns zero
for an actually negative obstacle.

The new method uses y=b-x, z=-kappa*y and
A=(b-cost)/(1-exp(-rho*tau-kappa*(b-reset))).
The exact scalar obstacle is
MU-U = y*(kappa*A-1) - A*(expm1(z)-z).
It evaluates the small remainder using a factored series, the characteristic
ODE for the continuation generator, and value matching on the FIRE branch.
For the endogenous threshold it uses the exact smooth-fit identity only
after checking its numerical slope diagnostic. Near the boundary the sign
can be underresolved; these cases raise ArithmeticError, not success.

The 64-ULP scaled sign diagnostic is heuristic, NOT a directed-rounding
interval certificate or a global optimality proof.

## Executed local relevant-module evidence

Tested source Git blob e31d59613c871e11fbe0b905e2cd5acb7eddf8d8;
test blobs 91183755b6b7866bc1f9ceb4fb7aed41c8535818 and
4c852a0c45ad022fc6fee0f75c6ab8ff2df310f4. All remote blobs
match the locally executed bytes.

New witness tests on the exact unchanged parent: 5 errors;
patched source plus original branchpoint/kappa tests plus new modules:
20/20 unittest methods PASS, zero skipped.
Python 3.13, SciPy 1.17; process wall about 1.33 s;
peak RSS 122516 KiB (process-level, not model hardware benchmark).

At x=-1e200 the patched obstacle is -1.936902534571161e199,
continuation generator 0, complementarity 0.
An independent 240-decimal-digit direct calculation for the
rounded supplied boundary differs by 1.144e-16 relative.
At x=b/2, b*0.9 and 0 the unresolvable strict sign is refused.

Deterministic seed 2026103013, 5000 random configurations:
4534 accepted continuation, 4581 accepted FIRE,
419 boundary refusals and 47 QVI refusals.
Among accepted outputs zero positive-obstacle,
positive-generator or positive-complementarity violations.
Refusals are NOT passes and these observations are NOT full-domain proof.

Reproduce by running Python unittest on modules:
experiments.hcsn_hx_unified_v3.test_qvi_stability
experiments.hcsn_hx_unified_v3.test_qvi_stress
experiments.hcsn_hx_unified_v3.test_stop_branchpoint
experiments.hcsn_hx_unified_v3.test_stop_kappa_scale

## Remaining blockers
P0: coupled financial HX boundary/fixed-point/obstacle, rigorous interval
and tail/rounding proof, FP32/fp16 native and global gradient qualification.
P1: causal Call/Risk/Margin mechanism gains (registered failures remain).
P2: long-memory, overwrite and repeated-event quality.
P3: paired text/image/audio/video encoders and OOD generalization.
P4: real Rust/GPU 64/256/1024/4096 Cells, joules and recovery.
P5: matched total-cost backbone advantage.

Only relevant Git-blob-exact local Python CPU tests ran. No full checkout,
complete CI, GPU/power, or production release proof. Keep Draft / DENY_ALL.
