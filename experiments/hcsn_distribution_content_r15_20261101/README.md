# R15: distribution content, independently trained control, and paid recovery

This study continues the exact R14 source at
`c0949e9cde89a54609a5133c0fb7f9c65bc80f4a` (PR #4549).
It replaces the fixed scalar renewal gate in the primary content comparison
with a position probability law and position-conditioned content first moments.
The finite-grid law is not an arbitrary joint density over neural content.

The registered campaign is `results/formal_02`. `formal_01` was superseded
before training or confirmation when validation-only development exposed
substantial artificial upper-boundary loss. That failed candidate and its
source snapshot remain in the evidence.

## Comparisons

| Core | Independently light-trained, read-all | Independently value-trained, shared critic |
| --- | --- | --- |
| Ordinary distribution dynamics | A | B |
| Regenerative distribution dynamics | C | D |

All five total-effect contrasts are reported: B-A, D-C, C-A, D-B and
(D-C)-(B-A). Separate same-weight execution ablations apply read-all to the
value-trained backends. Those conditional effects are never substituted for
the independent-training total effects.

Each task/fit/value group shares one identical R14 value controller across
six backend families. The additional candidates are the original ordinary
dual gate, fixed renewal gate, pinned Mamba-1 CPU reference and causal
Transformer. Validation selects the strongest registered ordinary candidate;
confirmation data do not choose the comparator.

There are two synthetic raw-vector tasks, eight fit seeds, two independent
training modes and six backends: 32 training groups and 192 backend fits.
Each group has 768 minibatch updates. Source, recipe and nonconfirmation object
identities are frozen before confirmation.

## Correctness and information boundaries

- Complete zero-delay renewal transport includes repeated events and reset
  remaining time. The fine spatial grid is extended with a nonuniform tail;
  the original learned anchor positions stay fixed.
- Every actual probability state retains its upper cemetery. Selected-model
  validation and confirmation record cumulative loss at every prefix. Passing
  an initial-atom numerical check does not qualify all learned posteriors.
- Raw tasks use disjoint query-invariant partition units; binding's four
  combinations stay together. Repeated fit seeds and rows are not treated as
  independent heldout contexts.
- Initial STOP is a real decision. Future timestamps/budget are public;
  unread payloads and labels are not controller inputs. READ targets follow
  the actual continuation policy after the registered warmup.
- Three execution interventions distinguish unweighted-content collapse,
  spatial-mean collapse and association removal preserving the current
  weighted readout. Their estimands remain separate.
- Recovery executes none, reset only, replay only and reset plus replay from
  the same damaged prefix, with explicit actual suffix processing and fees.

See `LAW_CONTRACT.md`, `RECOVERY_CONTRACT.md`, `AUDIT_NOTES.md` and the frozen
protocol for exact scope. Physical-parameter tangents on the nonuniform grid,
learned moving boundaries, learned reset kernels, natural media, general scale,
GPU, physical energy and provider billing are not qualified by this study.

## Evidence and costs

`SUMMARY.json` and `EFFECTS.csv` are reconstructed from raw outcomes and frozen
validation choices. `audit.py` independently reconstructs fees, utilities,
coverage, source/checkpoint identities, posterior records and total effects.

Process CPU includes startup, fitting, validation and evidence writes.
Nested body timers are descriptive and are not added to process totals.
Task fees are synthetic utility tariffs, not Joules or provider invoices.
Cold microbenchmarks clear transition caches; they do not measure cold process
startup. Microbenchmarks and complete-cohort execution are separately labelled.

No favorable task result alone closes foundation-core or all-user-requirement
acceptance. The machine-readable decisions explicitly retain the unmet scope.
