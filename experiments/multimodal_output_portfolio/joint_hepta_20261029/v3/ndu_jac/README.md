# NDU-JAC: bounded joint-control research reference

This package implements and challenges one finite-horizon, risk-sensitive joint-control model. It provides executable mathematics, sampled-model actor training, critic diagnostics, and paid conditional comparisons. **It establishes neither algorithmic originality nor superiority over ordinary planning, and grants no production or full-CI qualification.**

## Objective and implementation map

Freeze the external score, cost prices, risk parameter, legal actions and model/objective version. The state can include belief/history, an internal configuration, remaining resources, residency and elapsed time. Actions may acquire evidence, reconfigure, stop or skip. For one jointly sampled reward/cost/duration/successor outcome, use

\[
X=R-C-\kappa+e^{-\rho\Delta t}V(S'),\qquad
Q(s,\alpha)=-\eta^{-1}\log E[e^{-\eta X}\mid s,\alpha],\qquad
V^\pi(s)=\sum_\alpha\pi(\alpha\mid s)Q(s,\alpha).
\]

STOP has zero continuation. **Action randomization is mixed outside the certainty equivalent.** Moving that mixture inside the exponential, or applying one exponential utility to a complete trajectory, changes the target. `THEORY.md` gives explicit counterexamples and distinguishes this model from existing exponential actor-critic objectives.

The policy score at step `t` receives the historical weight `w_t`; the current outcome tilt and actual-duration discount propagate to `w_(t+1)`. Ordinary returns, GAE and arbitrary group normalization are not substitutions for that derivative. Estimated conditional moments/normalizers generally introduce finite-sample bias.

| Component | Purpose |
|---|---|
| `core.py`, `test_core.py` | Stable entropic evaluation, exact finite DP, recursive actor gradient and adversarial controls |
| `finite_study.py` | Joint sensing/configuration/STOP task; sampled-model actor versus same-bank DP |
| `critic_study.py` | Proper moment loss, direct internal derivatives, intervention checks and critic exploitation counterexample |
| `paid_audit.py`, `paid_study.py` | Frozen conditional moment differences, independent reset controls, actual repeated estimators and Hoeffding rejection/adoption |
| `variance_audit.py`, `variance_followup.py` | Separately labeled fresh-stream empirical-Bernstein follow-up |
| `policy_gate.py` | Sufficient whole-policy gates conditional on simultaneous baseline-Q or initial-value coverage |
| [THEORY.md](THEORY.md) | Assumptions, proofs, non-transfer results and inspected primary references |
| [evidence/validation.json](evidence/validation.json) | Original source hashes, commands, artifact hashes and local validation receipt |
| [evidence/followup-validation.json](evidence/followup-validation.json) | Expanded 62-test validation and preserved original/follow-up artifact hashes |

## Recorded finite-task result: actor loses to same-bank DP

The task has 52 states and 124 legal state/action rows. Each row supplies 64 sampled transitions; all failed sensing outcomes consume time/resources. The learner has a resettable generative-model interface and known state/action support. Its tabular critic solves the proper-moment objective on the frozen empirical law; this is a plug-in model gradient, not an unbiased true-environment gradient or a neural-critic result.

True-model evaluation in [finite.json](evidence/finite.json) gives:

| Training seed | Trained actor | DP using the same sampled bank |
|---:|---:|---:|
| 1701 | 0.207491 | 0.252747 |
| 1702 | 0.183655 | 0.203521 |
| 1703 | 0.214359 | 0.251571 |
| 1704 | 0.216051 | 0.252747 |

The actor loses in **4/4 seeds**. Exact known-model DP gives 0.252747; the strongest tested fixed schedule gives 0.208740. Exact truth is validation instrumentation and is not supplied to actor fitting. Recorded CPU/wall values describe this small local computation, not a scaling or hardware-efficiency theorem.

## Critic values and internal gradients are separate obligations

For frozen continuation targets, `exp(v) - Y*v`, with `Y=exp(-eta*X)`, is a proper loss for `v=log E[Y|s,a]`. Regression on `log(Y)` targets a different quantity. The critic study compares fixed degree-four polynomial models on independent held-out internal states; the exact-moment model has stronger oracle information.

In [critic.json](evidence/critic.json), at internal noise `epsilon=0`, the sampled proper-moment fit has value RMSE **0.004003** and internal-gradient RMSE **0.011453**. The log-sample fit has **0.024318** and **0.066315** respectively. These are bounded-model diagnostics, not a universal learning guarantee.

Direct differentiation remains defined at zero noise. Injecting absolute `Z` error `1e-5` and dividing by positive `epsilon` produces gradient errors `1e-5`, `0.001`, `0.1`, and `10` as epsilon decreases from `1` to `1e-6`; the inversion is undefined at zero. Direct fitting still has approximation error, which is checked against actual interventions.

A separate corrupted critic has uniform value error at most `0.001` but gradient error `2` at a tested prefix. Its proposed move predicts a gain while the independent exact intervention loses approximately `0.0001034`; it returns no-update. Small value error therefore does not certify useful internal gradients. This is a constructed diagnostic, not an observed neural failure rate.

## Paid reset experiment: MSE improvements do not close the decision gate

Three bounded tasks, three fitting seeds and `poly1`/`poly3`/`tanh16` give 27 fitted cells. Each uses 128 fitting pairs and 128 independent allocation-pilot pairs. Frozen allocations are saved before fresh paired outcomes and independent reset banks are drawn. The scalar finite-bank coefficient retains its shrinkage:

\[
\widehat d=\overline{D-\beta H}+\beta\overline{H'},\qquad
\beta=\frac{\widehat{\operatorname{Cov}}(D,H)}{\widehat{\operatorname{Var}}(H)}\frac{n}{m+n}.
\]

Each fitted cell executes 64 complete estimators for each of the paid-reset, after-setup direct and known-reset-mean routes. Nine full-budget direct cells add another 64 each: **5,760 complete estimators**, rather than only plug-in variance calculations. [paid.json](evidence/paid.json) retains every estimate, fit, count and timing; [paid.lock.json](evidence/paid.lock.json) preserves the pre-evaluation fits/allocations.

Observed MSE ratios below divide the sum across three fitted seeds by the corresponding full-budget direct MSE sum:

| Task | poly1 / direct | poly3 / direct | tanh16 / direct |
|---|---:|---:|---:|
| Smooth positive candidate | 0.3255 | 0.3143 | 0.4534 |
| Noisy harmful candidate | 1.2940 | 1.4087 | 1.3301 |
| Symmetric null | 0.0780 | 0.1075 | 0.1719 |

These are descriptive repeated-sampling MSEs, not significance claims or learned-policy gains. **All 27 fitted-route first-repetition certificates return no-update.** Full-budget direct certifies the three positive cells and rejects the six harmful/null cells. Support-only Hoeffding bounds on the control residual can widen even when its variance falls.

Known-law controls remain available: polynomial reset means use exact finite-grid basis moments; the tanh mean enumerates all 4,097 reset atoms and is charged for those predictions. Three `tanh16` fits on the noisy task reach the fixed iteration limit; their parameters, status/messages and actual fitting work remain in the record. No failed fit or adverse seed is deleted.

### Fresh empirical-Bernstein follow-up

After observing the Hoeffding failure, a separately labeled exploratory follow-up freezes the existing fits/allocations, draws fresh stream phases 30/31, and compares both bounds on the same new data. It uses 36 cells and a registered family of 72 comparisons; 23,605 fresh pairs and 199,123 resets are physically drawn once. No predictor is refitted and no allocation is chosen using these outcomes.

Both Hoeffding and empirical Bernstein adopt **3/36 cells, all full-budget direct positive candidates**; neither admits an additional fitted-control cell. This is one fresh draw per frozen cell, not a repeated power study. It does not overwrite the original experiment or establish that variance-aware bounds are generally ineffective. [variance_followup.json](evidence/variance_followup.json) retains the raw draws and both decisions; the command below reproduces that separate record from the retained lock.

## What the certificates actually cover

- `PaidAudit` / `VarianceAudit` compare a **fixed conditional continuation target**. They assume bounded justified supports, IID paired observations, an independent reset bank with the same conditional predictor law, and coefficients fitted separately. Distinct IDs alone do not prove those facts. Pairing does not manufacture counterfactual outcomes.
- Confidence spending covers all sample-prefix sizes, including adaptive sample counts, within the registered comparison family. It cannot justify target/predictor refitting on the audit data or arbitrary reuse across new families.
- `policy_gate.py` requires simultaneous intervals for the complete **baseline policy's Q values** on the same recursive model; the initial-value alternative requires complete recursive policy-value coverage. Local improvement over STOP alone does not establish whole-policy improvement.
- The finite study supplies oracle intervals to illustrate these gates. Its conservative local gate rejects delayed improvements that the full initial-value oracle can recognize. It supplies no learned statistical coverage for a real agent.
- A rejected update retains its paid verification cost. No-update protects against the uncertified policy change; it does not recover sunk fees or guarantee zero economic loss against never auditing.

## Cost and integrability boundaries

The paid studies use an explicitly declared **counter tariff**, separate from measured CPU/wall. Each estimator is charged its standalone fitting/pilot counters, although fitting is physically performed once per frozen cell. Allocation search, statistics, source hashing, audit construction and output have measured runtime but no tariff. Those exclusions prevent a claim of complete economic cost or end-to-end hardware advantage. The finite-task gate's `0.01` fee is a declared toy utility charge, not a hardware-calibrated price. Arithmetic is ordinary floating point, not a formally validated stochastic implementation.

The predecessor R32 objective is expected priced cost. Conditional on the penultimate state, its U3/M8 models have a non-degenerate Gaussian final internal coordinate and a positive quartic terminal loss. Consequently `E[exp(eta*C)]` is infinite for every `eta>0`: a positive quartic exponent dominates the Gaussian density's negative quadratic. Finite polynomial moments and finite observed Monte Carlo samples cannot establish exponential integrability. This does not invalidate R32's original expected-cost objective; it blocks silently exponentiating it into this one. See [R32_TAIL_OBSTRUCTION.md](R32_TAIL_OBSTRUCTION.md). The present bounded tasks are separately defined objectives.

## Reproduce

Run from the repository root. The recorded environment used Python 3.12.14, NumPy 2.3.5 and SciPy 1.17.0. NumPy and SciPy are the additional dependencies; no Torch or remote model call is required. Choose a new output directory for each reproduction because the runner refuses to overwrite evidence.

```bash
python -m pip install numpy==2.3.5 scipy==1.17.0
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1
NDU_JAC_MODULE=experiments.multimodal_output_portfolio.joint_hepta_20261029.v3.ndu_jac
NDU_JAC_PATH=experiments/multimodal_output_portfolio/joint_hepta_20261029/v3/ndu_jac
python -m "$NDU_JAC_MODULE.reproduce" --output /tmp/ndu-jac-replay
python -m "$NDU_JAC_MODULE.variance_followup" \
  --lock "$NDU_JAC_PATH/evidence/paid.lock.json" \
  --output /tmp/ndu-jac-variance-followup.json
```

`reproduce` runs package tests plus the inherited exact-decision suite in ordinary and `python -O` modes, then executes the finite, critic and paid studies. It records command exits and source/artifact SHA-256 values. The original retained logs report **59 passed tests in each mode**. The separate [follow-up receipt](evidence/followup-validation.json) records **62/62 in each mode: 48 package tests plus 14 inherited tests**, and preserves the original evidence. Repeating the modes is not an independent scientific replication; each receipt applies to its recorded source snapshot. A new run produces its own receipt. Timing fields and hashes of timing-bearing records need not match across machines.

The follow-up command uses the original saved fits; replacing `--lock` with a new run's `paid.lock.json` explicitly starts from that new fit/measurement record. Check `parent_lock_sha256` in the follow-up protocol when comparing runs. These local suites do not constitute Rust workspace CI, independent deployment acceptance or a production gate.

## Immutable provenance and unresolved work

- Implementation base recorded by the receipt: [hepta-private-ci `bde82cc66099ccdfe198d2c02f4536b70c91731c`](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/bde82cc66099ccdfe198d2c02f4536b70c91731c/experiments/multimodal_output_portfolio/joint_hepta_20261029/v3).
- External-goal/internal-preference boundary: [NDU_FBSDE_SPEC at `732e934ba496d90fbe042b8d41d479ef901643e5`](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/732e934ba496d90fbe042b8d41d479ef901643e5/docs/learning/NDU_FBSDE_SPEC.md).
- Retained R32 expected-cost training/simulator: [ICLR-2027 `8b796bcea7038f22b20592df2d79a792a396093a`](https://github.com/TrillionniumFoundation/ICLR-2027/tree/8b796bcea7038f22b20592df2d79a792a396093a/05_NDU_RL_NeurIPS/revision_20261104_r32).
- Paid-reset manuscript: [ICLR-2027 `d3485e0c22789aad360e42b42167e8530494bf4a`](https://github.com/TrillionniumFoundation/ICLR-2027/tree/d3485e0c22789aad360e42b42167e8530494bf4a/05_NDU_RL_NeurIPS/revision_20261104_r32_paid_reset); executable predecessor allocation source is separately pinned at [`762e4b629b7e32997f1f7b916096a3b1237c2b5b`](https://github.com/TrillionniumFoundation/ICLR-2027/tree/762e4b629b7e32997f1f7b916096a3b1237c2b5b/journal_revisions/2026-11-04/ten_line_closure/ndu).

Still open: informative learned coverage under distribution shift; joint recursive value/gradient/moment error control at useful scale; real validation-induced clock/state changes; paid exploration; stable long-horizon risk weights; valid unbounded-tail domains; and a demonstrated total-cost or policy-quality advantage over strong ordinary methods. Correct finite-model identities and lower estimator MSE do not close those scientific obligations.
