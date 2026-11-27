# Retained-state representation probes

The final local audit completed every retained training posterior in the pinned hosted factorial pilot: 12 declared seed/arm runs, 384 episode/update trace records and 14,336 posterior positions. It probes the existing finite QPR implementation; it does not certify a continuum model or implement a faster recurrent network.

The practical findings are limited but concrete. Collapsing the active distribution to its conditional mean substantially changes the candidate's next-interval event probability. Unrepaired low-rank transition matrices violate positivity, row mass and refractory/phase behavior. Content-only low-rank approximations have smaller arithmetic storage estimates and preserve the probability vector, but their task and recurrent rollout effects have not been measured.

## Evidence and source identity

The audited hosted pilot is `/dev/shm/hcsn-hosted-43127560720/experiment`, with `SUMMARY.json` SHA256 `c60378ffc2a51f580a9b7cfd11a09cec5f53d9a9cc37c03b81605bedc54b8715`. This is a separate execution identity from the local factorial pilot, even where inputs and code agree. Each source file, DATA/PLAN, per-arm result and complete training trace is bound to the pinned summary. Every trace is checked for step, episode, physical time, validity mask and complete state dimensions. All input hashes are rechecked at the end.

Version 003 additionally records the audit module and imported admission-helper SHA256 values before reading experiment inputs, then rejects either source changing before completion. Its isolated source tree is retained. The source-change negative control separately mutates an audit fixture and a helper fixture; both are rejected by the same guard used in the full audit. All five tests passed. No gradient-audit module was edited for this change.

The final result SHA256 is `ff6433f033cb1c57597e72325fefc4e72c834275f9fc3d8108f88fa543bf51c9`. The compact receipts and archive identity live in `evidence/representation-20261112-8262/`. The archive preserves all three attempts and their available original source snapshots; the final attempt also includes the complete executing dependency snapshot. The original hosted training data and traces retain their separate factorial archive identity.

## Actual visited domain

| Recorded quantity | Observed range or count |
| --- | ---: |
| Episode/update traces | 384 |
| Posterior positions | 14,336 |
| Positive training gaps | 0.001, 0.003, 0.02, 0.04, 0.08, 0.16 |
| Saved log boundary | -0.0079167232 to +0.0086938858 |
| First active-cell mass | 0.0099511913 to 0.1779507049 |
| Tail-cell mass | 0 to 3.1969073e-7 |
| Refractory mass | 1.9322714e-5 to 0.1162433312 |
| Maximum probability mass defect | 4.4408921e-16 |
| Smallest positive stored coefficient | 8.35e-322 |
| Distinct physical parameter tuples | 184 |

These are stored floating-point values, including zeros and subnormal numbers. They do not establish relative accuracy of rare tails. The experiment did not vary low noise or test intervals longer than the candidate's refractory period. Its training sources remain synthetic.

## Conditional mean-margin approximation

For each saved posterior `p`, retain active occupancy `a`, replace its normalized active law with an atom at its conditional mean log margin, and retain every refractory coefficient. The dense reference is `p @ risk`. The approximation is `a * F(mean_margin, dt) + p_phase @ risk_phase`, using the same candidate parameters. Thus this is a specific distribution collapse with phase memory still present, not a scalar-only network.

Every saved posterior is crossed with every distinct positive observed training gap. This is 14,336 × 6 = 86,016 posterior/horizon probes. It is not restricted to the actual next gap that followed a given posterior. Reported averages weight posterior positions equally; they do not give episodes or tasks equal weight.

| Horizon | Mean absolute risk difference | Maximum absolute difference | Mean signed difference, approximation minus dense |
| --- | ---: | ---: | ---: |
| 0.001 | 0.002711131 | 0.005273369 | -0.002711131 |
| 0.003 | 0.004719711 | 0.009180220 | -0.004719711 |
| 0.02 | 0.012414479 | 0.024147166 | -0.012414479 |
| 0.04 | 0.017777975 | 0.034579431 | -0.017777975 |
| 0.08 | 0.025642356 | 0.049833632 | -0.025642356 |
| 0.16 | 0.038360935 | 0.073439596 | -0.038360935 |

The mean collapse underestimates risk in these aggregate results. The maximum difference is approximately 7.34 percentage points of event probability. This is evidence that the retained distribution affects the candidate's risk calculation; it does not establish downstream task gains or a general inequality for all possible posteriors.

## Content-only SVD: an offline oracle

Each saved content-mass matrix is independently replaced by its best rank-r approximation in Frobenius norm, while its probability vector is retained exactly. Singular values are absorbed into one factor for the storage calculation. No compressed state is fed into a subsequent model step; no model is trained or evaluated using these factors.

| Content rank | Estimated probability + factors, bytes | Mean / maximum content Frobenius error | Mean / maximum absolute summed-content coordinate error |
| --- | ---: | ---: | ---: |
| 1 | 432 | 0.035534861 / 0.060909549 | 0.012458030 / 0.049979193 |
| 2 | 664 | 0.013563772 / 0.027034038 | 0.006355871 / 0.039544499 |
| 3 | 896 | 0.003022434 / 0.006101996 | 0.000843879 / 0.005091945 |

Dense probability plus content uses 1,000 FP64 bytes under the same payload convention. These storage figures exclude metadata, SVD work, temporary dense states, weights and optimizer state. Retaining probability preserves its immediate fixed-parameter risk calculation, but summed content changes, and recurrent error can accumulate after repeated compression. The evidence supports investigating a content compression method; it does not demonstrate memory savings in a deployed model or a training/inference speed improvement.

## Transition SVD: rejected without repairs

The candidate's one-step transition matrix at the largest observed gap, 0.16, is approximated by a truncated SVD. No clipping, renormalization or phase repair is applied. Both transition into phase destinations and full phase-source rows are inspected, so a changed release distribution cannot pass solely by preserving destination-phase coefficients.

| Transition rank | Minimum entry | Maximum row mass defect | Maximum phase-destination row L1 error | Maximum phase-source row L1 error | Maximum second-interval event-probability difference |
| --- | ---: | ---: | ---: | ---: | ---: |
| 4 | -0.08035548 | 0.95603321 | 0.99904482 | 1.06296893 | 0.06470220 |
| 8 | -0.09777255 | 0.46916254 | 0.50437078 | 0.65900882 | 0.05471979 |
| 12 | -0.09233172 | 0.38995980 | 0.47411544 | 0.91464666 | 0.02561074 |

All three candidates fail the declared local eligibility checks. The risk statistic compares `(p @ P) @ risk` to `(p @ P_rank) @ risk`: an event probability in the second interval after one unobserved propagation. It is not the probability of at least one first hit over the combined two intervals, and it does not condition on surviving the first interval.

There are 384 matrix applications per rank, one per saved episode/update trace, but only 184 distinct parameter matrices at this gap. Negative-entry totals count repeated applications; they are not counts of unique coefficients. Across all six horizons, the cache constructs 1,104 distinct parameter/horizon tables. Neither factor multiplication nor the scalar storage formula is an observed optimized-kernel benchmark.

## Attempts, corrections and measured cost

| Attempt | Change | Internal audit wall / CPU seconds | Complete child wall seconds | Outcome |
| --- | --- | ---: | ---: | --- |
| 001 | Initial offline probes | 15.2566 / 15.1477 | 15.6302 | Completed; original misleading phase-row and two-interval labels retained |
| 002 | Separate phase destinations/source rows; name second-interval probability precisely | 10.6959 / 10.6724 | 11.0048 | Completed |
| 003 | Audit/helper source guard, Cartesian scope, distinct/application count semantics | 10.1356 / 10.0772 | 10.4151 | Completed; final source unchanged |

The three audit children consumed 37.0500 observed wall seconds in total. The final five-test child took another 4.5278 wall seconds (test body 0.023 seconds); earlier test costs and packaging are not inferred. The internal and outer measurements overlap within each attempt and must not be added together. Version 003's whole-child CPU was 10.3542 seconds. These costs include imports and provenance checks and were observed on a shared host, with concurrent audits possible; the timing differences between versions are not an optimization claim.

All common numerical sections of 003 equal 002 exactly, including coverage, mean-margin errors, content errors and transition defect/risk statistics. Only the source identity and scope/counter descriptions changed. The original 001 and 002 outputs were preserved rather than overwritten.

## Reproduction and admission

From the pinned source tree, with CPU PyTorch and NumPy available:

```bash
python -B -m unittest qualification.hcsn_boundary_audit.test_representation -v
python -B -m qualification.hcsn_boundary_audit.audit_representation \
  --pilot /path/to/pinned-factorial-output \
  --summary-sha256 c60378ffc2a51f580a9b7cfd11a09cec5f53d9a9cc37c03b81605bedc54b8715 \
  --output /path/to/new-result.json
```

An existing output is rejected. The source must match the summary, and the audit must see the full declared roster and complete traces. Scientific admission remains `HOLD_NO_GO`: independent continuum accuracy, relative rare-tail precision, compression rollout semantics, task quality, actual optimized cost and product adoption are not established by this audit.
