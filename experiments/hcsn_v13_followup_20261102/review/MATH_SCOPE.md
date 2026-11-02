# V13 financial-channel qualification and independent reference audit

This review reads the actual inherited `hcsn_hx_unified_v3/hx.py`, not the V10
finite CTMC filter. The inherited source SHA256 is
`f7089527461983ebfd53ce82d95a124314a797fc57ed40386ad2e8d4b75e1d19`;
Git blob `55f4b4e9f5fd83cfa41b02f30b5a7520680f9086`. It is a scalar SciPy/math
precision reference and is explicitly not a differentiable production kernel.

## Primary source and mathematical identity

The primary source is He and Xiong, *Rollover Risk and Credit Risk*, Journal of
Finance 67(2), 2012, DOI `10.1111/j.1540-6261.2012.01721.x`, the authors'
[39-page journal PDF](https://www.princeton.edu/~wxiong/papers/rollover.pdf).
The web retrieval opened that PDF and inspected equations (1), (8), (9), (11),
(12), and (A7), including the appendix boundary argument. A local byte-identical
PDF was not obtained, so no paper-file hash is claimed.

The paper's equity equation contains bond issuance proceeds minus maturing
principal. Its endogenous default boundary obeys zero equity and zero equity
slope. Equation (12) supplies the boundary and (A7) its equity solution. `F` is
the first-hit probability and `G` a discounted first-hit factor. Neither is an
independent put-option payoff. Applying these functions to neural latent states
is an explicitly new analogy; it is not validation of a financial equilibrium
for audiovisual data.

## Actual bounded reference checks

`reference001/PLAN.json` freezes parameters, source identities and numerical
tolerances before calculation. `reference001/RESULT.json` passes **117 checks**:

- Default parameters give `VB=64.62517667527493`. At seven declared interior
  points `log(V/VB)` from `.02` to `2`, equity is nonnegative and A7 differs
  from a separate killed-diffusion Green resolvent by at most `2.84218e-13`.
  The independent resolvent shares the inherited bond evaluator; it does not
  independently certify every financial formula.
- The log-coordinate equity ODE, evaluated using five-point finite differences
  wholly above the barrier, has maximum absolute residual `4.03405e-7`.
- At 21 point/time pairs, `F` and `G` agree with separate quadratures of the
  first-passage density and its discounted version, and `0<=G<=F<=1`.
- One-sided boundary differentiation at log step `.001` gives equity slope
  `-1.45040e-9`; positive interior values approach the boundary continuously.
  Zero-hazard and small-hazard removable limits also agree with the resolvent.
- The inherited corner contract is pinned: default has priority at `V<=VB`,
  including `tau=0`; a surviving zero-time bond instead pays principal.

The outer fresh-worker receipt is
`receipts/reference001/RECEIPT.json`: **0.583942 CPU seconds**, including its
waited supervisor/task boundary. Inner timings must not be added again. An
earlier read-only exploration cost **0.379491 self CPU seconds as a lower bound**;
it did not have the full wrapper boundary and remains a separate incomplete
scope. Its near-boundary central stencil crossed the default branch and gave
an ODE residual about `-0.8511`; that is not an interior ODE check and was not
silently treated as a passing reference point. Formal checks use one-sided
boundary derivatives and interior stencils.

These are numerical observations on fixed points and bounded regimes, not a
global parameter-domain proof, a continuum error bound, or neural acceptance.

## Actual Torch and sampled-model execution

`audit_torch_port.py` and `port001/` pass **90 checks** of all four financial
values, endpoints, FP64 asset gradients, and the five normalized neural features'
log-asset gradients. Two finite-difference step sizes independently recompute
the inherited scalar function. The negative control really detaches its asset:
its forward values are unchanged, its asset derivatives become zero, and the
derivative gate rejects it. Declared coalescent exclusions also reject actual
zero-hazard constructors. The wrapper CPU is **2.255448 seconds**. A harmless
Tensor-to-float warning during a value-only diagnostic is retained in stderr;
it does not detach the audited derivative computations.

`audit_model_contract.py` and `model001/` pass **53 checks**. Full/margin/ordinary
arms initialize every common state-dict value identically under the same seed.
Actual constructed forwards execute 16 resets and 16 restorations; state is
held exactly while inactive. The review identified full elapsed time being
applied after cooldown. The model was corrected before this final audit: with
`.75` elapsed and `.5` initial cooldown, only `.25` active duration affects
membrane drift and content decay. The independent expected content is
`0.5*exp(-log(2)*.25)`, and both drift and decay agree.

Changing the financial boundary with the absolute asset anchor held fixed
changes an actual content step. A real constructed cross-entropy objective
backpropagates through the financial map, and an optimizer actually changes
asset-drive, gate, content-candidate and reader parameters. A guard that forbids
financial `forward` still permits the ordinary bank to execute. This does not
mean its shared constructor never computes the common fixed boundary units.
The model wrapper CPU is **3.450512 seconds**.

These event/gradient witnesses are constructed branch checks, not events from
the later formal fit and not evidence of task improvement. Formal training must
report its own gradient/parameter changes and reset/restoration counts. Hard
crossing decisions and reset masks do not provide a differentiable event-time
or surrogate-gradient certificate. Numerical gradient checks concern smooth
continuation interiors, not the nonsmooth probability contact at the barrier.

The three disjoint complete review wrappers total **6.289902 CPU seconds**.
The earlier unwrapped `.379491` self-CPU lower bound is separate and cannot be
mistaken for a fourth complete envelope. Ten balanced source schedules are
admitted under explicit mandatory first audio A1, not all twenty possible
three-audio/three-video orders.

## Architecture and training admission contract

1. A differentiable FP64 port must agree with the scalar reference on complete
   equity, bond, boundary, `F`, and `G` values. Asset/log-asset gradients require
   independently recomputed finite differences at multiple step sizes;
   finite output with a detached asset is a failing negative control.
2. Fixed financial parameters with trainable asset encoding and common content
   head constitute genuine end-to-end content training through financial
   channels. That closes this specific implementation gap only. It does not
   establish all-financial-parameter training or a task-learned free boundary.
3. Asset scale must be declared independently of the barrier for a boundary
   intervention. Actual counterexample: at fixed absolute asset, increasing
   `VB` by 3% changes `F` by `+0.05682203726`; co-moving `V=VB*exp(.2)` makes
   that change exactly zero. A normalized log-distance input cannot by itself
   demonstrate a causal boundary contribution. The final model now stores an
   independent absolute anchor; that engineering correction permits the
   constructed intervention without establishing a task-level boundary gain.
4. Train the full and declared reduced-channel networks independently, with
   matched initial states, inputs, targets, schedules and complete recorded
   costs. Cross-evaluate each fit under both execution mechanisms. A same-weight
   execution ablation alone is not a retraining result.
5. Strong ordinary history/GRU/SSM references must receive the same entire legal
   observation history. Report capacity and actual CPU; equal updates are not
   equal compute. Model selection and calibration must be separate from test
   scoring, and exposed historical AV objects remain development evidence.
6. An observation-driven asset crossing followed by a declared neural reset is
   a new executable neural rule. It is not the paper's absorbing default, exact
   continuous first-hit timing, repeated within-interval renewal, or a learned
   full conditional propagation law. Those larger claims remain HOLD until
   separately implemented and exercised on actual forward trajectories.
7. A gate must be materially consumed by content state updates and receive
   nonzero end-to-end gradient/parameter changes. Recording a financial feature
   after inference is not integration. A reset that is never reached is not
   exercised coverage; true crossing and no-crossing cases are both required.

The intended minimum next claim is therefore fixed-law, exact-financial-channel
content/asset joint training with explicit sampled crossing semantics and
retrained channel interventions. Quality advantage, complete continuous
first-passage/reset integration, strong frontend admission, and full economics
remain separate gates.
