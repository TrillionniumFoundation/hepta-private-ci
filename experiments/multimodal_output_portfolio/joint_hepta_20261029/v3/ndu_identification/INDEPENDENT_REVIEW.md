# Independent review of the finite identification package

Date: 2026-11-05. Scope: `ndu_identification/model.py`, `study.py`, `README.md`, and the subsequent binary SPRT numerical bridge. This is a second mathematical implementation in the same working session, not external institutional review or a fresh independent dataset. The exact reviewed source hashes appear in `evidence/independent_model_review.json`.

## Findings that affect the reported 18-cell model

No discrepancy was found in the declared bounded-model values or the specified timing, censoring, and fee mechanisms. An independent solver uses a manually transcribed joint probability table, unnormalized masses for the two hypotheses, and discounting at absolute payment time. It does not call the package's kernel, censoring routine, posterior update, branch generator, conditional Bellman values, or planner recursion. All 18 registered task values agree with both the package DP and its hidden-state path enumeration to at most **1.1102230246251565e-16**.

The independently implemented objective is

\[
W(m_0,m_1,t,k)=\max\left\{e^{-\rho t}\max(m_0,m_1),\;
\max_a\left[-(m_0+m_1)ce^{-\rho t}
+\sum_e W(m_0K_a^0(e),m_1K_a^1(e),t+d_e,k-1)\right]\right\}.
\]

This differs in representation from the package's normalized-belief, relative-time recursion. Both calculate the same unconditional expected utility.

### Joint law

The manually checked joint sensor table has identical label marginals and identical duration marginals under the two hypotheses. Its full joint KL is `0.7 log(8) = 1.4556090791758851`; the posterior examples `1/9` and `8/9` are correct. The fast and slow success/failure probabilities sum to one, and no failure mass is lost.

### Censoring filtration

For each selected probe/cap action, all uncensored outcomes whose duration exceeds the cap map to one `('timeout', cap)` event. Their hypothesis likelihoods are summed before the Bayes update. Neither the hidden label nor the unobserved completion duration enters the policy. Completion at the cap is observed, as stated. Conditional likelihoods include the query and cap; these controls are observable and chosen from the history, so they need not be separately multiplied into the posterior likelihood.

The current duration marginals do not distinguish the hypotheses, so ongoing silence alone adds no hypothesis information in these kernels. The label-duration pairing does. In more general timing models this simplification must be revisited.

### Timeout and deadline

Cancellation consumes only the realized cap and one launch fee, and control can resume if time and query allowance remain. Every smaller-horizon strategy can be embedded at a larger remaining horizon by choosing the same caps and stopping at the same times. Because the objective is discounted from the current time, not evaluated at an obligatory terminal deadline, this establishes the stated value monotonicity. The original pilot without cap controls did not have that policy-class nesting; retaining it separately is appropriate.

### Fee timing

The planner uses `−fee + E[exp(−rho*elapsed)*child]`. The path enumerator discounts each admitted fee at its actual start time. These are equivalent recursive and trajectory forms. A failed or timed-out query retains its fee. The discount prices delayed receipt; no second arbitrary latency tariff is present. Actual planner computation is separately measured metadata and is not represented as model time or a net hardware gain.

### Ablations

`label_only` is a deliberately degraded posterior-updating/planning procedure; it is not an optimal method under all information available through the clock. `fixed_step` forecasts each tool as completing in one model time unit, which also changes its predicted censoring, while actual execution uses the true capped law. Both are feasible policies evaluated under the same real model law, but they are mechanism ablations rather than evidence that a new learning method beats a strong generic planner. The README states the relevant nonclaims.

## Binary SPRT bridge

The new bridge matches the assumptions in `IDENTIFICATION_THEOREM.md`: known IID symmetric Bernoulli laws with `p>1/2`, resettable observations, fixed positive fee and deterministic duration, no free hypothesis information, and two-sided likelihood stopping at `log(1/delta)`. The rational threshold condition `((1-p)/p)^m <= delta` implements that threshold without float boundary ambiguity. Closed-form gambler's ruin error and expected query count agree with an independent rational absorbing-chain solve.

Deadline-forced decision results are distinct from the unlimited-time guarantee. The exact full-cap majority risk is a stronger necessary feasibility check than the KL relaxation in this symmetric one-sensor model. In particular, with `p=.7`, `delta=.05`, cap 8 passes the KL information inequality but has minimum fixed-cap error about `.126036`, so the KL test is correctly treated as necessary rather than sufficient. A stopped strategy using at most eight observations cannot beat the unrestricted eight-observation Bayes rule; symmetry converts that Bayes obstruction to a uniform-correctness obstruction.

The reported `.05` unlimited-time row agrees with the theory reference: boundary 4, error `.0326349718`, expected queries `9.3473005641`, lower bound `7.8189595570`, upper bound `11.3390765916`, ratio `1.1954660330`. This does not establish a near-lower-bound property of the separate 18-cell Bayesian utility controller.

## Small non-result-changing review comments sent to the implementing agent

At the time of review, the public `deadline_walk` helper accepted `p<.5`, while its `optimal_full_cap_error` field used an unflipped majority rule. For example `p=.3, cap=1` would give `.7`, although the optimal known-law decision error is `.3`. The registered `p=.7` experiment is unaffected. The agent was asked either to restrict the helper to `p>.5` or implement the correct reversed rule. `exact_sprt` already enforces the former assumption.

The v2 protocol's older `deadline_rule` wording refers to the global remaining time, while its newer `timeout_cap` field correctly declares selectable caps. The implementation and README use the correct selected cap. Harmonizing the two protocol descriptions avoids ambiguity in a later reproduction.

## Review artifacts

- `independent_model_review.py`: separate absolute-time solver.
- `evidence/independent_model_review.json`: all 18 values, maximum error, joint KL and reviewed source hashes.

The published script uses a relative package import only to compare final outputs. Its separate calculation requires only the Python standard library. This internal review did not modify the reviewed model or study implementation.
