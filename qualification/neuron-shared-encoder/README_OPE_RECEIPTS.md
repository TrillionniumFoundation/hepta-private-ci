# X/P/Y/Z causal and OPE receipt boundary

This is a research-only adapter for the shared Stem transfer plan. It is
stacked after the immutable Stem, Cell, Reader and equal-budget contracts. It
does not run a checkpoint, train a Cell, select a candidate, mutate a snapshot,
or grant production authority.

## Existing ledger contracts

The repository already has a durable learning-ledger path:

- `LearningDecisionV1` exposes the selected candidate, candidate-set digest,
  policy digest and logged propensity;
- `OutcomeReceiptV1` is a compatibility view of a terminal authenticated
  outcome;
- `OutcomeWatermarkProtocolV1` and `LearningEpisodeV1` preserve delayed
  observation, censoring, correction predecessor and finalization state;
- signed generator/evaluator role separation and NDU certificates remain
  independent, evidence-only, and `DENY_ALL`.

Those interfaces are intentionally general. The shared Stem experiment needs a
stricter OPE projection that keeps the model-visible context, action policy,
independent outcome and resource/censoring accounting as separate receipts.

## X/P/Y/Z split

`ope_receipts.py` defines:

| Plane | Receipt | What it binds |
| --- | --- | --- |
| X | `ContextReceiptV1` | request/context digest, independent source and Git blob, Reader manifest, source split, gold exclusion |
| P | `PolicyDecisionReceiptV1` / `DecisionReceiptV1` | candidate set, selected action, logging/target propensity, support, policy and budget |
| Y | `DelayedOutcomeReceiptV1` / `OutcomeReceiptV1` | independent observer, delayed watermark, terminal/pending/censored state, utility and correction lineage |
| Z | `OPEResourceReceiptV1` | forward calls, tokens, FLOPs, memory, latency, energy, parameter counts and evidence class |

`XYZEpisodeV1` binds exactly one receipt from each plane by episode ID and
requires independent policy and outcome principals. The four receipts have
different digests; a caller cannot replace a missing outcome with a resource or
policy receipt.

## Support-aware estimators

`estimate_ope()` implements bounded research versions of:

- IPS: `mean((target propensity / logging propensity) * outcome)`;
- SNIPS: the normalized weighted outcome;
- DR: a caller-supplied nuisance pair `(mu_logged, mu_target)` plus the
  importance-weighted residual.

All estimators require positive logged support, a matching immutable budget,
resource values below that budget, and terminal outcomes. Pending and censored
outcomes remain in the audit count and are excluded from the terminal estimate.
The adapter computes effective sample size, maximum importance weight and a
normal-approximation research interval. The interval is not a causal or
efficacy certificate.

Synthetic evidence is never relabeled as real. The default path requires
`REAL_SHADOW`; callers may explicitly run a smoke calculation with
`require_real_shadow=False`, in which case the output remains
`SYNTHETIC_SMOKE` and `model_efficacy_measured=False`.

## Next real gate

The next experiment must map the actual pinned harness receipts into these
planes without renaming their raw evidence class. It must preserve the
existing Rust ledger's independent observer and delayed watermark, bind the
same Reader source/blob/request identities used by #2685, and charge encoder,
Cell, controller and verification costs under one fixed budget digest. Only a
future-window/OOD matrix with complete terminal outcomes, support diagnostics,
ESS, IPS/SNIPS/DR intervals, resource receipts and independent review can be
considered for a later shadow advisory. None of that is supplied by this
protocol-only module.
