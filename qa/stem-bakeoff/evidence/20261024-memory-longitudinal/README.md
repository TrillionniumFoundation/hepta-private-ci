## Published archive transport

The complete 79,416,167-byte archive is published as 13 ordered binary parts.
The retained source report below refers to the reassembled archive. Download all
`hepta-memory-longitudinal-20261024.tar.gz.part-*` files alongside `parts.json`
and `reassemble.py`, then run:

```sh
python reassemble.py --output hepta-memory-longitudinal-20261024.tar.gz
```

The helper checks every part size, SHA-256 and Git blob identity before checking
the complete archive SHA-256. It refuses an existing output. Reassembly does not
execute a model or modify the retained experimental evidence. The base model
remains external with its full pinned six-file inventory.

# Longitudinal typed memory: completed development campaign

This is a completed, preregistered three-seed synthetic development campaign.
All 5,184 decoder optimizer updates and 558 raw decoder rows ran. Every seed
failed the required conjunction of continuous parameter accuracy, retention and
correction quality. The engineering lifecycle completed; this does not establish
reliable continual memory, a natural future-task advantage or production readiness.

## Exact execution identity

| Item | Identity |
|---|---|
| Baseline commit | `429894ac8e0818102cfdea4ad47a56e4583b2902` |
| Executed source capsule | `longitudinal-source-002` |
| Source identity, canonical JSON SHA-256 | `693f288009f134a2d8e1a65c1f2fee255a1ea29d87f9c8183c8f7f218e51983e` |
| Campaign, canonical JSON SHA-256 | `f5825183d082f429764234809ec4585ae2218f5543d8cd9a967a329aeb384c23` |
| Campaign file SHA-256 | `7ca0d71b559cb7d1896915b442af4f3fe25d0910699dc6300d58926894edfaf5` |
| Base | `HuggingFaceTB/SmolLM2-135M-Instruct` |
| Publisher revision | `12fd25f77366fa6b3b4b768ec3050bf629380bac` |
| Complete six-file base inventory, canonical SHA-256 | `46b83e37620f8bb1ae57754856718886c6aa1b12d267b5b0993e779f9596f96f` |
| Campaign result file SHA-256 | `0ae172c78012ace799b7046d09f186430ada11bfbebf80ba5c9db17613b6705b` |

Each seed retained and rechecked 114 baseline Python source files and ten driver
modules. All before/after identities match. Exact unformatted executed code is
in the archive; readable published copies are not a substitute for these bytes.
Runtime package versions are retained, but they do not establish complete runtime
or operating-system dependency-byte closure. The external base is 271,170,520
bytes; all six filenames, sizes and SHA-256 values were checked before each seed.
Those base bytes are not duplicated in this archive.

Source-001 and registration/campaign predecessors are retained as unexecuted
history. Before any model invocation, scheduling was corrected to enqueue the
background job after a published cut, use `WriteReceipt.training_job_id`, and
revoke `conflict_04` using its actual typed key `long_04`. Source-002 and
campaign-002 incorporate these executable fixes. No observed model score changed
the recipe, stream order, threshold, seed set or subsequent event schedule.

## Frozen stream and quality definition

The launch order is 24019, 24023, 24029. Each has six fresh-base full-replay fits
of 256 updates and three real background fits of 64 updates which are superseded
by an admitted source event during candidate construction. Each seed therefore
performs nine fits and 1,728 updates, not six fits with uncounted discarded work.
Training uses rank 8, learning rate 0.001 and the four registered templates.

The same six-round event policy starts with eight color facts, adds facts,
corrects existing source revisions, withdraws facts, introduces one conflicting
source, then withdraws that conflicting source. Live fact counts are
`[8, 9, 10, 10, 10, 10]`. There are 24 source events per seed. Seed variation
changes the initial color assignment and training randomness; these are related
synthetic streams, not three independent natural task cohorts.

A source counts correct only when both registered read wordings produce the exact
stored answer. Parameter scoring uses raw decoder text, with whitespace stripping
only; no answer lexicon, retrieval input, source answer or generated-text repair
is supplied to the decoder. Required gates were fixed before execution:

- Every round must have at least 90% source accuracy across both wordings.
- Every nonempty retention panel must have at least 90% accuracy.
- Every corrected source present in the current panel must be exactly correct.

Retention means the same key and value in consecutive rounds, evaluated after
fresh-base replay. It does not require an unchanged source revision or digest.
The round-2 `long_02 -> blue` correction is a same-value correction for seeds
24023 and 24029, so it appears in both correction and retention panels. This is
service retention after replay, not a pure gradient-forgetting measure on a
single adapter updated continuously. Quality failure continues the full fixed
campaign; it does not remove the seed or trigger recipe changes.

## Parameter results, with denominators

Each entry lists rounds 0 through 5. The first retention/correction panel is
empty and shown as a dash. Counts are repeated source/round observations; they
are not independent natural samples.

| Seed | Source correct on both wordings | Retention correct on both wordings | Corrected sources correct |
|---|---|---|---|
| 24019 | 7/8, 6/9, 4/10, 7/10, 1/10, 5/10 | —, 5/7, 1/6, 4/7, 1/8, 3/8 | —, 1/1, 2/3, 2/2, 0/1, 1/1 |
| 24023 | 8/8, 9/9, 10/10, 10/10, 10/10, 8/10 | —, 7/7, 7/7, 7/7, 8/8, 6/8 | —, 1/1, 3/3, 2/2, 1/1, 1/1 |
| 24029 | 8/8, 9/9, 10/10, 10/10, 7/10, 2/10 | —, 7/7, 7/7, 7/7, 6/8, 1/8 | —, 1/1, 3/3, 2/2, 1/1, 1/1 |

| Seed | Every round ≥90% | Every measured retention panel ≥90% | Every correction exact | Combined gate |
|---|---|---|---|---|
| 24019 | Fail | Fail | Fail | Fail |
| 24023 | Fail | Fail | Pass | Fail |
| 24029 | Fail | Fail | Pass | Fail |

The raw-query counts are respectively `[15/16,12/18,8/20,14/20,4/20,11/20]`,
`[16/16,18/18,20/20,20/20,20/20,16/20]` and
`[16/16,18/18,20/20,20/20,15/20,4/20]`. These less stringent query counts do not
replace the two-wording source criterion. Adapter-disabled base and shuffled-adapter
controls were executed at rounds 0 and 5. For every seed and each control,
they scored 0/8 and 0/10 sources, and 0/16 and 0/20 raw queries.

All seed coordinators exited 2, the registered quality-failure exit. Their
retained completion receipts report `timed_out=false`. Every canonical model
child exited 0; no execution-failure file or incomplete stdout was present.
The campaign-result records all seeds completed. This archive contains these
actual receipts; it does not fabricate a separate signed outer tool exit receipt.

## Source and lifecycle results, reported separately

Independent replay of the registered source events found 72/72 immediate overlay
responses correct: 63 `answered`, three `conflict`, six `revoked`. Withdrawing the
conflicting source correctly exposes the surviving answer, so that response is
`answered`, not `revoked`. These are source-layer behavior counts, not parameter
recall. They never enter a parameter numerator. Mutation plus its immediate
overlay read took 61,230,689 ns, 85,111,345 ns and 90,251,629 ns per seed. This
combined measurement is not isolated retrieval latency and is not a retrieval
comparison on the complete parameter-question panel.

| Engineering observation | Actual result |
|---|---|
| Dirty parameter admission | 204 checks, zero model callbacks and zero raw responses |
| Dirty status breakdown | 171 unavailable, 18 unknown, 12 revoked, three conflict |
| Superseded background fits | Nine actual 64-update fits; all nine terminal jobs are superseded |
| Clean publication | 18 actual 256-update fits admitted into real parameter owners |
| Stable identity | Same cell ID; owner generations 0–5 and topology generations 1–6 per seed |
| Source withdrawal closure | Eleven durable withdrawn roots per seed; each clean owner excludes the then-current withdrawn roots |
| Checkpoint retention | 27 trained checkpoints plus 18 actual transaction copies; all 45 physical copies retained |

The lifecycle audit opens completed SQLite databases in read-only immutable mode
and rejects leftover WAL files. It checks actual owner records, operation records,
committed generations, source cuts and manifests against the retained receipts.
The nine stale fits really trained; their losses and optimizer work remain in
the evidence. The event was inserted after candidate construction was observed.
The following clean fit published in every scheduled round.

This demonstrates finite supersession and recovery. Publication latency was not
separately timestamped; round wall time also includes reads and controls. No
sustainable arrival-rate or unbounded starvation guarantee is claimed. The
source provider is the trusted local research service, not independently attested
native HNMF authority. These runs exercise refresh publication; split, merge and
rollback execution belongs to the separate edge-lifecycle experiment.

Retained old checkpoints remain physical audit bytes. Withdrawal blocks their
admission; it does not establish physical erasure or exact machine unlearning.

## Actual work and retained storage

| Quantity | 24019 | 24023 | 24029 | Sum |
|---|---:|---:|---:|---:|
| Optimizer updates | 1,728 | 1,728 | 1,728 | 5,184 |
| Raw decoder rows | 186 | 186 | 186 | 558 |
| Training input tokens | 128,031 | 128,041 | 127,955 | 384,027 |
| Decoder input tokens | 13,950 | 13,950 | 13,950 | 41,850 |
| Generated tokens | 1,254 | 1,254 | 1,322 | 3,830 |
| Training seconds | 940.976 | 1,200.569 | 1,216.141 | 3,357.686 |
| Seed elapsed seconds | 1,238.866 | 1,581.844 | 1,574.579 | 4,395.290 |
| Model child receipts | 19 | 19 | 19 | 57 |

The 558 rows comprise 342 adapter rows and 216 base/shuffled-control rows. Counts
come only from canonical `*.stderr.result.json` journals, not duplicated embedded
journals or copied checkpoints. Child PID values are unique within each seed;
there is no general cross-namespace PID-identity claim. Recorded child CPU totals
7,555.050 seconds and parent CPU 10.870 seconds; seed elapsed sums are not a
separately measured entire scheduler wall clock. The three seed-wrapper receipt
elapsed times are retained independently.

Each adapter has 460,800 float32 trainable parameters: 1,843,200 tensor payload
bytes and 1,858,776 safetensors-file bytes. The final immutable run inventory has
968 files totaling 92,305,297 logical bytes. This includes physical transaction
copies and all raw evidence, but excludes the external base, runtime and extra
derived audits. It is not peak disk usage, exact storage byte-time, total memory,
energy or a complete lifecycle I/O measurement. Parent peak RSS values are
retained; full child/population peak RSS was not measured by this campaign.
No memory-compression or equal-total-cost advantage is established.

## Independent audit and archive contents

`audit/audit.json` independently reduces raw query rows, source wordings,
retention/correction panels and all quality gates; it also checks byte-pinned
source snapshots, real safetensors layouts and original training receipts.
It completed 8,145 comparisons in 734,208,674 ns wall / 438,705,453 ns CPU.
`audit/lifecycle-audit.json` adds 676 SQLite/lifecycle comparisons in
11,939,205 ns wall / 11,939,177 ns CPU. `audit/overlay-audit.json` independently
replays all 72 source events in 3,763,362 ns wall / 3,762,188 ns CPU. These are
additional audit costs with zero model or router predictions. The comparison
count is an audit-operation count, not a statistical sample size.

The archive contains the complete run root, both source capsules, registration
history, exact audit/packaging helper source, development test source, launch log,
runtime version lock, the three derivation receipts and raw per-file inventory.
Only disposable Python bytecode caches in source capsules are omitted; executed
Python modules, model outputs, all checkpoints and databases are retained.
The zero-byte outer launch log is preserved; actual output is in per-seed logs.
An external manifest identifies every archived input by full SHA-256 and bytes.
Archive metadata fixes timestamps, ownership and modes; compression is streamed
gzip level 3. A separate archive audit verifies all member bytes and the index.

To reproduce the statistical reduction after extraction, run the archived
`evolution_audit.py`, `evolution_overlay_audit.py` and
`evolution_lifecycle_audit.py` with `--longitudinal <extracted>/run` and new
`--output` paths. They do not import Torch or invoke a decoder. A model rerun is
new work, not an audit: use the archived source-002 runner, exact baseline HEAD,
the pinned six-file base and compatible runtime, with the campaign/source hashes
above and a fresh output directory. The complete original argument vectors are
in `run/seed-*.completion.json`; replace only environment paths for relocation.
Do not overwrite this completed negative result or describe a rerun as confirmation
without a new preregistration and untouched cohort.

## Published package verification

Archive: `hepta-memory-longitudinal-20261024.tar.gz` (79,416,167 bytes), SHA-256
`bedd0c0ef0f176549efe085f3615f4f417517bb03b91d74a9cab946e15b10dc6`.
`archive-audit.json` independently checked all 1024 members (1021 payload files
plus three metadata members), with every member hash matching. The archived payload is
92,920,383 bytes. The outer `manifest.json`, `index.json` and receipt identify the
exact source/evidence closure; `SHA256SUMS` checks the compressed artifact.
