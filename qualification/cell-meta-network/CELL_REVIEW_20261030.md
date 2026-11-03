# Cell continuation review: measured progress and activation limits

**Final status update:** the later native bilingual parity, ten-case actual
owner, independent Semantic/Skill maintenance and 19-test federation/final-use
gates have passed. The matched warm locality control also completed, without
establishing a reliable distributed advantage. See the
[final qualification result](CELL_QUALIFICATION_RESULT_20261030.md) and
[locality result](LOCALITY_REBOUND_RESULT_20261030.md). The text below preserves
the earlier review snapshot and its then-pending gates; it is not the final
status ledger. No model tuning or additional held experiment followed it.

This review covers the cell candidate based on
`ca77c10b25cf6eb1de91537c938a2beba597c886`. It records the completed P1 language
and P2 budget results, the preserved limitations of the first P3 experiment,
and the qualification gates still outstanding at this review snapshot. Later
native or physical-node receipts must be added explicitly; definitions of tests,
successful compilation, and an evaluator's zero exit code do not substitute for
their required assertions. No additional training follows these results.

## Decisions supported by the evidence

1. Keep cells as logical parameter, memory and routing units within shared
   runtimes. A cell split does not require an OS process, encoder, GPU model,
   database or agent harness copy. Independent model validity is useful even
   when publication and execution retain a common owner.
2. Retain the pinned bilingual candidate for the remaining native/owner gates.
   It fixed known-request coverage within the declared finite grammar in the
   frozen Python comparison. It is not evidence of open-domain Chinese routing.
3. Keep automatic split and prune disabled. In the fixed equal-budget study,
   splitting underperformed rank increase and fixed experts, while pruning
   substantially damaged retained behavior. Positive local task-value credit
   did not predict the best whole-system held result.
4. Keep physical distribution conditional on measured task size or data
   locality. The first source-integrity A/B comparison confounded host placement
   with worker concurrency. A separate two-worker-per-arm warm control is
   required before attributing a difference to physical distribution.

These decisions preserve the existing owner and final-use validation. They do
not admit autonomous creation of execution authority, publication rights, or
general-purpose agents from a local training result.

## P1: bounded addressing and frozen bilingual learning

The v2 route artifact declares exact Unicode aliases and supported whole-query
templates. It refuses unknown full names, ambiguous captures, conflicting
routes and extra capabilities. The original query still reaches the original
pinned encoder; the learned head must independently agree with the declared
operation and pass its calibrated confidence/margin gate. Neither a substring
match nor an alias can grant a tool or effect.

The first unchanged-head baseline exposed a concrete gap: only 73 of 120 known
requests were accepted correctly, including 21/48 Chinese and 52/72 English.
All 360 unknown requests abstained. The next experiment explicitly reused the
120 known cases as historical training replay. That original 480-case collection
is preserved, but is no longer candidate generalization evidence. Its 360
unknown cases did not train the head or calibrate admission thresholds.

The continuation froze train/development/held data and a finite development
calibration grid before training. The new held set was opened only after the
candidate was sealed. Both old and new heads used the same expanded 51-template
grammar and one encoding of the same new held rows. The expanded old baseline
retained old weights and thresholds; it is distinct from the original 480-case
baseline.

| New held outcome | Expanded old head | Frozen candidate |
|---|---:|---:|
| Known requests correct | 77/96 | 96/96 |
| Chinese known requests correct | 29/48 | 48/48 |
| English known requests correct | 48/48 | 48/48 |
| Unknown requests correctly abstained | 304/304 | 304/304 |
| All rows correct | 381/400 | 400/400 |

The nineteen improvements are within the Chinese known group; there were no
known regressions. All unknown examples meet bounded grammar rejection rules,
so their zero false accepts cannot independently be credited to the learned
head. The main new evidence is improved learned-head coverage inside supported
language templates. New texts and base wording families are separated across
train/development/held. Boundary perturbation operators and their family label
are shared; the frozen `template_families_disjoint` flag must not be interpreted
as every literal family label or unknown perturbation type being novel.

The actual run used 27.100725 child CPU seconds and 27.222928 outer wall seconds,
with cumulative child peak RSS 641,172 KiB. This is encoder/training/evaluation
process memory, not the footprint of one cell. Python CPU timers are budget
detection, not an OS-enforced hard CPU limit during C-extension execution.
Original baseline work, historical encoder creation and Runtime launch remain
separate cost windows. See [the bilingual result](../memory-cell-adapters/BILINGUAL_RESULT_20261030.md)
for stage costs, artifacts and protocol boundaries.

Frozen identities:

- Runtime job: `1a18bbe608b-96a-4640`.
- Run root: `/tmp/hepta-cell-bilingual-continuation-20261030-01`.
- Protocol SHA256: `21c109a75b1c98f52fcc567e1f59a5cad56300c95e754007e09bc6cec1165d24`.
- Model SHA256: `5b6bec4e6f13958d3572bee68b03977fbc7064fac4be47959f1b7f0b1ecc8522`.

The Python gate has passed. Native f32/live-encoder parity and actual-owner
qualification require their own measured reports. Native evaluation must show
400/400 head parity, 400/400 live parity, all expected groups correct, zero
unknown accepts and one encoder start. The owner fixture must exercise the ten
declared v2 cases through signed release selection and canonical reads. Such
fixtures still do not prove a deployed production service.

## P2: independent source validity and structural credit

The v2 inventory bundle records the complete training-source cut separately for
the Semantic and Skill models. A change or withdrawal of any source used by one
model invalidates that whole model, including queries to an unchanged address.
The other model may remain valid when its complete dependency set is unchanged.
Composition requires both. Exact Event and Hold values remain owner reads.
Legacy v1 bundles retain their full combined-source validation.

This is independent training and validity within one coherent selected bundle.
Publication still verifies both lineages. Reusing unchanged model bytes avoids
unrelated training; it does not create another publication owner. Query binding,
release selection and acquired owner-cut revalidation remain enforced. Release
and store revalidation across an await are not a cross-store atomic effect
authorization token; any actual effect still belongs to its final action owner.

The nineteen inventory unit tests passed earlier in this candidate. The real
ignored two-kind correction/retraining/publication/withdrawal cycle is a separate
gate: its code exists, but it must not be described as completed before its
actual receipt. The broader crate suite initially returned 559 passes and two
failures out of 561. One lacked the explicit built Codex App Server test-binary
environment; the other returned zero completed peers in the 16-peer truncation
fixture. Those exact failures are being rerun separately. A diagnostic-only
assertion reports coverage without changing the production two-second budget
or removing any expected result.

The structure study used the existing shared Python runtime and frozen feature
vectors, two fixed seeds and a 12 CPU-second ceiling per candidate/seed, with
common setup allocated into each allowance. All eight runs completed and met
the measured budget; no candidate was rerun or tuned after held evaluation.

| Structure | Held correct | Never-updated entities correct | Charged CPU, two seeds |
|---|---:|---:|---:|
| Dynamic split | 355/384 | 230/240 | 22.218990 s |
| Fixed experts | 368/384 | 236/240 | 22.198996 s |
| Rank increase | 377/384 | 238/240 | 22.158891 s |
| Pruning | 120/384 | 69/240 | 22.154637 s |

All structures shared the same parameter upper bound. Pruning intentionally
retained fewer actual parameters, and the common CPU ceiling allowed different
sample exposure. Therefore the experiment does not claim equal actual pruning
capacity or equal training presentations. Rank increase was best in this finite
configuration; two seeds and reused expressions do not establish universal
superiority or statistical significance.

Dynamic split reached task utility 1.0 on every training-prefix phase and all
twelve adapter-update conditional credits were positive, yet finished 22 held
answers behind rank increase. A useful local update can still be a worse global
structural choice. Pruning's immediate phase-one utility collapse and negative
phase-two update credit in one seed further justify keeping candidate rejection.
These counterfactual ablations hold other final components fixed. They measure
conditional task value, not additive credit, randomized causal effects, or a
globally optimal topology.

The process cost was 88.731515 CPU seconds and 89.099801 wall seconds, with
306,712 KiB peak RSS. The 3.306532 CPU-second setup and measured coordinator
overhead are already allocated into arm totals. Historical parent/encoder work
and external process/transport costs remain excluded, so `full_cost_exact=false`.
See [the complete budget result](BUDGET_RESULT_20261030.md).

Result identity:

- Runtime job: `1a18b89dd54-96a-45ae`.
- Run root: `/tmp/hepta-cell-budget-20261030-01`.
- Original `RESULT.json`: 119,865 bytes.
- Original result SHA256: `919e1f1bc1745f9e945e48de9b5a5fca72258195abfc963861e80225abdebb46`.

The local review copy has an extra trailing newline. Hash the original remote
bytes when checking the identity above; do not replace its digest with the
review copy's file digest.

## P3: first-round limits and the separate matched control

P3 audits actual immutable source shards. The x230 shard came from the node's
preexisting `source-r5b` directory, rather than data uploaded from main and then
mislabelled local. That directory is not a Git repository, so its frozen identity
is a content manifest/tree digest with no invented source commit. The main shard
uses its actual fixed Git source identity. The mixed manifest versions retain
their distinct identity contracts.

`AuditShard` performs bounded file reads, hashing and source-summary work. The
native memory model is loaded by the worker but is not invoked by this action.
This is a useful data-locality subtask, not an inference-speed or distributed
learning benchmark. Its observations cannot establish spontaneous emergence of
an agent, a learned meta-network, or general intelligence.

The first A/B completed, but its local arm used one worker serially for two
shards, while the distributed arm used two workers concurrently. Preserve those
results under that precise comparison. Do not attribute a performance difference
to physical host placement alone. No new P3 performance number is inserted into
this review before the matched control's actual result arrives.

The old worker jobs later timed out. Their original Runtime terminal receipts
and complete direct-child lifecycle receipts remain retained. The next control
uses two replacement workers and an additional main worker, all with fresh job
bindings and the original binary/model/shards. It does not reuse dead ports or
claim same-process continuity. It references the already completed central
transfer and filled central root without repeating that transfer.

Both arms perform two concurrent audits in a fixed 16-trial counterbalanced
schedule. New worker startup, proof preparation/transport, warmups, RPC transport,
task time and terminal resources have separate scopes. OS caches are uncontrolled;
all three workers remain resident. This is a warm task comparison with matched
worker count, not a complete cold deployment-cost comparison. Preserve all old
and new costs, including failed setup and time spent awaiting tools, without
charging the same cumulative resource receipt twice. The new protocol and exact
proof contract are in [the rebinding control](LOCALITY_REBIND_CONTROL.md).

## What would change the activation decision

A structural candidate needs a whole-task retention/generalization improvement
under an explicit total budget, not just positive local credit. A distributed
candidate needs useful work or actual data locality sufficient to offset its
measured setup and transport, plus a fair parallel local baseline. A language
candidate needs implementation parity and the unchanged owner/source/final-use
gates, even after a good finite-language held result.

The present candidate supplies concrete components and measurable rejection
criteria for that process. It does not yet demonstrate an indefinitely growing
cell network, autonomous topology improvement, or a general-purpose native agent
replacing the entire Codex execution contract.
