# Final CI diagnostic snapshot

PR4649 head `94252595fa741ed331b9946d7a910b28c96e44cf` is **not CI green**.
Run41378736133 confirms that head; reusable workflows refer to merge commit
`f2e56a873f49768673f15fb85225406103137dfb`. The observed first-page job list
contains nine completed failures, and other platform jobs remain queued or
running. This was read-only retrieval: no scientific rerun, source mutation,
workflow change or bypass.

| Jobs | Confirmed failure | Remaining uncertainty |
|---|---|---|
| cargo-deny125069634987 | `Run cargo-deny` fails; setup and clean-worktree succeed | Both log calls return `Transport closed`; advisory/license/policy reason unknown |
| Windows test shards125069635177/248/225/224 | MSVC-target rust-lld cannot resolve stack-check, MinGW and CRT symbols from native dependencies | Object/runtime/toolchain incompatibility is plausible; exact producer/cache/flag cause unverified |
| Windows clippy125069635221 and release125069635187 | Same native-link error family | These are not demonstrated fixes or merely skipped tests |
| Ubuntu release125069635119 | E0599: `DurableLedger::append_qualification`, plasticity_process_e2e.rs:115 | Separate exact-head audit finds a feature-gated implementation and a Bazel integration-test profile bypass |
| Ubuntu clippy125069635168 | Same E0599; `unwrap`/`expect` lints; disallowed direct SQLite pool connections | Broader lint failures remain beyond the single profile proposal |

The Windows test shards also contain **actual executed test failures** beyond
link failures: shard1 rejects a fleet workspace path as noncanonical; shard2
reports `PermissionDenied`/`UnsafeStateDirectory` in intelligence tests; shard3
V8 aborts with `!IsConfigurablePoolInitialized()`; shard4 reports missing key
generation/ssh-keygen paths and permissions in operator acceptance, plus unsafe
state directories in prompt optimization. The observed errors are concrete;
their deeper causes have not been established by this triage.

GPU job125069498107 was reported queued by the parent. Independent step fetch
returns an empty list and log fetch returns404 `BlobNotFound`. There is no
observed executed GPU step or numerical/cost evidence; these responses alone
do not prove why it is queued or whether suitable hardware is available.

[CI_FINAL_TRIAGE.json](CI_FINAL_TRIAGE.json) records failed steps and diagnostic
messages. The two compressed JSON files retain the run/job snapshot and selected
decoded-log excerpts with line numbers. Complete decoded logs for all eight retrieved failed jobs are archived as
deterministic gzip; two large compressed streams are split into bounded parts.
`CI_FINAL_TRIAGE_RAW_LOGS.json` records concatenation order, byte sizes and both
compressed/decoded SHA256. All11 parts are at most400000 bytes; cargo-deny
remains unavailable. The job-list wrapper returns only
its first page/latest attempt, so no all-pages completeness claim is made.

The separate test-only Bazel candidate under
`tools/hcsn/ci_qualification_profile_r22_20261102` requires root review and
meaningful hosted validation. It does not justify enabling legacy writes in
production, adding an API stub, or declaring the broad suite repaired.
