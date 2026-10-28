# V5 independent theory and protocol review

Status: **EXPLORATORY DESIGN; NO NEW EFFICACY OR PRODUCTION QUALIFICATION**.

This review preserves the V4 terminal result and the original B01--B10
criteria. It does not turn a failed effect into a passed blocker. The source
baseline is `0acfd9b27db910c180b0d8911f39aea469b7f864`, particularly
`field_bridge_v3_20261027/{training_bank,training_policy,learning,training_features}.py`
and `field_bridge_v4_20261027_review/{BLOCKERS,NEW_STUDY_CONTRACT}.json`.
Paths in this paragraph are relative to `experiments/multimodal_output_portfolio/`.
The latter contract is the historical V3-to-V4 proposal; V4 has already run.
V5 needs its own source, algorithm, budget, data-role and result identities.

## 1. What the reference target means

Use the reward convention: larger values are better. For a fixed finite
horizon, complete state `s`, and a fixed feasible reference policy `pi_ref`,

\[
Q_t^{\rm ref}(s,a)=r_t(s,a)+
\mathbb E[V_{t+1}^{\rm ref}(S_{t+1})\mid s,a],\qquad
V_t^{\rm ref}(s)=Q_t^{\rm ref}(s,\pi_{\rm ref,t}(s)).
\]

The transition in this definition includes the actual guard, rollback,
clock, budget and action-admission behavior. A sufficient-state candidate
for training contains parameters, every optimizer variable, time/schedule,
remaining resources, the immutable guard baseline and relevant data/context
identities. Hidden quantities require an appropriate history or belief;
listing a short observation vector does not prove its sufficiency.

The V3 bank executes one candidate block followed by the registered guarded
reference through the fixed terminal step. Its same-schedule, exact-prefix
checks are useful implementation evidence. Each recorded label is still a
complete **realized return** `G_ref(s,a;omega)`. One realized future schedule
does not integrate over future marks to give an exact expected `Q_ref`.
Paired schedules can reduce contrast variance; they do not remove it.

`Q_ref` need not equal the value of the adaptively replanned deployed policy.
That is not automatically an algorithm error: reference values can support
policy improvement. It is an error of interpretation to label them as
calibrated predictions of the deployed policy's final value without a
separate justification. A rolling fixed-H window also needs its own
terminal/receding-horizon argument; it is not the fixed-terminal proof below.

## 2. Conditional improvement and error-budget proposition

**Exact statement.** Fix the same finite horizon, terminal reward, legal
action set and guarded transition for both policies. Suppose the new policy
selects only feasible actions and, at every relevant time and state,

\[
\mathbb E_{a\sim\pi_t(\cdot\mid s)}Q_t^{\rm ref}(s,a)
\ge V_t^{\rm ref}(s)-\delta_t(s),\qquad \delta_t(s)\ge0.
\]

Then, from a common initial state/law,

\[
V_t^\pi(s)-V_t^{\rm ref}(s)
\ge-\mathbb E_\pi\!\left[\sum_{k=t}^{T-1}\delta_k(S_k)\mid S_t=s\right].
\]

In particular, `delta=0` gives improvement relative to the reference.
The expectation is under the **new policy's occupancy**. A bound verified
only on reference-policy states is insufficient unless it extends to the
newly reached states.

**Proof.** Define the reference advantage `A_ref=Q_ref-V_ref`. Inserting
`Q_ref=r+P V_ref`, summing along the new policy and using the common terminal
reward telescopes to
`V_pi - V_ref = E_pi sum A_ref(S_k,A_k)`. Apply the assumed lower bound.
This proof also works with full histories as states. It does not replace
the assumptions with a low-dimensional-state claim.

**Sufficient interval gate.** Suppose actual, simultaneously valid errors
are supplied for every queried feasible action:

\[
|\widehat Q_t(s,a)-Q_t^{\rm ref}(s,a)|\le\epsilon_t(s,a).
\]

Let `a_star` maximize `Q_hat` over legal actions, with a fixed tie rule. Use
it only if

\[
\widehat Q_t(s,a_*)-\epsilon_t(s,a_*)>
\widehat Q_t(s,a_{\rm ref})+\epsilon_t(s,a_{\rm ref});
\]

otherwise execute the reference action. Each deviation then has positive
true reference advantage, and fallback has zero advantage. Missing,
nonfinite or negative error budgets must be rejected, not called certified.
A known direct bound on advantage error can replace the sum of the two
actionwise error budgets. Ungated approximate greedy actions with a uniform
error `epsilon_t` instead give the familiar per-step `2*epsilon_t` bound.

The hypothesis is the substantive part: a deployment-wide deterministic
bound, or a justified simultaneous probabilistic event over the actual
queries, must be supplied. A finite residual table is not that hypothesis.
The NumPy tests in `policy_improvement_tests.py` verify finite-MDP examples
and counterexamples; they do not certify a neural estimator.

## 3. The proposed empirical gate is a new heuristic, not a certificate

For each frozen model/representation and the already selected ridge, define
the baseline-action advantage residual from its held-out trajectory rows.
Here `a_b` is the fixed strong ordinary action, while the labels still use
the historical reference continuation:

\[
e_{i,a}=(\widehat Q^{(-i)}(x_i,a)-\widehat Q^{(-i)}(x_i,a_b))
       -(G_i(a)-G_i(a_b)),\qquad
\tau_{\rm model}=\max_{\rm mode\in\{field,richer\},i,a}|e_{i,a}|.
\]

The two representations share this pooled threshold within each model.
The concrete candidate uses the frozen full-fit head and normalizer. It
deviates from the ordinary baseline only when its
predicted advantage is strictly greater than this frozen nonnegative
threshold. Ties and insufficient margins return to the ordinary baseline. The ridge,
representation, threshold formula and tie rule must not be selected again
after looking at the new development results.

This gate changes the policy; subtracting a common target baseline from a
fixed linear ridge head does not. However, `tau` is an empirical safeguard:
the held-out heads differ from the full-fit deployment head, labels contain
single-tail realization error, the four fitting trajectories share panels,
and the new policy can reach new states. Four trajectories cannot yield a
nonvacuous ordinary 95% split-conformal maximum-trajectory guarantee.
Neither the maximum residual nor cross-validation establishes the uniform
error event in Section 2. Do not name the candidate a certified/safe policy.

The label reference is the policy used to construct `Q_ref`. For seed 17
it is action index 1 (multiplier 0.25), while the fixed ordinary fallback
is index 2 (multiplier 1). For seeds 29/43 both are index 3 (multiplier 2).
The seed-17 mismatch is intentional and must be recorded, not normalized
away. Even exact advantages under a different tail policy need not give
improvement relative to the fallback baseline: the independent test
includes an explicit complete-state counterexample. Claiming that theorem
for ordinary would require a different justification or `Q_ordinary`.
Every actual V5 method has `certificate=false`, including the other seeds.
Field and richer controls receive the same threshold construction, baseline
information, permitted actions and accounting opportunities.

The inherited V4 initial-panel translation may be reused as shared frozen
preprocessing. It is the identity on the old fit domain and uses only the
current phase's legal step-zero probe/guard measurements. Preserve its
extra readonly calibration context and costs. Reuse does not change the
V4 failed field-gain result or create a new head fit.

## 4. Guard granularity is a separate exploratory intervention

The historical guard checks each 48-step transaction and restores complete
parameters, optimizer, gradients and RNG on rejection. Rejection still
advances logical time and charges the attempted computation. Action zero
consumes the scheduled block without advancing parameters or momentum; it
is not an early terminal stop. These semantics belong in target generation
and deployment alike. The reviewed V3 bank already used `guarded_block`;
this review does not allege that it omitted the historical guard.

The registered guard-8 candidate retains 288 scheduled microsteps and six
48-step policy decision windows. Hold one selected multiplier fixed inside
each decision window; execute six consecutive 8-step transactions. Each
transaction uses the unchanged original guard baseline and threshold.
On rejection restore the **current transaction's** entry state, preserve
earlier accepted prefixes, consume its eight schedule positions, and charge
all attempted work. Do not restore the whole 48-step prefix or retry the
same positions for free. The scientific protocol must fix exception and
nonfinite behavior before execution as well.

This changes the transition kernel. The old head predicts a guard-48
reference tail, and its old residual threshold does not certify guard-8
behavior, even when every comparator also uses guard-8. Treat this as a
frozen-model transfer experiment with no new head fit. At minimum include
the identical guard-8 ordinary and richer controls and preserve guard-48
references, so improved rollback granularity is not relabeled as a field
advantage. Guard-8 makes 36 routine checks instead of six per full path;
record the actual generator/observer work, rollback count, time and memory.
Equal gradient counts alone do not establish equal total compute.

## 5. Evidence needed before advancing beyond development

- Freeze all input hashes, reference actions, heads, thresholds, schedule
  IDs, method names, guard variants, sample counts and resource ceilings.
- Keep every old path/result intact. Previously inspected V3/V4 panels are
  development data now; their reuse supplies no new independent confirmation.
- Verify accepted/rejected/zero/exception transaction state, logical-clock
  advancement, exact scheduled work and original frozen-base identity.
- Retain every action, predicted advantage, threshold, fallback reason,
  guard decision and actual after-state. Report fallback and reject rates
  by model and full trajectory, together with both observers' terminal
  outcomes and the original clean margin.
- Independently score actual emitted media. After a first action divergence,
  the old policy's later log cannot stand in for the candidate's rollout.
- Distinguish head prediction error, reference-action regret, full-path
  outcome, and guard-transfer error. A one-schedule counterfactual is not an
  expected-value oracle and a state change is not an efficacy result.
- Stop this fixed exploratory design at its declared end. Preserve every
  adverse result; do not increase samples, change thresholds or select a
  weaker comparator to make an old blocker pass.

A favorable development result would motivate a separately frozen new
source-disjoint qualification/confirmation. It would not itself close
B03--B07, erase the historical B09 qualification, establish scalar
FBSDE/HJB identification, or alter `DENY_ALL`, calibration and owner-
integration boundaries. An unfavorable result is a valid completed study;
the unestablished scientific claim remains unestablished.

### Fixed V5 development scope supplied for implementation review

The registered factorial has three methods (strong ordinary, empirical-gated
field, empirical-gated richer) crossed with guard sizes 48 and 8. It uses
three fixed models, four predeclared schedules `6000,6001,6002,6003` and only
previously exposed V3 development roles: **72 complete paths**. It opens no
new qualification, primary, retention or runtime holdout. This review fixes
the interpretive limits before those outputs; actual execution, source
hashes, resources and independent integrity checks require their own records.

## 6. Independent implementation review before scientific execution

The reviewed V5 source is `run.py`, `transactions.py`, `calibration.py`,
`records.py`, `audit.py` and `PROTOCOL.json` in this directory. This section
records the pre-execution review on 2026-10-28; the execution source freeze
must identify the final bytes. It is a source/protocol review, not a claim
that the planned 72 scientific paths have already run successfully.

### Scientific and transaction semantics

- The calibration code replays the already selected whole-trajectory OOF
  folds and checks their saved predictions and fit-row counts. It pools
  action-minus-**strong-ordinary** advantage residuals over both heads into
  one threshold per seed. It does not reselect a ridge or fit a new head.
  Its target remains the old reference-tail realization. In particular,
  the seed-17 label reference is action 1 and its fallback is action 2.
- Field and richer use the same frozen origin transformation and threshold
  construction. Ordinary skips feature measurements it does not need.
  All successful paths consume 288 scheduled gradient steps, but ordinary
  and the two instrumented methods do not have identical total compute.
  This distinction is explicit in the registered cost statement.
- A macro decision is made once per 48 scheduled steps. Its action is
  fixed across all six guard-8 transactions. The same model seed,
  schedule ID and logical step produce the same data/noise marks. A
  rejection advances to the next scheduled slice, without a free retry.
- Guard-8 snapshots each slice, preserves accepted prefixes and restores
  only the currently rejected or exceptional slice. Its checks use the
  original immutable guard baseline. Guard-48 delegates to the original
  V3 transaction implementation with unchanged arguments. Neither branch
  changes the original label bank or claims that its tail matches the
  new deployed policy.
- The original learning primitives reject nonfinite loss/gradient or
  hard-panel utility. The wrapper restores the active slice and aborts
  the path on an exception. An exceptional path is not a completed
  288-step observation. Its actual counters and elapsed time are retained;
  a completed-step counter must not be interpreted as counting the
  partially failed backward operation as a successful microstep.
- Training instantiates only the four registered old development roles;
  evaluation instantiates only the two registered old development endpoint
  roles. The corpus loader may read raw dataset files for hashing and
  validation. Thus `new_holdout_access=false` means no new holdout role is
  constructed or evaluated; it does not assert that unrelated raw dataset
  bytes were never read by the loader.

### Execution-integrity findings and implemented corrections

The first source review identified failure-handling and binding defects
that could invalidate a completed-run claim. The subsequently reviewed
source addresses them as follows:

1. The final source check runs **before** `COMPLETE.json` is written.
   Completion and verification reject a stage with `FAILED.json`; the
   exact file inventory and every sealed file hash must agree.
2. Endpoint evaluation verifies each training phase against the current
   study, freeze, protocol, phase and seed. All three 24-path training
   phases must be sealed before endpoint evaluation starts. Checkpoint
   metadata binds its method, schedule, study and development role.
3. Both transaction grains retain exception receipts with actual work.
   An active training path retains its own failure and resource receipt;
   the phase retains its cumulative counters, elapsed CPU/wall time and
   error. Partial outputs are preserved rather than silently rerun.
4. The source check requires the V5 Python files, protocol and calibration
   in the freeze, checks the registered role lists, and checks protocol
   baseline actions against calibration and reference actions against
   the bank. The registered commit must be a 40-digit hexadecimal ID.
5. Each trace record binds its index, predecessor hash, contents and
   monotonic timestamp. The artifact audit independently checks the
   chain, recorded decisions, paired schedules, accepted/rejected states,
   resource sums, final stored checkpoint tensors and endpoint byte
   hashes. It evaluates no new neural model.

These corrections remove the identified source-level execution blockers.
They do not guarantee efficacy or authorize changing the protocol after
execution begins. Actual phase seals, full trace census, resource reports
and artifact-audit success remain conditions for accepting a completed run.

### Independent tests and their limits

The following commands passed with the isolated pinned runtime
`/workspace/scratch/e8a4dc33549f/runtime_v5/bin/python` (Torch `2.8.0+cpu`,
NumPy `2.3.5`), from the repository root:

```text
python -m experiments.multimodal_output_portfolio.field_bridge_v5_20261027.policy_improvement_tests
python -m experiments.multimodal_output_portfolio.field_bridge_v5_20261027.transactions_tests
```

`policy_improvement_tests.py` passed eight tests. Independent backward
reference values and forward occupancy evaluation establish exact-greedy
and interval-gate examples on finite MDPs, including the performance
difference identity and accumulated approximate-greedy error bound. The
counterexamples show failure under the wrong guard, hidden-state aliasing,
a lucky single tail, unsupported extrapolation of old residuals, and a
mismatched fallback policy. They illustrate the proposition's necessary
premises; they supply no neural-model error certificate.

`transactions_tests.py` passed six tests using direct imports of the real
transaction module and learning dependencies. Synthetic state/learning
primitives then isolate the wrapper: accepted prefixes survive later
rejection; all-reject paths consume work and restore entry state; zero
actions charge gradients/guards without optimizer advance; an exception
restores only its active slice and preserves partial costs; guard-48
delegates unchanged and retains delegated exception costs. No scientific
model, corpus or endpoint was executed. These tests do not independently
re-prove the inherited Torch snapshot/restore implementation, whose source
was also inspected. A preliminary system-Python invocation lacked Torch
and stopped at import, before any test or model execution; the successful
tests use the real pinned dependencies, with no replacement import loader.

No current-source defect found by this review justifies relabeling a V4
scientific negative result as a software-only failure. V5 remains a new,
bounded empirical policy/transaction study. Its seed-17 baseline mismatch,
guard-8 kernel transfer, exposed development panels and noncertified
threshold remain interpretation limits even if all execution checks pass.
