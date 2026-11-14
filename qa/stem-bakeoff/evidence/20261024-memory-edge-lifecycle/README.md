# Actual cell-to-cell dispatch and topology lifecycle: negative development result

The fixed experiment completed: 1,024 decoder optimizer updates, 400 router
updates and 75 actual decoder reads. Learned next-cell routing scored 1/6,
direct parameter access 2/6 and exact source lookup 6/6. This establishes bounded
execution plumbing and preserved negative results. It does not establish a
learned-edge quality advantage, autonomous growth or general memory.

## Exact protocol and source

| Item | Identity |
|---|---|
| Baseline | `429894ac8e0818102cfdea4ad47a56e4583b2902` |
| Executed capsule | `edge-source-002` |
| Source identity, canonical SHA-256 | `64b5d1492be5e282f13c3a995467b81a5cbc214561c38183c1a1cf16ef244a5c` |
| Protocol, canonical SHA-256 | `65bcc00cc281c1d586d1ad904efee06b48d9170cd48d5f16983cc7c040adca21` |
| Protocol file SHA-256 | `14555058109e538ce9cd18f871ba39e6105f5f89395fa9c587de5330aa7107d4` |
| Actual random tiny-base inventory identity | `3e1548b308b01716ef79a1740d1bb490fefb8bd825b5735c2ceafb60786fab3e` |

Source-001 remains unexecuted. Before launch, source-002 added six lines to inherit
the complete decoder and committed-policy ancestry into source utility records,
including ancestors outside a partial query panel. This is a provenance closure
fix, not a scoring or hyperparameter change. The protocol, cases, weights recipe,
budget and final queries were unchanged. All 131 captured baseline/driver/budget
source files match their byte pins, and the before/after source identities match.

The random tiny Llama uses seed 24031, hidden size 16, intermediate size 32, one
layer, two attention heads and context 256. It is not pretrained. The vocabulary
is constructed from registered training/source/final wording and stored values;
there is no claim of unseen-vocabulary generalization. The complete seven-file
tiny base is retained in this archive. Runtime versions and interpreter identity
are recorded; full OS/runtime dependency bytes are not all included.

Three cells (`hint`, `color-a`, `color-b`) receive 256 updates each, with rank 4
and learning rate 0.01. A fourth 256-update fresh replay follows withdrawal.
The source utility panel has two wordings for each of six stored entities.
Final evaluation uses those same six entities under another wording. These are
synthetic repeated entities, with zero independent natural future tasks.

## Actual routing mechanism and final results

For each source query, the first cell really generates its hint. Both candidate
next cells are considered; actual source admission determines whether a decoder
callback occurs, and its exact raw answer determines utility. Ten of the twelve
source rows have utility `[0,0]`; two have `[1,0]`. These are measured outcomes,
not positive/negative wording labels. The existing numerical router performs
400 source-only updates, and its serialized bytes/policy are frozen before any
final outcome. The audit verifies that the saved utility rows match these raw
observations. It does not rerun numerical router predictions.

At inference, the metadata resolver supplies only the typed key, roots and prompt.
The first raw output becomes policy input and literal context in the second
decoder prompt. The next-cell decision is persisted before the second callback.
The raw source/final/rebuild traces account for every actual reader call exactly
once; no precomputed final expert matrix supplies an answer.

| Arm | Exact color answers | Actual decoder callbacks | Observed arm wall time | Final status counts |
|---|---:|---:|---:|---|
| No edges | 0/6 | 6 | 44.346 s | Six stopped |
| Fixed target | 1/6 | 9 | 65.807 s | Three generated, three indeterminate |
| Deterministic random target | 1/6 | 10 | 71.625 s | Four generated, two indeterminate |
| Learned next cell | 1/6 | 7 | 54.595 s | One generated, five stopped |
| Capability metadata route | 1/6 | 12 | 89.961 s | Six generated |
| Direct parameter access | 2/6 | 6 | 46.770 s | Six generated |
| Exact source lookup | 6/6 | 0 | 0.025248 s | Six answered |

All arms use the same three cell checkpoints. The no-edge arm returns the hint
cell's output, while the task asks for a color. Its answer-type asymmetry makes
it a path ablation, not a strong standalone memory baseline. Direct parameter
access and exact source lookup are the principal stronger controls. Wrong-target
admission can reject the second call after the first ran; those attempts remain
`indeterminate` and are included in the six-case denominator. Learned routing
stops five times and invokes one next cell. Its fewer callbacks do not establish
superiority over the stronger controls or excuse the added fitting cost.

The arm wall intervals include edge publication, execution, receipt writes and
scoring; their terminal score-file write is excluded. The exact-source arm is
not zero-time: its observed interval is 25,247,824 ns wall and 14,225,000 ns CPU.
Its model leaf ledger is zero because it invokes no model. Arm intervals already
include their model effects and must not be added to the leaf ledger again.

## Actual topology and withdrawal lifecycle

The experiment bootstraps three real parameter owners, then executes a fixed
split, merge, rollback to the split and rollback to the merged population.
These commit generations 2, 3, 4 and 5. The same cell checkpoint hashes are
restored for the final arm comparison, while stable owner generations increase.
Prepared candidates are backed by actual checkpoint bytes and parameter-owner
databases; the exercise is not only a simulated topology table.

The split uses a fixed three-plus-three support partition of the hint sources,
cloning an already trained checkpoint and retaining its complete ancestry. Merge
reuses the checkpoint already trained on all six hints; it does not average
weights or perform uncounted training. These operations add zero training updates.
The sequence and partition are prescribed, not triggered by a learned or
pressure-sensitive growth controller. Autonomous growth, useful fission under
capacity pressure and learned merge/rollback decisions remain open.

Withdrawing `edge_0_hint` then rejects three old paths: parameter admission,
learned-policy ancestry and rollback to the old topology. All three reject before
a model callback. A fresh-base 256-update replay of the remaining five hints
publishes a new owner and clears the old learned policy. The subsequent actual
read asks for `edge_1`'s hint and returns **`warm`**, while its registered value is
**`cool`**. Rebuild admission worked; answer quality failed. This miss is retained.

Old checkpoints remain physical audit bytes. The withdrawal closes admitted
parameter/policy/topology paths; it is not physical deletion or exact machine
unlearning. The source authority is a trusted local research provider, not native
HNMF attestation or distributed consensus. Source/query fences do not prove that
the first hint is necessary to solve the task, nor that chaining improves it.

## Work, accounting and limits

| Physical work | Measured total |
|---|---:|
| Decoder updates | 1,024 across four real fits |
| Router updates | 400 |
| Decoder reads | 75 = 24 source utility + 50 final arms + one rebuilt owner |
| Training input tokens | 44,546 |
| Decoder input / generated tokens | 3,296 / 136 |
| Canonical child receipts | 80 = one base build + four fits + 75 reads |
| Sum of training-loop seconds | 2.905517 s |
| Model leaf effects, wall / CPU | 604.685265 s / 619.274084 s |
| Entire trial, wall | 608.992389 s |
| Outer process-group receipt, wall | 609.535423 s |
| Outer completion | Exit 0, no timeout, complete result retained |

Every child exited 0, with complete retained stdout. Cold process/runtime startup
is included in the actual child and wall receipts; the very short training loop
does not stand for total system latency. The source utility and router fitting
phase alone used 24 reads and 400 router updates, with an observed interval of
184.305520 s. Physical work trains each population cell once and does not multiply
shared work by seven arms.

Standalone dependency views assign required initial training of 256 updates to
no-edge, 512 to fixed/direct, 768 to random/learned/capability, and zero to exact
source. Only the learned arm requires the source utility matrix and router fit.
These are allocations of already executed work, not extra experiments; their
sum is not the physical execution total. They are incomplete standalone total
cost estimates, not proof of equal total budgets.

Each adapter contains 256 float32 trainable parameters: 1,024 tensor-payload bytes
and 1,552 safetensors-file bytes. Four original trained checkpoints plus fourteen
real topology copies are retained. The completed raw tree contains 770 files and
3,669,427 logical bytes. The budget's earlier inventory reports 3,228,500 bytes;
final result/receipts increase the completed-tree inventory. Peak RSS is a
555,147,264-byte sum of observed parent/child peaks, not an enforced OS memory
quota or an exact concurrent population peak.

The process-group deadline is 900 seconds; model effects use 120-second child
deadlines and persistent reservations. No reservation is pending or lost at
completion. Reported block I/O is Linux rusage block I/O, not all logical reads.
Zero storage-byte-time or transport fields do not imply zero physical resource
use. Transient storage lifetime, complete logical I/O, energy and complete
runtime/OS storage remain unmeasured. No equal-complete-cost or compression claim
is made.

## Evidence, audit and reproduction

The independent raw audit checks 1,414 source/weight/trace/score/cost comparisons
without a model or router prediction. It verifies the literal prompt composition,
decision chronology, actual expert-utility labels, full observed-cell ancestry,
fixed population, exact callback accounting and raw outcome denominators.
Its 34,313,974 ns wall / 34,314,052 ns CPU are additional audit work. The separate
artifact audit verifies all tiny-base files and actual SQLite owner versions,
committed lifecycle operations and the final withdrawal frontier.

The archive includes the complete immutable run, launch/completion/log, both
source capsules, frozen budget dependency, all tiny-base/checkpoint/database
bytes, router serialization, every reader request and receipt, source utility
traces, final policy freeze, all failed/indeterminate outcomes and additional
stdlib audit code/receipts. Only disposable source-capsule bytecode caches are
omitted. Exact unformatted executed code remains available even when readable
publication copies are formatted later.

To reproduce the data audit, run the archived `evolution_edge_audit.py` and
`evolution_edge_artifact_audit.py` against the extracted `run` with new output
paths. The archive index records every input byte and SHA-256. A model replay is
new work requiring the recorded protocol/source pins and a fresh output path;
it must not overwrite this negative result or be relabeled confirmation.

The only interrupted transport attempt concerned publication of the separate
longitudinal archive after this trial had launched. It was abandoned after a
tool wait returned no blob result. No branch, tree, commit or PR was created by
that attempt. The root coordinator owns subsequent remote transport. It did not
alter this experiment or its completed raw evidence.

## Published artifact verification

Archive: `hepta-memory-edge-lifecycle-20261024.tar.gz`, 1,034,424 bytes. SHA-256:
`afed9ed67c691c2e19651598e78d037f3c0e99a6845a31fa5e0bbcd7809dc8ca`. All 903 archive
members were verified against the manifest; 900 payload files contain
4,567,198 bytes. `archive-audit.json` retains the independent verification.
The extra artifact audit completed 81 comparisons, including all 14 real owner
versions, seven base files and terminal topology generation 15. It explicitly
retains `rebuild_correct=false`; no extra model/router predictions were made.
