# Independent internal review: clock semantics

**Disposition: the registered finite semantic result passes.** The existing 81 cells, two fixed-local-risk root-action flips, and agreement of transported risk with the matched terminal-payoff objective are reproduced without importing the new `semantics.py` evaluators or graph builders. One assumption in the general Bellman proof should be made explicit before broader use. This is internal review by `/root/frozen_llm`, separate from the author of the reviewed unit, not external mathematical review.

The review leaves every target source and result unchanged. It performs no LLM inference, real task-tool execution, random sampling or enlargement of the primary grid. `clock_semantics_review.py` and `clock_semantics_review.json` preserve the reconstruction, source hashes and **266 passing review checks**. These checks are separate from the original 518 program checks; neither count denotes independent scientific samples.

## 1. Retained JAC code reproduces the counterexample

I imported the existing `ndu_jac/core.py` (SHA-256 `a04d3a1cc038448e9a2f7fc5f5336c60a80f06171833517f045e90cf7a1b6578`) and manually constructed both graphs using its original `Outcome`, `evaluate` and `optimal_policy` interfaces. No new semantic-module function was imported or called.

Both graphs pay the `.01` cost at launch. A one-tick continuation reaches a revealed terminal state, whose STOP pays 0 or 1 immediately there. This placement matters: putting reward X directly on a terminal initiating transition with duration 1 would cause the retained core to treat X as immediate, producing a different physical contract.

| Retained-core computation, eta=2 and rho=log(2) | Probe Q | Optimal root value | Root action |
| --- | ---: | ---: | --- |
| Coarse completing transition | 0.17994274652086123 | 0.17994274652086123 | probe |
| One deterministic wait, then forced zero-time resolution | 0.13155479237924317 | 0.16 | STOP |

Explicit forced-probe policy evaluation agrees with the corresponding optimal-Q entries. The small differences from the printed decimal targets are ordinary binary-float rounding.

The closed forms are

\[
q_{\rm coarse}=-.01-\frac1\eta\log(1-p+p e^{-\eta\gamma^d}),
\qquad
q_{\rm fixed,refined}=-.01-\frac{\gamma^d}{\eta}\log(1-p+p e^{-\eta}).
\]

Using these formulas at higher Decimal precision, I independently checked every recorded value and root choice on the **same 81 registered cells**. The two flips are exactly `(eta=2, gamma=.5, p=.5, duration=1)` and `(eta=2, gamma=.8, p=.5, duration=3)`. The transported formula equals the direct time-zero CE. The separate already-recorded random-duration example also matches its four-point direct terminal moment.

The identity `C_eta(gamma X)=gamma C_(eta gamma)(X)` and the necessity argument using a nondegenerate bounded small lottery are valid. The necessity is for preservation of all bounded lotteries, not inference of a risk parameter from a single degenerate payoff.

## 2. “Same physical observable process” is satisfied here, not inferred from terminal marginals alone

An administrative refinement must preserve more than the law of final payoff and completion time when policies may adapt. It must preserve the available observations and their times, admissible choices/cancellation opportunities, and timed cash flows, after erasing the inserted forced node.

For these actual handwritten graphs, the stronger condition holds. I independently reconstruct both root choices:

- STOP pays `.16` at time 0 and terminates in either representation.
- Probe pays `-.01` at time 0. At time 1, X is observed and paid, with probability one half for each value. The inserted `resolve` node is deterministic to reach, offers one forced action, consumes zero further time and has no fee or extra signal.

The complete timed cash-flow/observation transcripts agree, not merely their discounted final sums. As the only free choice is the same root action, this also gives a correspondence for arbitrary root randomizations. The graph-refinement example is therefore sound. The study check named `physical_transcripts_identical_after_forced_node_removal` itself computes a terminal payoff/time law; it should not be advertised as a general-purpose filtration-equivalence verifier. The stronger conclusion here relies on the explicit graph contract and the additional reconstruction.

## 3. Required clarification in the general Bellman induction

Section 4 factors an exponential moment using a child continuation CE conditioned on `h'`. A sufficient assumption is that the transition's elapsed duration and realized interim cash flows are recorded in `h'`, so `r,d` are child-history measurable. More generally, it suffices that the continuation exponential moment conditioned on `(h',r,d)` equals the one conditioned on `h'`.

“Complete observable history” alone does not cover a hidden prior cash flow that remains correlated with future payoff. As an explicit boundary witness, let `X~Bernoulli(1/2)` be an unobserved first payoff and let the later payoff be `Y=X`, with zero delay. At eta=2,

- the true `CE(X+Y)` is approximately **.337498626321**;
- replacing continuation by its marginal CE and factoring gives `CE(X)+CE(Y)` approximately **.566219169517**.

This is not a failure of the registered graphs: their relevant costs, times, and revealed payments meet the needed condition. It is a missing explicit restriction if the theorem is read as applying to arbitrary partially observed rewards.

Suggested insertion:

> For this induction, the realized transition cash flows and elapsed duration are included in the child history, or the child history is conditionally sufficient for the continuation exponential moment given those quantities. Hidden past cash flows correlated with future payoff are outside this reduction and require an appropriate augmented information state.

No new algorithm or general hidden-state claim is needed to address this point.

## 4. Random action CE and enumeration scope

The retained core with two deterministic actions paying 0 and 1, chosen equally, actually returns **.5**, because action randomization is outside CE. Direct trajectory CE at eta=2 returns **.2831095847584864**. The distinction and the warning about stochastic policies/gradients are correct. A deterministic optimizer for unconstrained exponential utility does not make the two randomized-policy objectives equivalent, and it does not remove randomization from the earlier constrained/minimax identification problem.

`backward` indexes continuation choices by `(state, elapsed)`. `exhaustive` uses `policy[state]`. Its documented unique-clock-per-state restriction is therefore substantive. All registered pair graphs have root time 0 and other nodes at the single declared probe duration; the random-duration example separates the fast and slow terminal states, so it also meets the restriction.

A separate analytic scope witness illustrates the limitation without adding a primary grid cell: reach the same named node equally at times 0 and 1, with eta=2, gamma=.5, a safe payoff `.35`, or a 0/1 lottery. The best state-only policy has CE **.254882512571**; the clock-conditioned policy choosing safe early and the lottery late has **.263593952562**. Thus the small enumerator is not a general clock/history planner. `validate` does not itself enforce unique clocks. This does not invalidate the frozen 81 cells, but reuse should either reject violating inputs or expand states by clock before enumeration.

A second small implementation coupling is also limited to reuse: `study.py` calls `pair(p,duration)` without passing the protocol's safe reward and launch-charge fields. Their frozen values exactly equal the builder defaults, so the present evidence is correct. A future protocol change must explicitly pass those values or enforce their equality rather than silently keeping defaults.

## 5. Final assessment

The unchanged evidence supports a **semantic guard**: fixed local recursive eta depends on the declared event representation; clock-transported risk matches the classical trajectory objective under the stated fully observed/sufficient-history contract; and matching the objective removes the apparent algorithmic difference. Positive headroom above STOP is not advantage above the correctly matched planner.

No independent-task gain, new RL contribution, learned-kernel result, monetary net benefit, or formal outward-rounded numerical proof follows. The current no-new-algorithm disposition is appropriate. The only required theoretical wording change is the conditional-sufficiency restriction above; the clock-state and protocol-default observations define implementation reuse boundaries, not new failures of the registered grid.

The review script records the exact absolute paths used for this historical run. It reads those target files and invokes only the retained finite mathematical evaluator; the JSON output is created exclusively and will not overwrite the original review. A relocated replay requires explicit path/output adaptation in a separately identified copy of the review script, not edits to the frozen study or replacement of this receipt.
