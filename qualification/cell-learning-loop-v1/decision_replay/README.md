# Separate post-run decision replay

**The data-dependent engineering quality veto was exercised successfully. No
optimizer update or positive new-candidate adoption occurred.**

This replay was frozen at `2026-11-06T07:59:38.043344+00:00`, after the original
results were known. It is a separate engineering check, not part of the original
pretraining freeze or a prospective efficacy trial. All original delivery files,
the original delivery inventory itself, the original six Python sources and the
original owner remained byte-identical.

## Predicate and actual execution

The reusable `quality.assess` predicate requires:

1. Exact checkpoint/manifest bytes and actual loaded complete state, encoder and
   source identities matching the frozen bindings.
2. The complete frozen case roster and typed outputs matching fresh real
   inference and execution, with strictly typed counts and exit status.
3. More correct corrected-task outputs than the parent, with no loss in the
   aggregate historical correct-output count.

The replay verifies both original artifacts through #4930 default `reference`
mode, reconstructs their frozen sources in an explicitly separate research
SourceOwner fork, and performs actual MiniLM encoding of all 74 evaluation texts
in one shared call. Both private heads and the fixed `tasks.py` executor rerun.
Their complete typed results match the original frozen evaluation receipt.
Self-reported scores or self-reported state hashes cannot substitute for these
checks.

| Measurement | Parent | Candidate | Predicate result |
| --- | ---: | ---: | --- |
| Corrected authored tasks | 0/2 | 2/2 | Improvement condition passes |
| Historical typed-output tasks | 59/72 | 55/72 | Retention condition fails |

The resulting dynamic quality veto is **`historical_retention_loss`**. Five
historical outputs regress and one improves, for a net loss of four. This is an
aggregate engineering threshold, not a confidence bound or proof that every
individual historical task is preserved.

The predicate executes inside the real `SourceOwner.publish` callback. The owner
rejects the candidate and leaves the fork's parent release and epoch 1 unchanged.
A separate cold worker reloads that persisted release and correctly returns
`["learn", "verify", "serve"]` for the frozen next request. Parent and candidate
complete states remain identical to their input artifacts.

## Eligibility does not grant publication authority

Quality eligibility is separate from authorization. This replay's formal gate
is permanently `HOLD_NO_REGISTERED_NINE_ARM_ROUND`; its complete-cost gate is
`HOLD_COMPLETE_COST_UNKNOWN`. Neither accepts a caller Boolean that can grant
authority. The retention loss is therefore an **additional dynamic veto**, not
the sole causal reason that publication was refused.

The V15 nine-arm authority is not invoked or weakened. There is no successful new
candidate adoption, synthetic success, additional optimizer update or added
training presentation. Across the original run and this replay, the physical
training total remains one candidate, 16 updates and 288 presentations.

The cold availability check applies only to the explicitly reconstructed fork at
the historical frozen cut. It does not rewind the original owner's source
frontier. The original owner remains untouched and fenced after its `skills`
revision; this replay grants no authority to serve through that stale release.

## Concrete negative probes

All four probes were rejected using the actual loaded models and inputs:

- A forged candidate aggregate of 59 historical successes disagreed with 55 real outputs.
- Replacing a typed `correct` Boolean with integer `0` or `1` changed the canonical typed output.
- Substituting the actual parent head into the candidate slot violated the content/state binding.
- A Boolean `False` exit code failed the strict integer exit-code check.

No probe trained a model or fabricated a successful candidate. Their execution
cost is included in the decision worker.

## Cost and evidence

The complete replay driver and two waited workers used **3.099507 CPU-seconds**
and **3.140813905 wall-seconds**. Full driver-only CPU was **0.124869 seconds**.
The maximum measured single-process RSS was **213,028,864 bytes**; this is not the
simultaneous resident-memory peak of the process tree. There were zero failed
real worker attempts. The outer Linux `wait4` envelope includes startup,
preparation, worker execution and finalization.

Original run plus replay measured runtime is **10.830403 CPU-seconds**, with
**10.932860110 summed invocation wall-seconds**. This does not fill unknown energy,
bills, historical acquisition, full storage byte-seconds, host network traffic,
p99 or development/review/reporting cost. Complete-cost qualification remains
false.

- `RESULTS.json`: consolidated decision, exact source/artifact identities, probes and costs.
- `evidence/replay-20261106-001/PROTOCOL.json`: explicit post-run freeze and quality/authority rules.
- `evidence/replay-20261106-001/INVENTORY.json`: exact frozen source and input bytes.
- `evidence/replay-20261106-001/decision.json`: actual callback, both content closures and all fresh typed outputs.
- `evidence/replay-20261106-001/cold_check.json`: persisted parent and unchanged-state checks.
- `evidence/replay-20261106-001/fork-owner/`: reconstructed research owner and unchanged complete artifacts.
- `measurements/FULL_PROCESS.json`: complete-process accounting.

The three new implementation files total **339 lines**. Original helper and
validator sources are copied byte-for-byte into the frozen dependency closure.
No original evidence or implementation file was edited to incorporate this
post-run result.

## Subsequent phase-process repair (2026-11-06)

The historical statements and measurements above describe the frozen original
replay. Its `EXECUTED_SOURCE`, manifests, results, artifacts and owner remain
unchanged. Subsequent driver source now freezes a 60-second wall limit per
worker phase and a separate five-second termination-observation limit. The
original CPU limit alone could not bound a worker waiting on I/O.

The driver starts each direct child in a new process group, records the phase
before dispatch, and polls only its own child with `wait4`. At the wall limit
it requests termination of that owned group. A late observed successful exit
still fails the deadline. Reaping the direct child preserves its actual exit
status and measured CPU; missing wait results preserve unknown CPU and RSS.
Failure to signal, wait or synchronize the log is a failed observation, not
permission to start the next phase. A lost wait owner is never followed by a
signal to a possibly reused PID. These observations do not prove that every
detached descendant terminated.

The outer `measure.py` driver still uses a blocking `wait4`, and preparation
and filesystem I/O have no new whole-driver hard deadline. The new bounds apply
to the worker-phase wait and its termination observation. Historical replay
quality and authorization predicates are unchanged; no model was loaded or
replayed to qualify this source change.

Run the no-model behavior tests from this directory:

```bash
python3 -B -m unittest -v test_phase_process test_replay_dispatch
```
