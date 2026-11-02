# R15: distribution content, independently trained control, and paid recovery

This study continues the exact R14 source at
`c0949e9cde89a54609a5133c0fb7f9c65bc80f4a` (PR #4549).
It replaces the fixed scalar renewal gate in the primary content comparison
with a position probability law and position-conditioned content first moments.
The finite-grid law is not an arbitrary joint density over neural content.

The active campaign is `results/formal_03`, with byte-identical scientific
registration inherited from `formal_02`. `formal_01` was superseded before
training or confirmation when validation-only development exposed substantial
artificial upper-boundary loss. The six-worker `formal_02` attempt was
interrupted by OOM/SIGKILL; `formal_03` uses at most two workers. Its original
launcher later reported ENOSPC while writing a receipt, after thirteen complete
groups. Those groups are immutable; the remaining nineteen are rerun in fresh
work roots under the same seeds, objective, data, budget and selection rule.
All failed candidates and operational attempts remain in the evidence. See
[`publication/ENOSPC_RECOVERY_ZH.md`](publication/ENOSPC_RECOVERY_ZH.md) for the
preservation and accounting rules. A running or successfully executed campaign
does not itself establish scientific benefit.

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

### Separate training and execution interventions

The supplementary registration at
`results/formal_03/train_execution_cross/SELF_REGISTRATION.json` defines the
four training/execution cells within each primary core:

| Content training | Read-all execution | Value-controlled execution |
| --- | --- | --- |
| Light training | LL | LV |
| Value training | VL | VV |

LV applies the same task/seed value controller to the independently
light-trained content model without refitting or recalibration. LL, VL and VV
reuse the original complete-cohort actual execution arrays. All four simple
effects and their interaction are reported using eight paired fit seeds.
The original A–D core/training comparison and this within-core factorial have
distinct estimands; neither substitutes for the other. The same-weight
conditional D−B and original D−B are required to have identical fit-level values.

Within one task/seed/training-mode group, all six families share the mean loss,
global gradient clipping and validation-selected checkpoint step. The light
and value groups have separate optimization and checkpoint selection. Thus
the result concerns this joint training procedure; the six families are not
six independent experiments. See
[`publication/ESTIMAND_REVIEW_ZH.md`](publication/ESTIMAND_REVIEW_ZH.md).

### Complete-cohort actual execution

The full-online supplement registers 2,160 conditions of 512 objects each:
1,105,920 actual executions across every family, task, domain, fit and original
execution cell. The within-core factorial adds 240 LV conditions, or 122,880
executions. These counts describe the registered workload, not a claim that
all work is complete. Actual executor outcomes, actual fees, CPU timers and
replay comparisons are kept separate; a replay confidence interval is never
attached to an actual-execution point estimate.

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

`publication/runtime_ledger_v3.py` separates canonical successful worker costs,
the retained OOM attempt, and every independent ENOSPC/resume process attempt.
Lost wait4 measurements remain unknown. A consolidated training TOTAL is
explicitly labelled as resumed; its wall time includes the interruption and
does not assert that the original launcher completed normally.

No favorable task result alone closes foundation-core or all-user-requirement
acceptance. The machine-readable decisions explicitly retain the unmet scope.
