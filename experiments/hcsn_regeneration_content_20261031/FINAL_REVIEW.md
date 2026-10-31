# Final mathematical and evidence review

Review date: 2026-10-31 UTC. Reviewer: mathematical-audit agent.

**Disposition: no unresolved blocker within the reviewed mathematical, numerical,
and reproduction-document scope.** The conclusions describe the implemented
fixed-renewal gate and small, controlled CPU study. They do not establish a full
He–Xiong Call/Put neuron, end-to-end endogenous-boundary optimization, reliable
query binding, or an advantage over optimized large models.

## Final document identities

| File | Bytes | SHA256 |
|---|---:|---|
| `REPORT.md` | 18316 | `5b1bc54e7a8c6626abbeb58e46e02be61ff036e1bd0b351dca62bf352156acaa` |
| `REPRODUCE.md` | 7117 | `81b85c81e18edc7adf41518307901290e4287258bfb82c402db69ea2bd148e05` |

These identities refer to the final local documents after the owner-authorized
scope edits. Publication and remote readback of these documents remain the
owner's operation; this review is not a receipt for that subsequent operation.

## Review method and limits

This review read the documents, existing contracts, saved summaries, original
query-diagnostic prediction payloads, process receipts, and archive manifest.
It recomputed descriptive statistics from saved values and logits. It did not
rerun training, inference, formal numerical scans, policy execution, or archive
creation/restoration. No file under `evidence/` or any frozen source was changed.

Earlier independent reviews covered the renewal formula and implementation,
content-gate chain rule, causal policy transitions, actual-policy continuation
audit, and primary/cross-architecture training-input identities. Their original
records remain in the immutable evidence archive. The current review does not
claim to repeat every earlier verification from scratch.

## Closed documentation findings

| Finding | Final resolution |
|---|---|
| Renewal expression also covers an initial point on the boundary | The report now defines the zero-distance immediate event, negative-time extension, `Q0=1`, and the `n>=1` tail-formula domain. |
| Bellman continuation formulas omitted STOP's terminal reward | READ/SKIP recursions are explicitly restricted to nonterminal branches; STOP equals conditional correctness of the frozen classifier. |
| A compressed hidden vector need not be a sufficient Markov state | The valuation state is identified as a causal history node; the deployed policy sees only its public projection. |
| A refitted controller cannot inherit a different frozen candidate's provenance | Re-evaluation of original artifacts is distinguished from refitting; changed artifacts require a new complete manifest and a freeze before evaluation. The low-level CLI alone is not remote-publication proof. |
| Last-input ablations and query counterfactuals have different model coverage | Last-input ablations explicitly cover 54 ordinary/analytic frozen models. Query binding covers 36 recall models across all four architectures. |
| Complete forced-first world enumeration has narrower configuration coverage than the Q-pi recursion | The report explicitly identifies six models' `heldout_a` roots: six models times three first actions times 1024 worlds equals 18432 executions. |
| “Six families/seeds” could be misread as six architectures | Reproduction now says six family–seed combinations, comprising two families and three seeds. |
| Development evaluation precedes candidate freezing | Both documents distinguish development selection from the final heldout test. They do not assert that all dev evaluation occurred after candidate freezing. |
| Training process timing could imply one process per fit | The report identifies two full training stages covering 108 fits and separately describes per-fit and whole-process timing scopes. |

The final reviewer directly made only the three owner-authorized scope edits
concerning the 54-model ablation, six `heldout_a` roots, and six family–seed
combinations. The owner made the other corrections before this final readback.

## Mathematical assessment

The renewal identity is valid for the stated fixed process
`X_t=x+mu*t+sigma*W_t`, with `x>=0`, `sigma>0`, a fixed reset distance `r>0`,
fixed refractory delay `d>=0`, and identical coefficients across renewed waits.
The first event counts immediately on first hitting. Independence and the
distance-additive first-passage Laplace transform give the stated count tail.
The positive-refractory sum is finite; the zero-refractory implementation is a
controlled infinite sum with recorded remainder bounds, not an exact finite
truncation. Positive drift retains its defective first-passage mass at infinity.

The report correctly separates this analytical identity from floating-point CDF
evaluation, finite-difference checks, quadrature, and finite Monte Carlo
evidence. The reported Monte Carlo agreement is statistical corroboration, not
proof of the identity or a direct empirical identification of infinite waits.

The neural gate `1-exp(-E[N])` is explicitly a deterministic rate mapping. It is
neither the probability of at least one renewal event nor the exact expected
state of a nonlinear sampled reset network. Each call reconstructs its positive
distance from the current preactivation; it does not transport a complete
cross-token survival distribution or refractory age. The generality limits for
content-dependent coefficients, moving boundaries, and state-dependent resets
are stated. Only the initial-distance gradient is trained in this study.

The policy report distinguishes optimal continuation `Q*` from a forced first
action followed by the same deployed policy `Qpi`. Conditional classification
reward and future action fees are included. The stated finite-task value zeros
do not imply classical smooth pasting, a unique scalar voltage boundary, or a
solution of the proposed coupled Call/Put control problem. Cost-ray errors
outside the training and original heldout tariffs are explicitly described as
an extrapolation pressure test.

## Numerical crosschecks

The width-64 accuracy and training-cost table, blank-delay table, parameter
counts, and all 27-pair win/tie/loss summaries agree with the saved model
summary. The policy table and interaction terms agree with the saved exact
finite-expectation results. Rounded values in the report match the underlying
numbers. Selected independently recomputed values follow.

| Quantity | Recomputed value |
|---|---:|
| Ordinary lightweight return | 0.6709319166666666 |
| Ordinary value-policy return | 0.65222198924 |
| Analytic lightweight return | 0.671824 |
| Analytic value-policy return | 0.6532592257433333 |
| Controller effect, ordinary | -0.018709927426666707 |
| Controller effect, analytic | -0.01856477425666671 |
| Two-by-two interaction | 0.00014515316999999528 |
| Original heldout roots where READ is suboptimal relative to Qpi | 7 of 24 |
| Cached forward CPU ratio, median of 27 pairs, batch 1 | 20.175341579973026 |
| Cached forward CPU ratio, median of 27 pairs, batch 64 | 21.855563299939238 |

Occupied-state legal-action advantage statistics were checked as equal means of
per-seed/configuration results, not as pooled RMSE. Ordinary `Q*`/`Qpi` RMSEs
are 0.10940498727126922 / 0.12525791517576307; analytic values are
0.10605701682982696 / 0.12365405113730221. Deployed sign accuracies are
0.44863303244619523 and 0.44769178542799043, respectively.

For the posthoc query diagnostic, all 36 prediction-payload hashes matched;
saved predictions matched logit argmax, and labels matched the shared inputs.
Recomputed original accuracy, distinct-history three-query accuracy, and
distinct-history all-three-correct rate produced 108 numerical comparisons with
maximum absolute discrepancy zero. There are 114 all-distinct histories among
512; majority accuracy on the original queries is 0.63671875. The saved original
query replay discrepancy is zero for every model. This is the same test subset,
not a new independent dataset; three counterfactual queries share each history.

The report's renewal error maxima and Monte Carlo standard-error statement
match the earlier raw-case analysis in `RENEWAL_RESULTS.md`. Its policy parity,
regret, execution-count, and boundary figures match the saved policy checks. No
new event sampling or world enumeration was performed during this review.

## Fairness and timing scope

The earlier training audit checked 32400 logs across 108 fits: identical raw
batches within each task/seed group across four architectures and three widths,
plus bitwise-equal initial arrays in 27 ordinary/analytic pairs. Across all
architectures, 997 of 999 parameter arrays changed. The two dormant LIF arrays
and their complete logs are retained. Cross-architecture initial equality is
not claimed.

The report correctly limits strict parameter matching to ordinary/analytic.
At width 64 on digits, parameter counts are 9994 / 9994 / 5322 / 34442 for
ordinary / analytic / LIF / Transformer. Equal widths and update counts do not
mean equal parameter budgets, equal training compute, or optimized models.

Recomputed actor CPU means per paired trajectory are 0.2323422714843739 ms
(ordinary/light), 0.4242280214843794 ms (ordinary/value),
1.2978209557291869 ms (analytic/light), and 1.8645841562500207 ms
(analytic/value). The documented scope includes control, content stepping,
guards, raw access, readout, and evidence hashing, and excludes outer world
generation and gzip output. It is not a pure deployment-kernel benchmark.

All 22 recorded child-process phases have exit code zero and nonoverlapping
start/end intervals. Summing their user plus system CPU gives 602.515913 seconds;
wall time totals 602.9322405259736 seconds. The two full training stages total
246.7739045729977 wall seconds. The report excludes publication, review, report
production, and archiving from these sums and makes no energy claim.

## Evidence identities and archive scope

| Saved input to this review | SHA256 |
|---|---|
| `analysis/summary.json` | `177bb2eef92857d7b9eb87bb898460cb4e93e84f1a14a05983f26ae46362dc25` |
| `analysis/policy_results.json` | `35fcf556585013a6d3367b75da9fd728865378cf9107bebe43eeec4faef9538e` |
| `evidence/recall_binding_posthoc/summary.json` | `29a50c9f3bdf60dd99f95c2a721bf9c9577f320478dbb2e877423e3b40f28ed3` |
| `archives/evidence_v1/MANIFEST.json` | `ac5dc163bf097c5bd6271c47f51239e0e293128214678e095faea3a4de099b52` |

The manifest records 2140 members, 133777817 member bytes, 107 parts, and
111259845 compressed archive bytes. Member and part sizes sum to those values.
Its aggregate archive SHA256 is
`18075523df1ba5f5f75a01b8db7cf04850bc70d55a91b970e8e37a32ad285d5f`.
This final review checked manifest consistency, not a second compression or
restore run. Source, reports, figures, Git metadata, and this review are outside
the evidence-only archive and are preserved through the owner's Git publication.

The negative results and scope limitations are retained. The final report is
supported as an account of this prototype and protocol; it should not be cited
as proof of broad neural-architecture superiority or impossibility.
