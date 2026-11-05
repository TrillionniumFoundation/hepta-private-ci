# JAC finite-bank optimization gap: diagnosis and repair

2026-11-05. This follow-up leaves the original result and its artifacts intact. It uses the exact source published at [`cea77b5`](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/cea77b5e6ff25b05bad7e9fbf88578fd84f198e9/experiments/multimodal_output_portfolio/joint_hepta_20261029/v3/ndu_jac). The target remains the bounded recursive objective with action randomization **outside** each conditional certainty equivalent. These are empirical-model optimization diagnostics. They do not establish a new model-free algorithm, sample efficiency, independent-task generalization or positive lifecycle economics.

## Result that changes the next experiment

The four original actor and same-bank-DP values reproduce with **zero absolute discrepancy**. The original actor's poor result has a substantial deployment-randomization component. Simply selecting its maximum-probability action at each state raises mean true utility from **0.205389 to 0.252159** on the original four banks, and from **0.207141 to 0.252674** on 16 additional banks. The known-law optimum is **0.252747**. This deterministic actor extraction must be retained as a strong baseline.

All-state mirror improvement shrinks the empirical optimization gap by over two orders of magnitude using the same 120 exact empirical policy evaluations. Greedy empirical policy iteration closes the empirical gap to floating-point precision in 2–3 updates. However, exact fitting of the small sampled law can worsen true performance: on 4 of the 16 additional banks, empirical policy iteration/DP has lower true utility than the original stochastic actor. The strong rounded actor does better on average than either. Closing an optimizer gap therefore does not close the identification or generalization problem.

All numbers below are calculated from [gap_study.json](evidence/gap_study.json). The local [protocol](evidence/gap_study.protocol.json) was written before candidate execution; it discloses that source review and a single original-seed occupancy diagnostic preceded freezing. This is not a public preregistration.

## Frozen comparison

The task, external scores, action laws, eta=2, rho=0.17 and 64 draws per state/action are unchanged. Every method receives the same 7,936 transitions per bank and known state/action support. The original seeds are 1701–1704; the additional independently sampled banks use 2701–2716. They are **new banks on the same task**, not independent task instances. No new training samples are acquired by an optimizer.

The original 120-step learning rate 2 logit-gradient method is reproduced without modification. An all-state mirror method uses the same initialization, 120 updates and step size 2. Greedy empirical policy iteration uses the same initial stochastic policy, at most 16 updates, and a root residual-bound tolerance of `1e-10`. Probability argmax extraction is registered for both actors. DP is the exact optimizer of each empirical bank. Truth is supplied only to final validation; none of these fits, hyperparameters or stopping rules consults true transition probabilities.

| Method | Original banks: mean empirical gap | Original banks: mean true utility | Additional banks: mean empirical gap | Additional banks: mean true utility |
|---|---:|---:|---:|---:|
| Original stochastic JAC actor | 0.04891731 | 0.20538891 | 0.04391504 | 0.20714106 |
| Original actor, probability argmax | 0.01047765 | 0.25215908 | 0.00498347 | 0.25267370 |
| All-state mirror actor | 0.00001441 | 0.24010418 | 0.00016639 | 0.23909829 |
| Mirror actor, probability argmax | numerical zero | 0.24014668 | 0.00011897 | 0.23893775 |
| Empirical policy iteration | numerical zero | 0.24014668 | numerical zero | 0.23416276 |
| Same-bank DP | numerical zero | 0.24014668 | numerical zero | 0.23416276 |

The additional-bank mirror worst empirical gap is `0.00114145`; its deterministic extraction has a worse maximum empirical gap, `0.00190347`, despite the lower mean. The maximum absolute empirical-PI-versus-DP root discrepancy over all banks is `5.56e-17`. No confidence interval or distribution-wide dominance claim is attached to these descriptive results.

## Why the existing gradient is slow

For independently parameterized softmax rows, the implemented exact empirical derivative is

\[
\partial_{z(s,a)}\widehat V^\pi(s_0)
  =d^\pi_{\rm risk}(s)\,\pi(a\mid s)
   [\widehat Q^\pi(s,a)-\widehat V^\pi(s)].
\]

Both visitation and action probability attenuate updates. After 120 steps at seed 1701, the original actor has minimum nonroot tilted occupancy `1.14e-6`, median about `3.27e-4`, root Bellman residual about `0.00697`, and maximum state residual about `0.48748`. The root already selects precise inspection with probability `0.96643`, while many downstream rows remain weakly optimized. Across the four original banks the median of nonroot occupancy medians is `0.00028851`; across additional banks it is `0.00032171`. These diagnostics explain an optimization mechanism; they do not prove it is the sole cause of every loss.

The reference objective has no entropy bonus. With the action mixture outside CE, its finite-model Bellman optimum can be deterministic. Probability argmax extraction removes residual randomization. Its observed reduction of the mean empirical gap is 78.6% on original banks and 88.7% on additional banks. **Probability argmax has no general improvement guarantee:** a stochastic policy that assigns 0.51 to a bad terminal action becomes worse after rounding. This counterexample is executable in the tests.

## Two explicit model-based repairs

### All-state mirror improvement

At each iteration evaluate the entire frozen empirical law and set

\[
\pi^+(a\mid s)\propto\pi(a\mid s)\exp(\alpha\widehat Q^\pi(s,a)),\qquad\alpha=2.
\]

The code uses centered advantages in the logit update, which gives the same policy. In a positively visited tabular row, the root-objective gradient has the form `d F Q`, with categorical Fisher matrix F. Removing visitation/Fisher attenuation motivates this update. The implementation also updates unreachable rows using reset-bank model access. Consequently it is **all-state model-based policy improvement**; it is not an unbiased on-policy natural-gradient estimator.

For each state the update maximizes `p·Q - KL(p||pi)/alpha`. Comparing its value with p=pi gives `pi+·Q >= pi·Q`. The CE operator is monotone in continuation values. Backward induction on the finite acyclic state graph then proves `V^(pi+) >= V^pi` at every state of the **empirical model**. This proof requires a fixed target and fixed empirical law and says nothing about true-model monotonicity.

### Greedy policy iteration and a stopping certificate

Given an evaluated empirical policy, define

\[
r(s)=\max_a\widehat Q^\pi(s,a)-\widehat V^\pi(s),\qquad
B(s)=r(s)+\max_{a,o:s'\ne\varnothing}e^{-\rho\Delta t_o}B(s'),
\]

where the maximum over an empty successor set is zero. Compute B backward. Then

\[
0\le\widehat V^*(s)-\widehat V^\pi(s)\le B(s).
\]

**Proof.** Assume the inequality at successors and write `Delta(s')=V*(s')-Vpi(s')`. A branch continuation changes by `exp(-rho*dt)*Delta(s')`, a nonnegative quantity at most the largest corresponding successor bound. Monotonicity and translation equivariance of CE place each action-value difference between zero and that maximum. Add the one-step residual and maximize over actions. Terminal states give the induction base. This proof uses only bounded finite outcomes, acyclicity, eta>0 and rho>=0, already required by the reference model.

The algorithm greedifies every empirical Q row and repeats until B(root)<=`1e-10`. It does not call DP during fitting or certification. In exact arithmetic, simultaneous greedy updates reach an optimum within the longest remaining decision depth: terminal rows become optimal after one update, and an induction advances one depth each time. The observed original banks need 2 updates; the additional banks need 2 or 3. Float roundoff leaves reported B(root)<=`7.53e-17`. These bounds certify the sampled model only.

## Separate optimization error from sampling error

Let pi be an actor, pihat* an empirical optimum, and define model optimism `b(pi)=Vhat(pi)-Vtrue(pi)`. The identity

\[
V_{\rm true}(\widehat\pi^*)-V_{\rm true}(\pi)
 = [\widehat V(\widehat\pi^*)-\widehat V(\pi)]
   -b(\widehat\pi^*)+b(\pi)
\]

is saved for every bank; its maximum arithmetic discrepancy is below `6e-17`. In seed 1702 the optimizer gap is `0.07057169`, DP optimism `0.03724112` and actor optimism `-0.01346466`, yielding a true DP-minus-actor gap of only `0.01986592`. Yet rounding that actor achieves the true optimum `0.25274722`, compared with DP's `0.20352134`.

Additional seed 2715 is a stronger caution: PI/DP reaches empirical optimality but true value `0.17634740`, below the original actor's `0.20079955`, while its rounded actor has `0.25274722`. This is consistent with finite-bank model selection error. It does not establish that early stopping or rounding dominates in other tasks. A separate test constructs a sampled law on which empirical improvement strictly harms the true utility.

## Actual computation and cost boundary

Per-bank fitting costs averaged over all 20 banks on this execution host:

| Method | Mean wall seconds | Mean CPU seconds | Conditional action-value backups |
|---|---:|---:|---:|
| Original actor | 0.161497 | 0.161481 | 14,880 |
| All-state mirror actor | 0.151411 | 0.151391 | 14,880 |
| Empirical policy iteration | 0.003935 | 0.003937 | 396.8 mean; 372–496 |
| Same-bank DP | 0.000941 | 0.000941 | 124 |

PI is much cheaper than the original loop in this implementation but remains roughly 4.2 times the DP wall time. DP is the computational control for this enumerated task. Each bank's acquisition work and timing, all fitting traces, all six full policies, sample counts and content hashes are retained. Validation work is separately timed. The runner measured total wall `6.73263 s` and CPU `6.73157 s` before serialization. Argmax extraction timing is not resolved separately; it requires the parent actor's full fitting cost. JSON serialization, source hashing and test execution are outside those total-run timers. There is no currency conversion, deployment amortization or positive net-benefit claim.

## Reproduce and verify

From the repository root:

```bash
python -m unittest experiments.multimodal_output_portfolio.joint_hepta_20261029.v3.ndu_jac.test_gap_study -v
python -m experiments.multimodal_output_portfolio.joint_hepta_20261029.v3.ndu_jac.gap_study \
  --protocol experiments/multimodal_output_portfolio/joint_hepta_20261029/v3/ndu_jac/evidence/gap_study.protocol.json \
  --output /tmp/ndu-jac-gap-new.json
```

The runner refuses to overwrite evidence. Five behavioral tests cover the residual bound against independently computed DP, empirical monotonicity and finite-step convergence, all-state updates at zero root visitation, adverse true-model transfer, and a rounding counterexample. They pass under ordinary Python and `python -O`; neither mode is an independent scientific replication. Existing source and historical evidence were not changed.

## Consequence for the research gate

The narrow G1 optimization-diagnosis milestone is materially advanced: the inherited negative result is reproduced, its empirical gap is decomposed, a strong deterministic baseline is exposed, and empirical planning parity is achieved with a certificate. The new research target is **decision-relevant identification under paid finite data and actual elapsed time**. Its strong control set must include original-actor argmax, same-information DP, all-state mirror/PI, and no-acquisition/stop. Empirical optimizer convergence alone is insufficient for G2 or any expansion gate.
