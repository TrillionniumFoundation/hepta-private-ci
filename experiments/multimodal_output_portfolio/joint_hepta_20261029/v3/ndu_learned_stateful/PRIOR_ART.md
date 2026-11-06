# Nearest-work check for the remaining NDU claims

Scope frozen for this round at 2026-11-06 02:49 UTC (2026-11-05 in New York).
This check precedes the new learned-stateful numerical results. It is a scoped
primary-source comparison, not an exhaustive novelty certificate or an external
review. The starting evidence is the stacked research commit
`5c0093cb62ca4b5007df733f470fc8922ffdafc8`.

## Direct neighbors

| Primary source and inspected location | Established ingredient | Consequence for this research |
| --- | --- | --- |
| [Cheng and Huan, *Optimal Stopping for Sequential Bayesian Experimental Design*, v3, 13 June 2026](https://arxiv.org/html/2509.21734v3), Sections 2–4 and Appendix E | Joint experiment selection and stopping; belief plus physical state; continuation-value learning, policy gradients and a stopping curriculum. | Adding STOP, nonmyopic design, physical state or a learned continuation value is not by itself a new RL contribution. The manuscript explicitly separates offline training from online execution costs. |
| [Lee et al., ICML 2023](https://proceedings.mlr.press/v202/lee23a/lee23a.pdf), Lemma E.1 and Appendix F.1 | Model-error control for arbitrary history policies through transition/observation total variation; learning with latent-state information revealed during training. | A finite transcript simulation lemma is a standard tool. Any labeled calibration access must be stated explicitly and cannot be described as ordinary unlabeled deployment data. |
| [Demirci, Kara and Yüksel, arXiv:2508.10658v2](https://arxiv.org/html/2508.10658v2), Sections 3–5 and 8 | Explicit filter/value/policy robustness to transition, observation and initialization errors under stated regularity. | An approximate-kernel performance bound alone does not establish novelty. Our finite bounded-horizon constants and assumptions need their own proof, not a stronger claim than this literature. |
| [Nitinawarat and Veeravalli, controlled Markovian sensing](https://arxiv.org/abs/1310.1844), sequential formulation | Controlled observation memory, nonuniform control costs and asymptotic identification guarantees. | A state-dependent information rate and paid sensing already have direct precedents. A reset-query lower bound must be replaced by the conditional transcript identity before treating state changes. |
| [Kanarios, Zhang and Ying, RLC 2024](https://rlj.org/papers/kanarios2024cost), paper summary | Expected-cost best-arm identification, an information lower bound and asymptotically matching CTAS. | Unequal acquisition prices or a cost-normalized information allocation are established comparison targets. |
| [Harding and Kandasamy, NeurIPS 2025](https://papers.nips.cc/paper_files/paper/2025/hash/b0dfe8236981ba84b4d98a7ed0426f0b-Abstract-Conference.html), formal objective and result summary | Sampling cost combined with terminal recommendation loss; DBCARE with risk guarantees. | A fixed external decision-loss-plus-cost objective is necessary for our experiment, but does not itself distinguish a new method. |

The Cheng–Huan formulation permits history dependence and physical variables.
Absence of a dedicated wall-clock deadline experiment in the inspected paper is
not a proof that its general decision formulation cannot encode a clock.
Likewise, a finite paid-calibration model is a restricted access model; its
positive result cannot remove general POMDP identifiability obstacles.

## Claims allowed before the new results

1. State the exact external payoff, information interface, legal calibration
   access and cost of obtaining labels, state resets and complete observations.
2. Prove a finite-horizon transfer bound using the joint observed kernel:
   outcome, duration, failure, censoring and next observable state.
3. Compare plug-in policies with same-data exact planning and simple stopping
   or myopic rules. Label any known-law oracle as diagnostic additional knowledge.
4. Report whether the resulting bound is nonvacuous after calibration costs,
   planning costs and a declared deployment amortization volume.
5. Qualify actual-clock execution separately from frozen-model task performance.

A plug-in DP implementation remains classical model-based planning. Matching it
does not support an exclusive neural advantage. Positive finite expected utility
and a valid simulation lemma do not supply a cost-optimal identification theorem.
An expected resource bound does not supply a pathwise deadline guarantee.

## What would change the decision

A result must identify its precise incremental theorem or algorithm, the closest
applicable comparator, and a setting where the increment changes a legal action,
an attainable error/cost bound, or independently confirmed full-cost performance.
Potentially useful findings also include a nonidentifiability construction, an
unavoidably vacuous certificate at affordable sample sizes, or dominance by a
cheap baseline. Those are reportable negative conclusions.

Current disposition: **a new general NDU RL framework is not established**.
The present work is a bounded reference/engineering investigation. Scaling stays
at HOLD until the previously frozen scientific gates pass; citation updates or
additional internal tests cannot replace external proof review or real-model
confirmation.
