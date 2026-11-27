# Independent fresh42 + C1 review protocol

## Status and scope

This is a prepared independent review design plus tested logical checks, not a
report that C1 was deployed or that fresh42 finished. Native control remained
unavailable at preparation time. The original last readable campaign observation
was 2026-11-10 14:59:52 UTC; subsequent process outcomes must be recovered from
the original persistent job. No duplicate launch is authorized by a missing
acknowledgement. The original v8 and original v1 reviewer are immutable inputs.

C1 is an explicitly recorded protocol amendment after original epoch-cap
observations. It increases the total epoch ceiling from 100 to 400 for eligible
original baseline fits while retaining each fit's **actual original outer wall
ceiling**. It adds optimization work and a distinct source/validation phase.
It adds no learning rate, seed, diagnostic rerun or confirmation-subject access.
Calling it an unchanged original 100-epoch comparison would be inaccurate.

## Roster and admissible transition

Start with the complete predeclared 42-fit roster: seven cores, three seeds,
two learning rates. Preserve every original completion, failure, timeout and
not-started record. Wait for all original 36 baseline attempts to become terminal.
C1 may start at most three additional workers. The original six HCSN attempts
are excluded from C1 and remain unmodified.

Mechanically derive eligibility across all 36 baselines, not from attractive D
scores: original outer status completed, return code zero, completed-development
fit, source/shared identities unchanged, and all 100 complete contiguous epochs
ending at `epoch_cap_not_convergence`. A plateau stop, partial epoch, timeout,
failed source gate, missing claimed evidence or HCSN identity is ineligible.
Insufficient remaining time is an explicit non-launch outcome. A failed original
memorization diagnostic may coexist with eligibility to continue main training,
but its failure is inherited and prevents adequacy credit.

Permit at most one C1 child for each eligible parent. Bind parent report bytes,
outer record, plan, source, data manifest, initial/last/best/diagnostic checkpoints
and journal. List every excluded original attempt and its reason. Report 42
original candidate chains plus N additional continuation process attempts;
additional phases are not free work and are not fresh independent seeds.

## Source, state and data identities

Pin a separate tested C1 capsule and exact helper/controller hashes before
deployment. The original v8 source is retained. If inherited Python files are
formatted in the C1 capsule, preserve both byte maps and the explicitly checked
AST equivalence; identical AST is not identical source bytes. Extra continuation
modules need their own reviewed identities and tests. Re-read source/data bytes
after review. Generic v8 `resume_supported=False` is not retroactively upgraded.

The optimization start is parent **last.pt**, carrying model, construction
configuration, Adam state/counters, Torch RNG, sample-order RNG, completed epoch
and main update count. Parent best.pt is a separate selection artifact and must
not silently replace last.pt as the optimization start. Validate parameter names,
optimizer groups, unchanged LR/weight decay, frozen frontend/head, learned common
adapter, class weights, data partitions, batch/microbatch regime and exact model
configuration including Python-level PLIF threshold and dependency paths.

Validate restored RNG after model construction/loading. Independently derive
the first next-epoch sample order from parent `order_rng`; check every continued
epoch covers ABC exactly once and every completed update has matching episodes,
weighted numerator/denominator and optimizer counters. Complete epochs number
101 onward; counters are cumulative. No diagnostic events or optimization reset
are allowed. Journal and checkpoint metadata must agree. A sample-order check
alone does not prove optimizer or Torch RNG restoration; the frozen implementation
equivalence tests and actual state identities are separate evidence.

## Selection and stopping

Recompute strict best and meaningful-improvement plateau state from all parent
epochs. Strict best uses `score > best`; ties keep the earlier checkpoint. Plateau
uses `score > anchor + .002`, with the original minimum epoch and patience rules.
Recompute both independently over parent plus child epochs. A child that ties or
regresses must retain parent best bytes; only a strict improvement changes them.
Hash-bind the child's inherited-best field and the retained parent artifact.

Recompute every selected child-logit metric, check D labels/order and connect it
to the cumulative best epoch/checkpoint. Retain original selected logits even if
the continuation fails. A parent cap remains a parent cap in its immutable report;
any derived-chain adequacy is a separate conclusion requiring inherited diagnostic
success, the prescribed stopping condition, complete source/data/state evidence,
and unchanged common tensors. A new 400-epoch cap or an exhausted timer is not
convergence. Numerical qualification and scientific benefit remain separate HOLDs.

## Full cost and quality chain

For original dispatch time t, the actual outer limit is
`min(14400, 15000 - t)` seconds. A later fit can have less than four hours. C1 must
use `remaining = actual_parent_limit - parent_outer_whole_process_wall_seconds`;
never subtract the fit-only timer and never restore the nominal four-hour limit.
New imports, process startup, source checks, final evaluation, serialization and
cold-cache rebuilding consume that remainder. Record actual deadline/timeout
overruns if any; an OS timeout is not proof of a perfectly exact wall cutoff.
C1 is a distinct phase and may occur after the original campaign's 15,000-second
dispatch window. Preserving each fit's actual budget does not preserve that
original campaign calendar deadline.

For a continued epoch, cumulative cost is parent full outer wall plus child
absolute process wall. Preserve the earliest observed .30 crossing in either
phase. No interpolation or free phase-clock reset is allowed. Parent plus child
process-wall cost excludes waiting between phases; it is not calendar latency.
Resource opportunity envelopes serialize attempts in the declared roster and
are also distinct from concurrently observed end-to-end campaign duration.

Parent per-epoch process CPU is exact; parent final `cpu_seconds` is fit-entry
delta and misses imports. It cannot become exact exit CPU by addition. Preserve
the parent lower bound and unknown residual. New phase full process CPU is kept
separately. Aggregate waited-child CPU includes its preflight and failed children;
do not add duplicated per-fit subtotals to it. Charge every original and C1 failed
launch, partial run, timeout, diagnostic and failed probe. Keep controller/preflight
and shared PLIF tuning/HCSN qualification overhead explicit. Historical totals
remain incomplete where no retained counter exists; no energy is imputed.

The 300/900/1800 cuts were descriptive common budgets, not permission to optimize
thresholds after outcomes. For every fit expose its actual wall opportunity and
observed evaluations. Keep right censoring and no-evaluation states. Show each seed,
all-seed medians only when complete, and the D tuning envelope separately. Choose
one LR by all-three-seed mean across the two declared LRs; never choose the best
seed as expected quality or drop failed/missing seeds from the denominator.

## Remaining implementation and execution gates

The v2 original-roster reviewer and C1 logical tests are prepared. A full C1 audit
still needs an adapter that reads actual C1 artifacts, verifies all file/tensor
and source identities, joins global epoch journals, applies the logical checks,
recomputes selected logits, and derives the 42 combined candidate chains while
charging every phase. It must also reconcile all original launch/continuation
idempotency keys and final controller records. Production C1 results have not
been reviewed by this package. Do not rename a logical fixture pass into a
completed fresh42+C1 audit.

The tests cover missing/tampered retained evidence, selected-best linkage,
shortened outer ceilings, parent startup cost, inherited plateau/stale counts,
strict improvements/ties, failed inherited diagnostics, optimizer counter resets,
RNG sample order, duplicate/noneligible parents and CPU scope. Their evidence is
about the reviewer checks. They do not train or numerically qualify an HCSN model.
