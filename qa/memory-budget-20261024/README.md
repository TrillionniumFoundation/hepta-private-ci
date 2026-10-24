# Workflow memory: actual budget, task, and prospective evidence

## Evidence navigation

The full evidence is stored as ordered binary archive parts listed in
[evidence-manifest.json](evidence-manifest.json). Download the parts, concatenate
them in manifest order, and verify the archive SHA256 before extracting it.
The archive root is `memory-budget-evidence-20261024/`; its `MANIFEST.json`
records every payload file's SHA256, original path, and original seal mapping.
Paths in the report below refer to files inside that archive. The original
reviewed report bytes are also preserved there as `README.md`; only link
presentation and this navigation section differ in this published copy.

The base model, installed runtimes, and separate codec engineering follow-up
are excluded as documented in the manifest. Original A/B executed sources,
full outputs, checkpoints, and all earlier failure observations are included.

The frozen four-arm pretrained experiment completed with 416 actual optimizer
updates and 210 raw decoder outputs. Known-source exact accuracy was 3/16,
3/16, 1/16, and 2/16 for single, expanded, data split, and random split;
lineage-supported exact accuracy was 1/16 in every arm. No arm produced an
admissible repair for the four historical natural tasks. These results do not
establish a memory growth advantage, net compression, or future task success.

This is development evidence against implementation commit
`429894ac8e0818102cfdea4ad47a56e4583b2902`, with one fixed model seed.
The full raw result is model-budget-run-001/result.json (`model-budget-run-001/result.json` inside the archive).
Its SHA256 is `5cde385cec6f760bda917b882681c04d9d1dd8cc32a34daf239a74bdb88f0ba0`.
The independent standard-library artifact audit (`model-budget-audit-001.json` inside the archive)
records 5,472 comparisons, zero failures, and no extra model or route calls.
These are artifact comparisons, not 5,472 unit tests.

## Evidence partitions and exposure

The historical source corpus comprises all 75 YAML workflows at main
`f8c9419df6ddeb36ff8b522a50219981fb8d9345`, available 2026-10-16 UTC.
Their exact source text totals 586,372 bytes. No workflow was selected using the
four later tasks. Seventy-five documents are not 75 independent task groups.

The four original-input tasks are curated time holdouts: missing Clippy
installation, Ruff F401/E731, Cargo.lock dependency disambiguation, and a codec
job that passed while skipping all 21 tests. The curator saw published repairs
before this experiment. They are not blind or genuinely prospective samples.
Original logs, source SHAs, and environment boundaries are retained in
task metadata (`prepared-001/task-metadata.json` inside the archive); repair material under `gold/`
never enters retrieval, model fitting, source partitioning, or router inputs.
The original Clippy input itself contains an installation hint.

## Prospective window: zero qualifying new groups

Rules were persisted at 2026-10-24 04:52:06.790611 UTC, before the registered
06:51:19 deadline, with a maximum of 12 independent new root-cause groups.
The final API observation at 06:51:33 retains all 13 returned failure rows,
each created and completed within that window. Twelve have the exact original
validation annotation already observed before registration: `Unrecognized
named-value: 'runner'`, in expression `runner.temp`. The remaining run,
40064504763, has zero jobs and no available original annotation. Its identical
workflow blob alone does not prove an identical root cause.

No independent new group qualified; no prospective prediction or execution
occurred. The result is 0/0 with accuracy null, not zero percent.
The final prospective record (`prospective-final-20261024.json` inside the archive) retains all rows,
exclusions, original page identities, and registration hash. Earlier cutoffs and
the unavailable diagnostic are preserved. Unrelated queued workflows are not
reported as successful.

## A: actual source retrieval and original task gates

A used protocol SHA256
`3263e416cd0df587e08ef380a3914662c7a398d12b0a90fd53c686fe1358ceed`
and source-seal SHA256
`3bbf6b52661e31e2e7f3465f5ef1c6c9f435c17e7e8d1f02e8f0dfc0e29d48ad`.
The exact executed A sources and outputs remain unchanged.

The retrieval result (`baseline-run-001/result.json` inside the archive) records actual source-only
BM25/code-token retrieval with path overlap over all 75 documents. The full
SQLite index occupies 1,474,560 bytes. Twenty-eight repeated original-input
queries across seven reader reopenings were stable. Fixed prefixes of 16, 32,
64, and 75 documents were also built and queried; their receipts are retained.
This establishes behavior only at those small corpus sizes.

The 645,305-byte source-document JSON roundtrips exactly through zlib-9
(108,308 bytes) and lzma-6 (81,720 bytes). Declared retained baseline components
at the inventory cutoff total 3,842,097 bytes. Metered work took 0.789 wall
seconds and 0.600 CPU seconds. Acquisition, complete runtime/OS closure, and
continuous file byte-time are incomplete; these are not a full provider bill.

This retrieval policy proposes original source command lines. It has no general
reasoner, dense reranker, or complete repair-agent tool loop, so it is not a
sufficient strong RAG/repair-agent baseline.

| Method | Verified task successes | Original gate coverage | Actual lint exits |
|---|---:|---:|---|
| Original input hints | 0/4 | 1/4 | before 1, after 1 |
| BM25 source command proposal | 0/4 | 1/4 | before 1, after 1 |

The exact pinned Python fixture reproduces F401/E731 with Ruff 0.15.13.
E731 occurs at line 237 in that source versus line 235 in the historical log:
this is the same failure class, not byte-identical logs. Neither policy supplied
an admitted repair. The other three original environments were unavailable and
remain in the denominator. The unchanged gate requires an admitted action,
a passing Ruff check, and all 76 original semantic tests. The Ruff failures
prevented those 76 tests from running; no published author test count is reused.
Original command/exit receipts are in input-only results (`input-only-tasks-001/result.json` inside the archive)
and retrieval task results (`retrieval-tasks-001/result.json` inside the archive).

## B: frozen source-only recipe and actual execution

Automatic extraction visits every workflow run block, skips heredoc bodies,
and retains short single commands without shell expansion. It produced 455
candidates across 60 workflows. Source hash order and the unchanged tokenizer
contracts admitted 128 records across 53 workflows; 327 exclusions are recorded.
Values plus EOS must fit 16 generation tokens and complete prompts 192 tokens.
No natural final task selected these source records.

| Arm | Initialization | Additional actual updates | Active adapter values |
|---|---|---:|---:|
| Shared parent | rank 4, frozen base | 32, physically once | 230,400 |
| Single | verified shared parent, rank 4 | 96 | 230,400 |
| Expanded | verified rank 4 to 8 function-preserving expansion | 96 | 460,800 |
| Data split | two rank-4 children, whole-workflow lexical groups | 48 + 48 | 460,800 |
| Random split | two rank-4 children, seeded whole-workflow groups | 48 + 48 | 460,800 |

SmolLM2-135M, seed 2718, learning rate 0.001, source templates, hash order,
and random partition seed 4731 were fixed before B fitting. Split routing uses
source-only lexical centroids, not decoder utilities or learned cell-to-cell
edges. Data shards contain 75/53 records and random shards 83/45: group counts,
not fact counts, were balanced. Source facts actually encountered during
training were parent 29, single 79, expanded 79, data children 42 and 38,
and random children 39 and 32. These sets overlap across stages; adding them
does not count distinct exposure. No full 128-fact pass is implied.

The unchanged source input pin is
`7e46a687b168e9c960199125eb8cbd09a8b95afd0a938326351a7618201ce375`.
The reader base identity is
`46b83e37620f8bb1ae57754856718886c6aa1b12d267b5b0993e779f9596f96f`;
the full base weights SHA256 is
`5af571cbf074e6d21a03528d2330792e532ca608f24ac70a143f6b369968ab8c`.
Exact base/runtime receipts are in launch dependencies (`b-execution-002/launch-dependencies.json` inside the archive).

B uses protocol SHA256
`65c01a741ce2580a7adbe415da5c47ca8abfff184587e952bed38aeb0187d675`
and seal SHA256
`e6f2e8fdd0e4b515e327a7c0ded300255e13da3d5ae57b61ad4ba2065ba5dab8`.
The independent `b-execution-002/source` revision fixed only an outer coordinator
failure boundary before any B fit. The freeze map (`b-execution-002/freeze-map.json` inside the archive)
preserves all 33 original protocol fields and all five input companions.
A outputs had already been observed; this was not a blind new benchmark.

The actual run exited zero in session 69617. All 61 disposable model children
returned zero: seven actual training receipts account for 416 updates, and
all 210 counted decoder rows come from raw child outputs. No child timed out;
OOM and OOM-kill counters remained zero. Eight physical checkpoint copies retain
9,339,888 safetensors bytes, including parent and expansion ancestry.
The completion receipt (`model-budget-run-001.completion.json` inside the archive), raw stderr,
monitor history, training receipts, and checkpoint manifests are retained.

An earlier process-creation request was rejected by a disconnected exec server
before a session/PID existed. After recovery, readback confirmed the result
directory and stdout/stderr files were absent and all 130 B source pins valid.
The explicitly authorized subsequent launch created session 69617. This is a
retained infrastructure observation, not an executed model failure or automatic
model retry; see launch transport receipt (`model-budget-run-001.launch-transport.json` inside the archive).

## B: raw quality, controls, and missing requests

The 16 known-source questions reword admitted facts; they are neither novel facts
nor independent future tasks. Supported exact match additionally requires the
answer fact's source digest in the selected checkpoint lineage. The adapter-off
and shuffled controls cover only four paired known-source questions per arm.

| Arm | Exact known source | Supported exact | Adapter on paired four | Base / shuffled on paired four | Actual raw rows |
|---|---:|---:|---:|---:|---:|
| Single | 3/16 | 1/16 | 2/4 | 0/4, 0/4 | 54 |
| Expanded | 3/16 | 1/16 | 2/4 | 0/4, 0/4 | 54 |
| Data split | 1/16 | 1/16 | 0/4 | 0/4, 0/4 | 51 |
| Random split | 2/16 | 1/16 | 2/4 | 0/4, 0/4 | 51 |

Each arm planned 64 requests: 16 known-source plus four natural adapter reads,
four known-source plus four natural reads for each control, and 28 natural load
requests. Overall, **256 planned = 210 raw decoder rows + 38 input-contract
rejections + 8 uncompleted load requests**. The codec prompt has 442 tokens,
exceeding the unchanged 192-token limit; it is rejected, never truncated.

Single and expanded handled 28/28 load requests, including 21 actual decoder
outputs and seven contract rejections each. Each split handled 24/28, including
18 outputs and six rejections, and retained four uncompleted requests under
`common_budget_preserves_final_inventory`. That preregistered guard preserves
read/wall/query headroom for final inventory. An arm's `executed` status does
not mean every planned request completed or every resource ceiling was exhausted.

Routes were fsynced before read reservations in the actual SQLite journal and
request files. This is controller/file chronology; bootstrap receipts have no
independent UTC child-start timestamp. Raw outputs are never replaced by source
answers. No new oracle cell matrix was run, so these results do not uniquely
identify the cause of low accuracy or rule out all alternative split designs.

## B: natural task actions and original-gate boundary

| Original task | Single | Expanded | Data split | Random split |
|---|---|---|---|---|
| Clippy | `cargo-clippy --version` | same | `exit` | `cargo-clippy --check` |
| Ruff | `python3 scripts/multimodal_output_portfolio/v4/` | same | `python3 --python3 --python3` | `print` |
| Lock | `python3 scripts/check-lock.py --locked` | `python3 scripts/cargo.lock --locked` | `uname -a` | `git diff --check` |
| Codec | 442-token input rejected | same | same | same |

The natural-action admission audit (`model-budget-natural-admission-001.json` inside the archive)
binds all 16 rows to raw outputs and the unchanged Ruff action schema. None
qualifies: zero admitted repair actions, zero executed repair actions, and zero
new original-task gate executions for B. Verified success is 0/4 per arm; this
does not mean four reconstructed original environments were executed. A retains
its actual lint gate exits. No gold action label or short-command recall counts
as task repair. Later codec environment engineering is a separate experiment,
excluded from these A/B outcomes, coverage, and cost ledgers.

## Common ceilings, actual costs, and storage

Every neural arm has the same 600-second wall ceiling and fixed resource prices.
Its standalone view allocates the measured 32-update parent once, allowing
128 updates; physical experiment totals count that parent once across all arms.
The remaining common limits include 1,200 CPU seconds, 32,768 training tokens,
64 decoder queries, 32,768 inference input and 4,096 output tokens, 8 GiB logical
reads, 2 GiB writes, 4 GiB retained files, 32 MiB private files, and 3 GiB peak RSS.
Router/feature/gradient and transport limits remain in the complete protocol.
Resource-fraction prices are accounting weights, not currency or measured energy.
The protocol's `fixed_total_capacity` is a 460,800-value ceiling: only expanded
and both splits use equal active capacity. Comparing them with the half-sized
single arm is a priced growth comparison, not equal active-capacity consumption.

| Arm | Metered standalone wall s | CPU s | Training tokens | Private bytes | Declared retained bytes | Unused wall s |
|---|---:|---:|---:|---:|---:|---:|
| Single | 273.145 | 416.046 | 10,540 | 1,631,110 | 1,147,773,462 | 326.855 |
| Expanded | 281.940 | 429.166 | 10,540 | 4,444,829 | 1,150,587,181 | 318.060 |
| Data split | 335.712 | 479.887 | 10,533 | 2,778,572 | 1,148,920,924 | 264.288 |
| Random split | 337.243 | 479.837 | 10,562 | 2,773,536 | 1,148,915,888 | 262.757 |

The physically executed total is 1,114.296 metered wall seconds, 1,630.371 CPU
seconds, 34,303 training tokens, 23,440 inference input tokens, and 2,180 output
tokens. Logical reads total 27,136,279,545 bytes and writes 27,011,911 bytes.
No router updates, gradient probes, or feature forwards ran. Actual consumption
differs; common ceilings are not matched actual total cost. Shared parent work
must not be summed four times as physical execution.

Declared inventories include base files, source/study data, checkpoint ancestry,
recovery artifacts, and the declared Python site-packages directory. They share
components across arms and must not be summed as physical deployment storage.
Inventories are cutoff snapshots taken before their own ledger settlement and
final-result writes; the packaged final files have a separate complete manifest.
Peak child RSS is a conservative cumulative high-water measure, not a fresh
independent per-arm memory peak. `rchar`/`wchar` measure logical syscall bytes;
they do not cover all memory-mapped reads or equal physical disk traffic.
Historical acquisition cost, full application/OS dependency closure, network
stack overhead, and continuous/transient file byte-time remain incomplete.
Zero for an unmeasured dimension is not evidence of free work. No net compression
ratio can equate lossy 128-command accuracy with lossless full-source storage.

## Validation, publication copy, and evidence preservation

A's 26 standard-library tests and B's 29 tests passed before final formatting.
Failure-path tests use fake child receipts where indicated; they are not model
results. Actual B sources remain unformatted and sealed. The separate publication
copy contains 24 formatted modules in ten dependency stages of 323--499 lines,
except the two smaller 280/286-line stages; every module is below 500 lines.
No product tests ran after the final formatter.

The formatting receipt (`publication-source-001/format-equivalence.json` inside the archive) records
20 raw-AST-identical files and four files with six function-docstring indentation
changes. Every non-docstring AST node and cleaned docstring is unchanged; raw
`__doc__` whitespace is not identical. The first exact-AST audit failure is
retained as a formatting audit observation, not an experimental failure.
The model artifact audit verifies final source/base pins, child receipts, actual
updates/tokens, SQLite accounting, controls, request denominators, checkpoint
hashes and safetensors layout without importing Torch or generating new answers.

The evidence archive preserves original A and B sources/seals, historical input
and repair provenance, all prospective cutoffs, full actual outputs, checkpoints,
SQLite ledgers, process receipts, audits, and publication equivalence receipts.
Large base/runtime installations are external pinned dependencies; their retained
sizes remain in the declared cost inventory. Original absolute-path seals remain
unaltered, with archive-path mappings supplied separately. Historical handoffs
and pre-B reports remain historical records, not current completion claims.

The remaining qualification gaps are strong complete retrieval/repair-agent
comparison, broad independently sampled natural tasks, genuinely future task
success, stable multi-seed memory quality, matched complete total cost, net
compression at equal utility, sustained scale, and physical distributed-host
performance. This fixed run supplies measured negative/limited development
evidence and working budget accounting; it does not close those gaps.
