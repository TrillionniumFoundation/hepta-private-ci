# E4 completed execution: no observed Circuit gain

The corrected frozen candidate completed 162 graph executions and 306 actual
model calls. The final reader accepted every required receipt and produced
`COMPLETE`, with no issues or failures. This is an execution and evidence result:
**the learned Circuit did not improve selected task success over FF, and every
arm scored 0/3 on old B.** The output selection rule retained earlier successful
answers while many second calls failed.

These are fresh interactions with the nine retained, previously exposed
development tasks (old A6 and old B3). New independent tasks, sources, teachers,
and users remain zero. F, T and C are three old Run02 adapters on the same base,
not the subsequently trained E2 adapters or independent teacher identities.
Scientific qualification, native Cell/HIA execution, owner adoption, FinalUse and
settlement eligibility are not established by this run.

## Candidate and execution identity

The pre-execution protocol is
`f4111d887c9827156da1f6c4a6859cb3d9cef02b1c54a90f3af47004a036c7c1`,
published in [#6684](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6684).
The original failed protocol `951c24b5…` remains preserved as a separate attempt.

| Executed component | Commit provenance | Actual file SHA256 |
| --- | --- | --- |
| Additional controls | `eb8f760d75a3e9ca5a1659045828925ef38280ad` | `6626583e85d2dfd9837da58560a2d5d7fca7769ce9ea758dddc3978aa690cd02` |
| Owned worker | Original file in corrected protocol PR | `9bbfd3cedefa3c897ca5ff44dd8806a644de541b3df7b088b9830be59c79c11a` |
| Exact adapter loader | `44da00130750844c27887c019a99c1c3a9eced69` | `110b33222dc620ce5fb61b1e4ff9fb4b4e5f7bb03ee25a4c9c726e99f7476d3c` |
| Final standalone reader | `7606036c3b01346dd058d6c658257b28cdded37a` | `a37bcd22f31f4ce9b31b798cb4efad70dc90fa427db23c976955777a9711a316` |

The actual class is
`cell_experiments.online_v4.e4_fixed_pool.SharedAdapterPool`.
`POOL_BINDING.json`, `POOL.json`, `WORKER_INTENT.json` and the protocol agree.
All original training-after parameter hashes passed pool construction and
subsequent activations. The base stayed BF16; adapters retained their exact
saved FP32 bytes. The former BF16 roundtrip failure, two numerical diagnoses and
CPU regression receipts are retained in the archive, not overwritten.

Original B source inventory `928aaa75…` and comparison `8424c071…` remain
predecessor references, not an assertion that the old numerical gate covered
the new loader. The corrected protocol separately binds the repaired source
and CPU admission evidence. All post-run source, runtime and model checks passed.

The real child was waited on and returned 0. Its owner PTY also exited 0 with
complete output; both original receipts are in the readout archive. The owner
wait took 2,122.537549 seconds; the nested worker after admission took
2,059.222877 seconds. GPU ownership was released before the final readout.

## Task results

Selected success uses the frozen rule
`earliest_business_success_else_last_surviving`. The first and last columns
show the two actual attempts, so selection cannot hide a regression.

| Arm | A selected /6 | A first | A last | A 0→1 | A 1→0 | B selected /3 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| FF with answer and feedback | 5 | 5 | 0 | 0 | 5 | 0 |
| Learned sparse Circuit | 5 | 5 | 0 | 0 | 5 | 0 |
| Fixed TF with answer and feedback | 4 | 4 | 0 | 0 | 4 | 0 |
| TT with answer and feedback | 4 | 4 | 2 | 0 | 2 | 0 |
| CC with answer and feedback | 1 | 1 | 1 | 0 | 0 | 0 |
| Task-bound random graph | 4 | 4 | 1 | 0 | 3 | 0 |
| A-selected static FF | 5 | 5 | 0 | 0 | 5 | 0 |
| Replace non-F slots by F | 5 | 5 | 0 | 0 | 5 | 0 |
| Legacy panel-wide random TF without messages | 5 | 4 | 5 | 1 | 0 | 0 |

All B first and last success counts are also zero. The one A recovery in the
legacy TF-without-messages arm is an uncommunicated fallback and does not beat FF.
That legacy random arm chooses one graph for the whole panel. The additional
random control instead binds its draw to the frozen seed and task identity.

Every main arm above used two fresh calls and two verifier opportunities per
task. The same input/output caps and output selection rule apply. TT and CC
supply stronger single-adapter self-repair controls; they were not additional
router candidates. Search considered the original six graphs on A only. FF,
TF-feedback and TF-none tied at five A successes; the predeclared lexical
tie-break selected FF. No B result was used to choose the static winner.

## Message and Cell interventions

| Learned-Circuit intervention | A selected /6 | A last | A effective /6 | A calls | B selected /3 | B effective /3 | B calls |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Remove answer edge | 5 | 4 | 5 | 12 | 0 | 3 | 6 |
| Remove feedback edge | 5 | 1 | 6 | 12 | 0 | 3 | 6 |
| Remove C | 5 | 0 | 0 | 12 | 0 | 0 | 6 |
| Remove T | 5 | 1 | 1 | 11 | 0 | 0 | 6 |
| Remove F | 1 | 1 | 6 | 1 | 0 | 3 | 0 |

The learned router used TF-feedback for A-counter, FF for the other five A
tasks, and FF for every B task. Thus removing C was ineffective throughout;
removing T affected only one A task. Removing F removed all calls in five A
tasks and every B task, so it is a resource-removal diagnostic, not a matched
budget demonstration of Cell necessity.

The separate identity-replacement control retained two paid calls. It was a
no-op for five A tasks and all three B tasks, and matched learned selected
success on every task. Its unchanged cases are explicitly counted in the
readout.

A read-only paired audit further checked all six A learned versus remove-answer
pairs. The five effective pairs have identical task, route, contract, first
request bytes, first answer bytes, output token IDs, feedback, model parameter
hashes and generation settings. Their second requests differ only by the
`answer` field in the tool-message JSON. Removing that field changes the final
attempt from failure to success on A-mse, A-readout-score, A-clipped-metrics and
A-pair-map; A-colon-repair fails on both sides. A-counter has no answer edge and
is the explicit sixth no-op.

This supports a narrow conclusion: the current answer relay harms the second
attempt on those four retained tasks. Selected success still remains 5/6. It
does not establish a general communication effect or a benefit on independent
tasks. The audit program, all input receipt hashes and its successful execution
are in `e4-offline-audit.tar.gz`.

## Complete observed cost, with explicit unknowns

| Scope | Graphs | Model calls | Verifier opportunities |
| --- | ---: | ---: | ---: |
| A-only search | 36 | 72 | 72 |
| Original arms and legacy interventions | 81 | 144 | 144 |
| Additional controls | 45 | 90 | 90 |
| Total | 162 | 306 | 306 |

The 306 calls used 110,751 input tokens and 26,330 output tokens.
147 reached actual repository business execution; 159 were rejected at format
admission. Both classes retain their original verifier receipts. FF results
reused for the comparison are not charged a second time.

The caps were 4,096 input tokens, 384 output tokens and 2,048 relay bytes per
call/relay as specified in the contract. Actual token use differs by arm, so
this is equal opportunity and equal caps, not equal realized cost. The learned
router additionally paid for the 72-call A search; that fitting cost is not
free or assigned to the fixed predeclared FF baseline.

One shared pool loaded the base once and three adapters, taking 55.188998
seconds. Search took 417.813175 seconds, including 0.021133 seconds for the
router fit. The graph-wall sum is 1,943.837531 seconds; nested provider time is
1,903.905449 seconds and nested verifier time is 27.389000 seconds. These scopes,
pool initialization, route validation, inner worker and owner wait overlap:
**do not add them together**.

The failed prior owner took 110.117431 seconds, including its nested
50.508930-second worker. Separate tensor diagnoses took 24.581579 and
22.870047 seconds; the CPU precision regression took 13.897277 seconds.
These are separately attributed historical work, not extra successful graph
calls. Full runtime restoration, historical training, monetary cost, energy
and GPU active time are not fully measured. Monetary cost, energy and GPU
active time remain null; `full_system_cost_known` and
`actual_cost_matching_claim` remain false.

## Original evidence and offline replay

| Archive | Bytes | Regular files | SHA256 |
| --- | ---: | ---: | --- |
| `e4-originals.tar.gz` | 2,576,143 | 3,035 | `7e0a67d8c4cdfadbebf195591bbe30cce2e6ed9b524c46c6011b0cadcb8f3a32` |
| `e4-readout-originals.tar.gz` | 208,335 | 19 | `04b05b0762f928734903287b8dd3c0bdef78743d4cd4af471945c19337a7c837` |
| `e4-offline-audit.tar.gz` | 10,366 | 6 | `3932ebcf47fdd46391d360e12b41690e122d5bfe00015be4f9e8a768c5a4fcd6` |

The first archive contains the complete run, exact inference source, task
inputs, predecessor source/closure, manifests, training receipts, admission,
owner receipts and the pinned prior failure/diagnosis evidence. It contains no
model weights. The second contains the final reader, its tests/format evidence,
the actual readout process receipts, the complete 1,054,217-byte `READOUT.json`,
the original summary and owner completion evidence.

The final reader audited 2,787 original JSON files. All eight per-call artifact
families have 306 unique call directories with exact one-to-one coverage.
It checks candidate identity, completion, task and graph coverage, slot and Cell
order, token caps, request/output/STEP equivalence, and the derived first-success
selection including final slot and answer hash. Partial evidence is not
converted to successful zero totals.

The downloaded archives were checked by full SHA256 and Git blob identity.
Pure-stdlib offline replay exited 0 and reproduced the original readout
**byte for byte**, SHA256
`8599d61793f97da236afb53aab382eba9b0a072752705c053aca8264977c3a94`.
`REPLAY_RECEIPT.json` records that execution. `RESULTS.json` is a compact derived
view of the archived summary, retaining every arm, transition and actual token
total. `ARCHIVES.json` records archive membership and hashes.

From this directory, with Python 3 and a fresh output directory:

```sh
mkdir e4-replay
tar -xzf e4-originals.tar.gz -C e4-replay
tar -xzf e4-readout-originals.tar.gz -C e4-replay
python -I -B e4-replay/e4-controls-readout-20261118-392934-c/readout_extended_circuit.py \
  --run-root e4-replay/research-e4-controls-20261118-392934-b \
  --protocol e4-replay/e4-controls-source-20261118-392934-b/PROTOCOL.json \
  --protocol-sha f4111d887c9827156da1f6c4a6859cb3d9cef02b1c54a90f3af47004a036c7c1 \
  --output e4-replay/REPLAY_READOUT.json
cmp e4-replay/e4-controls-readout-20261118-392934-c/READOUT.json e4-replay/REPLAY_READOUT.json
```

Replay loads no model, runs no verifier, performs no network calls and changes
no original evidence. It checks the recorded run rather than creating new
research observations. The required remaining scientific work is still real
independent tasks and sources, new complementary teachers where authorized,
and retrieval controls: this run gave every arm zero retrieval opportunities.

