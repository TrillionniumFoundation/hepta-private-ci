# One bounded source-correction learning loop

**Engineering closure passed; candidate adoption and scientific net benefit did not qualify.**
This directory records one real native V13 training attempt, ten fresh worker
interpreters, full checkpoint verification, cold task execution, rejection and
source-freshness fencing. It uses the existing research `SourceOwner`; it adds no
second owner implementation and changes no Rust/native authority contract.

## Observed result

| Check | Observed result |
| --- | --- |
| Original parent | Exact provenance skills artifact, step 240; 250,077 bytes |
| Parent closure | #4930 default `reference`, non-synthetic; weights, optimizer, RNG, sampler and training cursor verified |
| Actual MiniLM replay | 120 archived training inputs reencoded; maximum absolute feature difference 0 |
| Only training attempt | 16 updates, step 240 → 256; 288 presentations over 124 rows (120 retained + 4 authored feedback queries) |
| Candidate checkpoint | 250,625 bytes; full source/data/encoder/optimizer/RNG/sampler closure verified in another process |
| Historical typed-output retention | Parent 59/72; candidate 55/72: five regressions and one gain |
| Two authored held correction requests | Parent 0/2; candidate 2/2 |
| Candidate cold next task | Unpublished shadow `sort_numeric` returned `["-2", "0", "3", "3", "12"]` correctly |
| Publication | Original `SourceOwner.publish` executable validator rejected the candidate; parent release/epoch remained unchanged at 1 |
| Active parent cold next task | `unique_stable` returned `["learn", "verify", "serve"]` correctly |
| Dependency revision | After `skills` revision 1 → 2, cold `SourceOwner.read` refused the stale release before prediction |
| Historical preservation | Parent checkpoint/manifest bytes and complete state remained identical; historical #4930 closure still verifies |

No retry, follow-up training, hyperparameter search or post-evaluation schedule
change occurred. Optimizer updates and learned parameters changed through the
original Adapter implementation. On the new dataset, its documented
`allow_data_change=True` path resets the sampler from the inherited RNG; the
entry parameters, Adam state, RNG and old sampler are recorded exactly.

## What the two source revisions mean

The protocol and literal task goldens were frozen before training. The first
event changes the constructed **Cedar intake** feedback source from revision 1
(`unique_stable`) to revision 2 (`sort_numeric`, preserving duplicates). The
candidate trains on a real native snapshot containing original `skills` revision
1 and Cedar revision 2. Cedar query text, source bodies, operation labels and
typed output goldens are reviewable in `inputs/` and the phase receipts.

The parent had never learned either Cedar revision. This is evidence of learning
an authored mapping from a corrected source, **not** proof that an already learned
wrong Cedar belief was unlearned. The held requests are authored engineering
fixtures, not independent natural future sources. The old 72 cases are historical
retention observations, not another independent replication.

The second event occurs only after the rejected candidate and successful parent
next request. It revises the parent's real `skills` dependency, without changing
labels, specifically to test stale-source fencing. This provenance-only revision
does not claim knowledge improvement. Historical content remains recoverable,
while the live owner correctly refuses stale service. No stale parent output is
used after this fence.

## Authority and evaluation boundaries

Every #4930 receipt remains `DENY_ALL`: content closure does not grant publication
or live-source freshness. Evaluation is a separate interpreter after training;
both heads share one actual encoding call and inference sees features only.
`tasks.py` executes the selected operation on the public payload and compares
canonical typed outputs against separately frozen literal goldens.

The callback's `passed=False` is fixed in advance because an independent nine-arm
future round is absent and complete lifecycle cost remains unknown. It exercises
the real SourceOwner refusal/rollback path. **The observed 59 → 55 retention loss
is descriptive additional evidence, not the causal trigger of this executed
gate.** This run does not test a dynamic quality threshold or positive adoption
of a newly trained candidate. The only successful publication restores the exact
historical parent. The V15 `FutureAdoptionGate` itself is neither invoked nor
weakened here. The active next-task run uses the unchanged parent. Candidate
next-task use is explicitly an unpublished shadow run. `GATE_AUDIT.json` records
this boundary against the frozen callback and actual receipts.

## Runtime and cost evidence

The complete two driver invocations consumed **7.730896 CPU-seconds** and a summed
**7.792046 wall-seconds**. Linux `wait4` includes driver startup, preparation,
all ten lifecycle workers, and finalization. The complete parent-only CPU portion
was **0.273554 seconds**; peak measured process RSS was **212,811,776 bytes**.
Per-phase user/system CPU, wall time and RSS are in `RESULTS.json`; raw stdout and
stderr are retained for every worker. PIDs can repeat between executor namespaces;
the receipts contain ten distinct process-instance identities.

The wrapper regression independently exercised a failed engineering result with
exit code 0, retained its failed cost aggregate, and proved `--resume` cannot
silently skip it. It performed no model load or training. Its measured interval
is recorded separately in `validation/regression.json`. There were zero failed
real lifecycle workers and zero failed physical training attempts in this run.

Energy, actual bills, historical acquisition, full storage byte-seconds, host
network bytes, p99 latency, development/review and delivery-reporting cost remain
unknown or excluded, explicitly `null` in the delivery report. They are not
zero-priced measurements; no full-cost superiority is claimed.

## Evidence and fixed inputs

- `RESULTS.json`: consolidated outcomes, identities, per-phase cost and limits.
- `evidence/run-20261106-001/PROTOCOL.json`: frozen schedule, source-event order, runtime and scope.
- `evidence/run-20261106-001/INVENTORY.json` and `LOCK.json`: exact source/input byte identities.
- `evidence/run-20261106-001/EXECUTED_SOURCE/`: captured driver/native/validator package; bundled test sources are archived dependencies, not claimed executed by the learning run.
- `evidence/run-20261106-001/phase_results/`: ten raw phase receipts, including three default-reference content closures.
- `evidence/run-20261106-001/owner/`: the one native SourceOwner database and complete original/candidate artifacts.
- `measurements/`: complete-process `wait4` receipts and orchestration logs.

The original four native modules are the exact #4930 reference bytes from commit
`aeedeee98a5f7472f11b88ef7b869fc5a6d3d8e1`. Source inputs come from donor commit
`0abc3f5132c944d517e6a75d6d5362819fd285ec`. All dependencies, including the copied
validator, are fixed by the inventory. Original step97 metadata is not modified
or used to manufacture a source-cut binding.

The runtime was Python 3.12.14, NumPy 2.3.5, ONNX Runtime 1.23.2 and tokenizers
0.21.4. It used the existing read-only MiniLM assets at
`/workspace/scratch/40d04650905b/v13-work/minilm`. The recorded source snapshot is
not a portable copy of these 90 MB encoder weights; their complete pinned file
manifest is included and both the runtime and validator rehash them.

No evidence blob exceeds the repository's 512,000-byte bound; the largest is the
250,625-byte candidate checkpoint. No checkpoint state was dropped or truncated.
This completed run is archival. The `--resume` path is for its recorded preflight
handoff; it is not an instruction to launch another training attempt.

## Receipt verification after the archived run

The current driver adds `receipt_verifier.py` to its frozen execution-source
check. A completed phase is reusable only when the parent observed an exact
integer zero exit code and its protocol, raw stdout/stderr byte hashes, complete
worker result and process-instance identity agree. Canonical JSON comparison
keeps booleans distinct from integers; ambiguous or non-finite JSON is rejected.
Final phase accounting uses the same verifier as resume. A failed result,
unverified receipt, orphan attempt or unresolved training marker never requests
an implicit retry. Failed attempts retain their captured output and measured
cost; unavailable or invalid parent measurements remain unknown in the failure
aggregate.

These checks detect inconsistent local evidence. They neither authenticate an
independent writer nor restore model state or grant publication authority. They
also do not turn the earlier Memory candidate into a positive adoption result.
The archived `EXECUTED_SOURCE`, manifests, receipts and results are unchanged.
The changed driver cannot resume that older frozen source identity. Any future
model run still needs its own frozen protocol and training budget.

Run the subprocess and recovery regressions without loading a model:

```sh
cd qualification/cell-learning-loop-v1
python3 -B -m unittest -v loop_tests
```

## Unsettled attempts remain part of the cost inventory

The driver reconciles all original attempt directories and the training marker
before dispatch and during final reporting, including phases beyond an early
stop. Missing or linked results and attempts outside the frozen schedule prevent
further dispatch. Their unmeasured CPU, wall time and RSS remain unknown rather
than disappearing from an empty sum. Existing failed measurements remain
available in their original receipts. See
`attempt_inventory_validation_20261106/` for the five original counterexamples,
18 passing recovery tests and exact source/log bindings.

Run the combined recovery and attempt-accounting regressions with:

```sh
python3 -B -m unittest -v loop_tests test_attempt_accounting
```
