# Hepta PR #4552: original-head CI triage

**Snapshot: 2026-11-01 10:20:55–10:20:57 UTC. CI is not passing.**

This is read-only evidence for original head `7ff91a4368bc110c35da789b16916e046f79b42c`.
No workflow was rerun or cancelled and no source, dependency, budget or CI setting
was changed by this audit. The [machine-readable report](triage.json) records all
50 job IDs, exact names, states, failed steps, source identities and root excerpts.
The [retained-material inventory](retained-materials.json) records every archived
material's SHA-256, length, source URL and representation.

## Snapshot and counting

| State | Jobs |
| --- | ---: |
| Successful | 19 |
| Failed | 22 |
| Skipped | 6 |
| In progress | 3 |
| Cancelled | 0 |

The 22 failures comprise **14 direct blocking-CI jobs, six native-pair jobs and
two fan-in summaries**. A job can have several causes; overlapping cause groups
must not be added into a larger failure count. Repeated diagnostic printing and
test retries are not extra distinct failures.

The three running jobs are Linux GNU, Linux musl and macOS Intel Bazel tests.
The six skipped jobs are four scoped/conditional jobs in blocking-CI and two V8
build variants. A skipped or running job is not a pass. This is not the completed
workflow's final verdict.

## Source identity

The original head tree is `09483e0039f8f900a403e38f791ca62576f46f38`.
Blocking-CI actually checked out merge
`ea28be81d529d832ef118339c176aa4ddbba16b5`, whose Git API tree equals that head tree.
Its parents are `a575cf03…` and `7ff91a4…`; the checkout is not silently labelled
as the bare head commit.

The prior comparison run is [41064643631](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/41064643631),
associated with parent head `a575cf03e2bc871a2f48021859c03ace806421c8`.
It actually checked out merge `52b3408aaaef531e8f389402a87e83287c48bc1b`, tree
`980cb998c894ee1366098c099de3bbdc0abeb51f`. Its 17 failures, three cancellations
and four skips are historical and are not mixed into the current counts.
Both merge-commit responses and the complete job snapshots are retained.

## Confirmed new PR-owned failure

Linux Bazel Clippy reports two fatal `clippy::unwrap_used` diagnostics in the new
`final_use_pq_recovery_tests.rs` signing helper, at `9:20` and `10:34`.
The first occurs at 09:43:06 UTC. The local scoped Clippy run had treated these as
warnings; CI passes `--deny=clippy::unwrap_used`. The exact added source is retained
as [text](sources/final_use_pq_recovery_tests.rs.txt), Git blob
`44c4b55042df52d241cad4af934ab21f1f360d4d`.

Job: [124811350753](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/41293942805/job/124811350753#step:4:1). This is a definite new diagnostic, not a baseline-only failure.
Repairing that helper alone cannot make the complete Clippy job pass; its other
fatal diagnostics remain independent obligations. No later fix is validated by
this original-head CI snapshot.

## Other observed causes

| Cause | Jobs / earliest useful root observation | Attribution and remaining limit |
| --- | --- | --- |
| Caller closed set | [124811350689](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/41293942805/job/124811350689#step:6:1); 09:41:06 UTC, `learning_artifact_verified_current_view` misses `neural_cognitive_ranker.rs`. | Same diagnostic in prior CI; exact scanner/manifest/ranker blobs match. The stale rule expects `candidate.with_current`, while the caller uses `from_authenticated_current`. |
| Unused dependency | [124811405953](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/41293942805/job/124811405953#step:6:1); 09:41:24 UTC, unused dependency `bytes`. | Same diagnostic in prior CI. The log does not identify its crate; this audit does not guess a dependency removal. |
| Dependency security | [124811350549](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/41293942805/job/124811350549#step:6:1); 09:41:44 UTC, h2 0.3.27 / `RUSTSEC-2026-0258`. | Same prior advisory; still an unresolved security gate, not an exemption. |
| Release API mismatch | [124811350804](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/41293942805/job/124811350804#step:4:1) and [124811350829](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/41293942805/job/124811350829#step:4:1); `E0599`, `append_qualification` missing at `plasticity_process_e2e.rs:116`. | Same error in prior Linux release CI and identical call-site source. Complete Bazel feature/dependency repair is not established. |
| Additional Linux lints | [124811350753](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/41293942805/job/124811350753#step:4:1); earliest unwrap in `authority_trust_unix_tests.rs:18`; guard across await at `authbus_ingress.rs:100`. | Prior CI contains the same guard failure, and the parent source already holds that guard across awaits. Other test and third-party diagnostics remain. |
| Windows linking | Release [124811350776](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/41293942805/job/124811350776#step:4:1), Clippy [124811350879](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/41293942805/job/124811350879#step:4:1), shards [124811350806](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/41293942805/job/124811350806#step:6:1), [124811350822](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/41293942805/job/124811350822#step:6:1), [124811350941](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/41293942805/job/124811350941#step:6:1), [124811350934](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/41293942805/job/124811350934#step:6:1). `libcrypto` has unresolved runtime symbols including `__stack_chk_fail` and `___chkstk_ms`. | Same symbol class in prior Windows release CI. Exact ABI/toolchain repair remains unproven; some shards additionally executed failing tests. |
| Windows key-generation paths | [124811350934](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/41293942805/job/124811350934#step:6:1); 09:45:54 UTC, `g5_trust_tests.rs:277`, OS code 3 / NotFound; additional `ssh-keygen` startup errors. | Concrete process/path failure; complete attribution is unresolved. It is not cleared by fixing the ledger fixture. |
| macOS ARM resource failure | [124811350834](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/41293942805/job/124811350834#step:4:1) and [124811350857](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/41293942805/job/124811350857#step:6:1); native-thread `OutOfMemoryError`, exit 34 and 33 respectively. | Clippy’s gRPC INTERNAL Panic has the same underlying thread-exhaustion cause. Prior comparable macOS jobs were cancelled, so a same-cause prior pass/fail is not claimed. |
| Dependent summaries | [124811730180](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/41293942805/job/124811730180#step:2:1) repeats `cargo_shear failed`; [124813523035](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/41293942805/job/124813523035#step:2:1) repeats Windows shard failure. | Two fan-in outcomes; not two extra independent root defects. |

The same unchanged file is not sufficient evidence of a baseline cause. Where
prior behavior is asserted above, the previous original log is retained. For the
caller proof, all three relevant files are additionally byte-equal at the parent,
original head and prior merge; the [source identity map](sources/source-identities.json)
records the exact Git blobs. These comparisons do not prove unrelated changes safe.

## Native-pair failures and actual Chain identity

The two Windows native-pair configurations fail the evaluated-ledger test at
`evaluated_shadow_pq_tests.rs:304`, with Win32 code 33 for a locked file region.
The same test also fails in Windows Bazel shard 2. Hepta's ownership review
identified a fixture copy/read while the ledger owner remains alive; the later
lifetime repair needs its own validation. Windows link failures remain separate.

Windows jobs: [124810737056](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/41293942778/job/124810737056#step:8:1), [124810737157](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/41293942778/job/124810737157#step:8:1); additional shard [124811350822](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/41293942805/job/124811350822#step:6:1).

All four Linux/ARM jobs fail their original pressure/convergence step: [124810737135](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/41293942778/job/124810737135#step:28:1), [124810737175](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/41293942778/job/124810737175#step:28:1), [124810737207](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/41293942778/job/124810737207#step:28:1), [124810737209](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/41293942778/job/124810737209#step:28:1).

The independently inspected detailed artifact is **only ARM source-head job
124810737207**, artifact `13078229624`. Its original
[ZIP](artifacts/arm-source-head-evidence.zip) is retained; SHA-256
`6fb34cbd21ed39888912c0ea0fe516e0002805c4d22d713c4669fb74444430a9`.
Its exact manifest, confirmation report and controller outputs are also retained
as lossless compressed ZIP-member bytes.

That run used Chain commit `131f673d9563e72aca7139f3239856957d118d49`, tree
`b8bdd87dca3cd6288c38f63848b24b1a2df6a09d`, with Hepta source head `7ff91a4…`.
It is not the interrupted, lost Chain witness candidate or the recovery-docs branch.

| Original four-second phase | Confirmations | Confirmation latency | Finite business target | Full native state equal |
| --- | ---: | --- | --- | --- |
| Attack-free baseline | 1 | 2.389878787 s | true | true |
| Pressure from zero, 16 workers | 0 | none | false | false |

All five named Rust tests passed, but the native manifest reports
`CONFIRMATION_TARGET`, `passed=false`. The reported invariant target remains true;
that does not replace timely honest confirmation. This detailed cause is not
extrapolated to the three other controller failures whose detailed artifacts
were not inspected. No deadline, worker count or acceptance target was relaxed.

## Evidence retention and limits

- 22 complete current failed-job logs and six complete prior comparison logs are
  retained under `logs/`; hashes cover both gzip and uncompressed representations.
- The six native-pair logs independently downloaded for this audit match the
  other agent's preserved originals byte-for-byte.
- Full job-log text is the connector's decoded response, re-encoded as UTF-8
  without content editing, including ANSI sequences, BOM and line endings. The
  compressed files are not falsely described as original GitHub log ZIP bytes.
- Readable root excerpts may remove ANSI color escapes for display; the full
  retained logs preserve those bytes. Two peer-supplied text artifacts are also
  stored with lossless gzip to preserve their original context whitespace and
  final newline; [the storage transformation record](archive-transformations.json)
  retains both original and compressed hashes.
- `peer-observations/` preserves earlier agent receipts. `followup-received/`
  preserves a proposed two-file patch and a labelled formatting observation;
  neither belongs to the original-head CI result or was applied by this audit.
- The original artifact ZIP and complete selected members are preserved as
  original bytes; summaries are explicitly derived analysis.
- The later follow-up's tests, strict lint result, final source identities and
  eventual CI require separate receipts. No green whole-CI, complete paired
  acceptance or whole-chain PQ claim is made here.
