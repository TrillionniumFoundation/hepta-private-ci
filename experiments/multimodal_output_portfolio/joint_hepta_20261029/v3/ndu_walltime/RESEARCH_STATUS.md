# NDU research status — 2026-11-05

The active research question is decision-relevant paid intervention identification,
with information acquisition and stopping under an actual clock. Finite reference
work is executable and reviewed internally. **Frozen-LLM confirmation has not run;
the large-scale training gate is HOLD.** No result here establishes a new general
RL algorithm or independently confirmed lifecycle net benefit.

## Reviewable stages

| Stage | Immutable evidence / review | Current conclusion |
| --- | --- | --- |
| Objective and theory repair | [NDU correction PR](https://github.com/TrillionniumFoundation/NDU/pull/1), [corrected manuscript source](https://github.com/TrillionniumFoundation/NDU/blob/a10df444963b7c3db9458faefe9624cf7e3c5c0f/main.tex) | Nine checks pass; 80-page PDF rebuilt; external mathematical review remains open. |
| Same-data JAC gap | [PR 4876](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4876), [gap report](../ndu_jac/GAP_STUDY.md) | Empirical planning parity achieved; true-model error and computational cost remain distinct. |
| Identification/time/cost mechanism | [PR 4878](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4878), [finite reference](../ndu_identification/README.md) | All 18 cells, five policies and 520 terminal histories retained; known likelihoods and simulated durations. |
| Information-cost denominator | [PR 4879](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4879), [theorem](../ndu_identification/IDENTIFICATION_THEOREM.md), [SPRT](../ndu_identification/BINARY_SPRT.md) | Classical narrow reference and deadline counterexamples; no original lower-bound method claimed. |
| Actual-clock execution | [runtime contract](README.md), [qualification](evidence/qualification-final.json) | Fourteen real-subprocess tests pass; every executed worker is a scripted fixture. |
| Frozen-LLM net benefit | [readiness](LLM_READINESS.json), [confirmation design](CONFIRMATION_PROTOCOL.md) | NOT RUN; model, task bank, prices and immutable evaluation protocol must be supplied and frozen. |

These are draft review branches. None is a main-branch merge, external acceptance,
or permission to reuse a finite-model claim as a production guarantee.

## Findings that change the research direction

1. The inventory model's internal shortage penalty can reward lowering the
   penalty itself. Its increasing service-pressure selector claim is withdrawn.
   Action-conditioned nonaffinity also cannot rule out an augmented-state MDP
   with joint actions. Concavity, selector regularity and constrained first-order
   residual claims now state the additional assumptions they require.
2. The original stochastic JAC actor is a weak deployment baseline in the
   measured banks. Probability-argmax extraction raises mean true utility from
   .205389 to .252159 in the original four banks and from .207141 to .252674 in
   sixteen additional banks on the same task. There is no universal extraction
   guarantee. The known-law optimum is .252747.
3. All-state empirical policy iteration reaches the same-bank DP solution in
   two or three updates, within 5.56e-17. This is model-based planning. In four of
   the sixteen new banks its true utility is worse than the original stochastic
   actor's. It costs about 4.2 times DP wall time here. Better empirical
   optimization is not an independent net-benefit result.
4. Joint label-duration information, paid cancellation and option value matter
   in exact finite cases. Myopic VOI nevertheless ties DP in 16/18 cells. All
   high-fee and zero-deadline cases stop. The initial missing-cancellation model
   and its original sources remain available as superseded pilot evidence.
5. Symmetric known-law SPRT has expected resource/lower-bound ratio 1.195466 at
   target error .05 and 1.011968 at .0001. The whole confidence grid is retained;
   lattice effects are nonmonotone. A five-observation forced decision has error
   .16308. Passing an expected-information necessary condition does not imply a
   feasible pathwise deadline guarantee.
6. The measured-clock adapter retains fees after launch failure, timeout,
   cancellation and invalid output. Internal review found and fixed nonfinite
   JSON, deep nesting, invalid UTF-8 and child-process cleanup failures. It
   does not establish remote-provider cancellation or immutable model serving.

## Verification and evidence boundaries

[Integrated scoped verification](evidence/integrated-scoped-validation.json)
contains one ordinary Python unittest run with **96 unique tests**, no failures,
no skips and unchanged Python source hashes before/after the run: 62 original
JAC/decision-audit, five gap, nine identification, six SPRT and fourteen runtime.
The separate manuscript verification adds nine checks. This is not full-repo
Rust CI, external replication, or an LLM benchmark. Immutable commits bind the
independent solver itself as well as the numerical receipts.

The final stacked tree restores the complete finite README reviewed by the
independent solver. The finite-only stage omits its later-SPRT link; its review
receipt still records the complete reviewed README's hash. Executable sources
are identical. Simulation durations, host computation times and provider costs
are separate quantities throughout. Local protocol freezes after disclosed
pilots are not externally timestamped preregistrations.

## Remaining gates

- Prove or reject a useful extension with estimated likelihoods and paid
  state-changing interventions. The current reset-query KL theorem does not
  automatically cover that extension or a learned continuation kernel.
- Freeze an accessible model revision, independent task families and untouched
  confirmation split, complete cost accounting and the evaluation protocol.
  Execute the [paired confirmation design](CONFIRMATION_PROTOCOL.md), including
  simple stopping, myopic and strong same-information baselines.
- Require a positive lower confidence bound on net gain against every frozen
  required baseline, under the declared full cost budget, before scaling.
  Missing inputs, inconclusive intervals, a dominant cheap baseline, or net
  losses keep the gate at HOLD. Historical negative evidence is not reset.
