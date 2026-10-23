# Group-wide budget clarification and next TRAIN proposal

This is a post-result review/proposal, not another execution authorization or
an amendment to the completed frozen study. No new training, gate, old-system
retest or formal confirmation accompanies it.

## The caps cover the entire group, not each candidate

The authoritative original total ledger and CPU account are
[`runs/content-control-train-r2-20261023/build.json`](../runs/content-control-train-r2-20261023/build.json).
For each arm, inspect `ledgers[ARM].totals.consumed_units`, its stage/kernel
breakdown, and `costs[ARM].complete_cpu`. The per-group WorkLedger has cap12B;
the actual CPU guard checks the complete group against10 seconds. Both are
enforced during the build; a violation retains its ledger and returns nonzero.

The source is bound by [`frozen-train-v2.json`](frozen-train-v2.json), source
commit `fbaac5b926`, execution commit `d986d4c64b`. In `run.py`, the training
allowance for ONE seed/LR candidate is calculated as:

```
candidate_units = (12B - full_shared_units - applicable_feature_units - 500M) // 9
candidate_CPU = (10s - full_shared_CPU - applicable_feature_CPU - 2s) / 9
```

The500M/2s reserves are admissions headroom, not consumed work or free extra
budget. Nine candidates share this allowance. The ONE group ledger also pays
actual objective setup, all candidate training, all LR/path scoring and decoded
observations, gradient evidence, model exports, selected-service/reload work,
and decoder-corruption observation. Actual stage charges, not the reserves,
determine the group total. Refiner candidate training averages all five paths;
its nine models yield45 scored LR/path/seed combinations, all within the SAME
group cap. There is no independent10-second or12B allowance per path/model.

Shared preparation contains all three decoder/base trainings, full data
preparation, compiler, imports, observer preparation, base exports and one
pre-adaptation service calibration:2.075925876 CPU seconds/3,486,924,537 units.
This entire amount is attributed to EVERY group. Refiner feature preparation
adds.212571458 seconds/138,037,248 units to EACH refiner. Scheduler/setup
.004935890 seconds is also attributed in full to EVERY group. All nine
candidate active CPU intervals plus selected-service/observer/export intervals
are accumulated into the relevant group's active CPU. Another group's training
is neither hidden as common nor subtracted as a budget credit.

| Group | Candidates trained | Candidate updates, all9 combined | Complete CPU seconds | Complete units |
|---|---:|---:|---:|---:|
| S | 9 | 3564 | 5.043679068 | 11,664,350,313 |
| H | 9 | 3564 | 5.023574262 | 11,664,350,313 |
| A | 9 | 3483 | 5.409933441 | 11,664,058,551 |
| H_R | 9 | 3991 | 8.127059989 | 11,658,601,814 |
| A_R | 9 | 3075 | 8.345216789 | 10,621,075,206 |

Complete CPU-net reporting amortizes each whole group's three-seed/nine-candidate
build cost over its three selected seeds, H100000 requests per seed. It does
not amortize only the winning candidate and discard search. Service preparation
and real PNG/hash/JSON work are retained. Observations are outside the narrower
service timer but inside the charged build CPU and declared-work ledger.
Input generation, allocation/copy, byte processing and metadata checks have
measured CPU but no invented hardware-FLOP prices. Final administrative JSON
archival/descriptive post-build statistics are separately reported; they are
not model-training credits or claims of equal cumulative R&D budgets.

The failed first construction remains additional research cost:1.554477821 CPU
seconds/37,616,283 units. It is not deducted from the successful builds. The
physical combined successful execution used23.479634726 CPU seconds; attributing
full shared work to each group makes the sum of attributed group costs larger
than that physical execution. These caps are ceilings, not equal consumption.
See [RESULTS.md](RESULTS.md) for the complete boundary and retained failures.

## Evidence for one next content-training hypothesis

Dense A-H utility was+.00264133 on selected TRAIN inner validation, positive
for all three seeds, despite fewer selected updates (387 versus396 per seed).
The selected A model beats A_R by.00737952; even free label-known per-row routing
cannot recover this difference. A_R-H_R is negative for all seeds. Accordingly,
the next hypothesis should keep the useful dense representation/content update
and address its operator cost, rather than enlarge this failed refiner/gate.

The dense group is close to its operator ceiling with substantial CPU headroom
(A5.4099s/11.6641B). Saving only Python dispatch time cannot be assumed to admit
more work under the unchanged12B cap. A_R's high wall/kernel overhead, frozen
base and five-path training all differ from A; these data do NOT identify
permanent encoder freezing as the causal failure. They motivate testing a
smaller change that retains encoder adaptation.

**Proposed single candidate: deterministic1:1 block updates of the existing
dense encoder/two heads.** Alternate one normal encoder+both-head update with
one both-head-only update. Every minibatch still encodes the actual fixed input;
on head-only steps skip encoder/tanh backpropagation and encoder/bias optimizer
work altogether. Do not execute those kernels then charge a saving, or pass
zero gradients and silently advance encoder Adam moments/clocks. The encoder
remains trainable on joint steps; both content heads change on every step.
No new parameters, learned router, early exit, decoder, utility or reward weights.

For the existing n64/d202/h32/k12 geometry, deleting encoder backprop and the
head-to-hidden derivatives removes
`n*(d*h + 2*h*k) = 462848 MACs` on a head-only step, plus the corresponding
encoder gradient/optimizer work. This is an algebraic inventory opportunity,
not a measured speedup, admitted update count or promised quality gain. Extra
head steps may be insufficient, or fewer encoder updates may hurt. Either
outcome must remain visible.

A later TRAIN registration could limit this to exactly one fixed1:1 schedule,
the existing three seeds/LRs, and matched0.2-CE H_block versus additive A_block.
The existing dense S/H/A are the effective reference; preserve their saved
model/input hashes and all receipts. Use fixed TRAIN physical-source grouping
and a bounded internal validation design, with no formal data and no favorable
subset selection. Keep the original10-second/12B complete-group ceilings,
including all candidate searches, inherited preparation, necessary observation,
adapter setup/export and service. Native block-optimizer semantics would first
need hand-array checks for actual parameter updates, unchanged inactive moments/
clocks and agreement with the established NumPy Adam equations. No such code
or experiment has been run here.

Use the already saved bases and TRAIN tensors for development instead of
retraining common models or duplicating their data. Reused preparation is
attributed at full inherited cost, with new access/adapter work added. Reusing
old model-quality arrays can support a descriptive content comparison; CPU-net
claims across different execution waves require a separately reviewed timing
design and cannot be manufactured from the old wave. This proposal does not
authorize rerunning the old controls or starting a new shared measurement wave.

The candidate would be rejected if A_block-H_block fails to improve content,
if A_block fails to improve over effective dense A, if greedy retention drops
by more than.02, or if either complete cap fails. These are proposed TRAIN
readiness requirements, not formal acceptance thresholds. No search over block
ratios, CE weights or seeds is included. The parent can review scope and costs
before any execution is considered.

Formal confirmation remains outside this proposal. The unchanged
[protocol draft](PROTOCOL.md) and [full historical/error-budget review](HISTORY_AND_CONFIRMATION.md)
require new physical provenance, fixed once-only opening authority, and honest
accounting for previous looks. The parent-reported toy exact-reference numbers
are documented [separately](MATHEMATICAL_REFERENCE_NOTE.md); they neither expand
this candidate nor qualify its budget or model benefit.

The parent subsequently reports an independent review of result commit
`86601343b8691a535f9f9105759ee03b1eb20061` with no new budget/split blocker.
Its [clarifications](HISTORY_AND_CONFIRMATION.md#parents-independent-review-clarification)
distinguish TRAIN search from formal alpha spending and explicitly allow
independent new synthetic physical sources. This proposal and every confirmation
draft remain unexecuted pending a unified design with the parent's NDU review.
