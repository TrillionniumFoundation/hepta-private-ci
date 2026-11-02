# Independent review of the R15 experiment

## Fixed scientific baseline

This experiment continues PR #4549 at
`c0949e9cde89a54609a5133c0fb7f9c65bc80f4a`. The R14 record established
finite-profile numerical checks and causal action accounting. It did not
establish a stable analytical-core benefit, a full conditional-distribution
content model, or total effects of independently trained light policies.

## Estimands that must remain separate

For the registered ordinary-distribution and analytical-distribution pair:

| Arm | Training | Execution | Core |
| --- | --- | --- | --- |
| A | Independent light fit | Read all | Ordinary distribution |
| B | Independent value fit | Shared value policy | Ordinary distribution |
| C | Independent light fit | Read all | Analytical distribution |
| D | Independent value fit | Shared value policy | Analytical distribution |

Report `B-A`, `D-C`, `C-A`, `D-B`, and `(D-C)-(B-A)`. Light and value
training must start at the same per-family initialization and end at separate
checkpoints. Read-all execution of value-trained weights estimates a different,
conditional execution effect; it cannot replace A or C in this table.

The controller's weights must be identical across all value-trained families
within a task/fit group. The ordinary family selected by validation is an
additional comparison, not a post-test replacement for the registered matched
ordinary-distribution pair.

## Substantive review findings

1. The binding generator creates four outcomes for each common context.
   Object rows are paired measurements, not four independent contexts. Aggregate
   within `group` before context-based uncertainty calculations. Shared heldout
   objects across fit seeds also do not become new independent objects.
2. Distributional state has more runtime capacity than a single hidden vector.
   Parameter equality alone cannot attribute an advantage to transport.
   The primary ordinary-distribution comparison must match probability/content
   state dimensions and active parameter counts. Strong vector/SSM/attention
   baselines remain necessary and their actual resource differences must be
   reported.
3. Predicted class confidence is a belief. It is not automatically calibrated
   expected STOP reward. Preserve occupied-state calibration and observed action
   consequences even if terminal-value structure is constrained.
4. The inherited actor observes the complete timestamp/budget schedule before
   initial STOP. This is an explicit task assumption. Payloads must still be
   acquired only after READ. It does not establish unknown-arrival performance.
5. Training objectives may differ between light and value regimes as part of a
   total treatment effect, but the difference must be declared. All families
   within a regime need identical data, batches, update counts, validation rules,
   and controller structure. Report measured CPU as well as update counts.
6. Actual online execution must agree with the evaluated actor on predictions,
   read counts, and fees. A full-prefix offline pass is not an online timing
   substitute. Recomputed paid prefixes incur real processing cost.
7. Separate null-information missing-modality domains from informative quality
   domains. Report every registered stress domain, including negative results.
   A positive selected domain does not establish stable overall benefit.
8. A finite spatial generator with fixed boundary, fixed transport coefficients,
   and an upper cemetery does not establish a learned continuous boundary or
   an exact infinite-domain process. Numerical and content claims require
   separate acceptance decisions.
9. Tariffs for synthetic reads/replays are task utilities, not measured device
   Joules or external service prices. CPU timings do not establish GPU results.

## Audit boundary

The result checker independently reconstructs arithmetic from per-object
records and checks declared identities/coverage. It does not prove the absence
of arbitrary hidden channels, a continuous-model theorem, or hardware/service
measurements. Source review, causal perturbation checks, raw process receipts,
and numerical references remain distinct evidence.

The checker must fail on missing required records and must keep
`foundation_core_acceptance=false` and `all_user_requirements_closed=false`
unless a separate, complete acceptance decision establishes their conditions.

## Development source observations

Before formal freeze, a direct comparison of the initial proposed generator's
train and validation raw inputs found 33/256 recall validation rows and 72/256
binding validation rows exactly repeated from training. Only train/validation
data were inspected. Different random seeds do not ensure unseen examples in a
finite template support. A disjoint content/context split is needed for an
unseen-object claim; otherwise the experiment must be described as fresh IID
draws with possible repeated inputs. This observation prompted a source review
before any confirmation data were accessed.

The distribution core stores spatial probability and conditional content first
moments, not an arbitrary joint content density. Its observation update defines
a learned moment closure. The `content_independence` execution intervention
preserves unweighted content first moments but can change the current
position-weighted readout immediately. It is a complete execution intervention,
not a matched-current-prediction proof of future information value.

The first context-only partition still allowed query-swapped validation inputs
to repeat training inputs. The final pre-confirmation revision assigns the
entire query-swap orbit to one split and deduplicates complete raw contexts.
Independent checks in `development_data_audit.json` passed 62/62 checks on
train/validation only: raw inputs, complete context IDs, and partition IDs are
disjoint; query swaps in both directions never reproduce the other split's IID
inputs; all stress variants retain their original context/partition IDs; the
four-row binding balance and missing-modality balance remain intact. The prior
intermediate audit remains in `development_data_audit_context_only.json`.

Partition units are a more conservative uncertainty cluster than individual
binding quartets. The development audit found 49 such units among 256 training
quartets and 16 among 64 validation quartets. Confirmation summaries must report
both counts, and any context bootstrap should account for this grouping.
