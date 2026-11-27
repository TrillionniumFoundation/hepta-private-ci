# Ordinary Rust consolidation: repair round 4

This directory preserves six reviewed source changes, the actual observations
that motivated them, a complete HIA protection preparation snapshot, and
separate future conflict resolutions. It does not qualify the combined source
tree or establish new historical branch coverage.

## Source identity and exact changes

The published input is `bbd56024408bb9f1b54dac9db91b628247a6488a`, with tree
`83b83df5596d95b6ef1e9ad79202c30732d3dc8d`. Four actual server source commits
have been created and read back, in this exact single-parent order:

1. `e8259f3c993f6258fcb6cacdd7629a22343192d1`: two exact formatter afterimages.
2. `82812ed8760dfd4df3ae5ab2259da98a61f96b39`: Bellman example error propagation.
3. `3c783d420f2b5be7005393c2e98e38a4da442953`: pinned Pillow workflow dependency.
4. `6220870f23ecef0b3d3924881821d5aa372de35f`: nine existing binary fragment
   identities registered with the existing spelling custody mechanism.

The source tree is `91cf7dfc529bd5a06e58da656cc59c343b51da2f`. It changes
exactly these six paths:

| Path | Change and preserved contract |
| --- | --- |
| `codex-rs/hepta-agentd/src/memory_serving_process_tests.rs` | Exact formatter artifact; all tokens, literals and assertions preserved. |
| `codex-rs/hepta-infer-core/src/durable_control_tests.rs` | Exact formatter artifact; all tokens, literals and assertions preserved. |
| `codex-rs/hepta-bellman-operator/examples/qualification_performance.rs` | Propagate the actual failures with their original context and error chain. Preserve successful operations, timing, samples, budgets, comparisons and output. |
| `.github/workflows/hepta-neuron-next-round-matrix.yml` | Add only `Pillow==13.0.0` to the execution regressions install command. |
| `.github/scripts/codespell_custody.py` | Add nine exact immutable binary fragment paths to existing custody validation. |
| `.github/codespell-custody.json` | Bind those same nine paths to their existing SHA256 values. |

All other 59,154 existing source-tree leaves retain their mode, type and object
identity. Cargo manifests, lockfiles, old QA archives, test selectors and
required gates are unchanged. The original 15 Python custody tests passed on
the frozen custody candidate. A separate import addendum confirms the loaded
candidate and original test module; it is not a retroactive execution trace.
Rust compilation, formatter, Clippy and full repository checks on this new
source tree have not been run by this preparation.

Local composition retained the real strict `write-tree` failure caused by an
unmaterialized, unchanged historical blob. The subsequent `--missing-ok` step
assembles verified tree metadata; it is not a complete checkout, an execution
result, or a historical default merge.

## Actual CI observations on the published input

The CI observations summarized below refer to the exact old `bbd56024` source
or a separately identified actual merge tree. Earlier Bellman failure logs from
the `2b538380` head are also retained as source-repair inputs, with their own
original identities. These observations do not transfer qualification to
the new six-path source tree or to the original owner's larger private union.
The snapshots are non-atomic observations of automatic attempt-one jobs.

The last included snapshot, number 13, was captured at
2026-11-20 06:40:36-37 UTC: 119 checks, with 67 success, 32 failure, 16 skipped
and four still running. Those four are the shared Cell owners job, Windows
release, Intel Mac test, and Architecture source. No new job, rerun, cancellation
or native computation was started for this evidence collection.

| Observed scope | Actual result |
| --- | --- |
| Research unit job | Ran 1,106; OK with one original skipped test. The three original RNG regressions passed. |
| GNU and Windows Bazel Clippy | Actual success. GNU release also succeeded. |
| Provider policy | Six selected cases and strict core Clippy passed; the final formatter step failed on the two preserved afterimages. |
| Learning artifacts source and merge lanes | Actual report verification succeeded, including ZIP CRC, log digests, report identity, source bindings and traceability. `qualified=true`; activation, release and independent acceptance remain false. Overlapping lane counts are not added together. |
| Windows owners | Eight groups, 98 unique exact selected cases, all passed. Zero retries and matching selection. The 43 Python collector tests are separate. |
| Windows process | Eleven groups, 77 unique exact selected cases, 73 passed and four failed. Full original group outputs bind all four failures to `FILE_DELETE_CHILD` refusal. Zero retries. |
| Windows required scope | Actual `FAIL_DECLARED_WINDOWS_SCOPE`; the process shard failed. |
| Neuron execution regressions | The old workflow failed with six missing-Pillow errors. The new dependency line has not yet been executed. |
| Bellman example | Source and merge lanes reported the same 18 Clippy diagnostics: 15 `expect`, two `unwrap` and one collapsible conditional. The new example has not yet been compiled or timed. |
| Spelling | 124 diagnostics originated in nine immutable binary archive fragments. All fragment bytes are preserved; exact custody validation precedes the existing explicit-path exclusion. |
| SDK conformance | Jest reported 46 of 47 passing. One new elicitation case timed out. The aggregate retained only the final 16,000 diagnostic characters, which exclude that case's section. The artifact therefore does not establish a production root cause. Baselines, deadlines and client-default semantics were preserved. |

Other full failures remain in the captured logs and diagnoses: the four Windows
Bazel test shards, filesystem isolation and private-state refusals, Mac FIFO
compilation, additional Mac/GNU full-test failures, B4 discovery failures,
Memory Cell helper metadata, musl linking, UI workflow path coverage and
AppContainer behavior. Passing Clippy does not qualify these failing tests.
Names outside an explicit test filter are retained as the original tool's
filtered counts, not reclassified as newly skipped required tests.

## HIA and historical coverage boundary

The complete Source04 preparation snapshot is dated
2026-11-20 06:29:32.030 UTC. It preserves the original graph's exact byte prefix
and has 78,803 nodes, no missing parent and no cycle. Its union includes every
historical protection name and pin from both audit owners:

- 7,665 live heads.
- 493 protected names and 524 historical or current protected pins.
- 7,171 ordinary branches other than main: 2,842 covered by Source04 and 4,329
  pending.
- Zero ordinary branches eligible for retirement against current main.

Source04 has no protected pin, current protected tip or member of the complete
protected descendant closure among its ancestors. The four source fixes add
zero historical branch coverage. At this snapshot main remained `732e934b`,
integration remained `0cee57ca`, and the safety ref still pointed to `bbd56024`.

This archived snapshot is preparation evidence. The final QA commit requires
a fresh complete-head/protection check and an exact expected-head update of
the safety ref. Only the original integration owner may advance integration or
main and perform any eventual ordinary branch retirement. Protected names and
their historical descendant histories remain outside that operation.

## Future conflict work, separate from these six source changes

The held group preserves reviewed ca77 work: four Goal/Queue keep decisions,
nine App Server decisions with five compatible future test files, and eleven
Supervisor decisions with one additive future socket test. The App Server
candidate preserves 101 original tests and 386 original assertions while adding
two missing tests. Its permission-root decision is an explicit semantic
resolution, not an assertion that the two historical policies are equivalent.

The Supervisor candidate adds only the original HealthSnapshot import and the
17-line real-socket case requiring a Drain acknowledgement. It retains all five
current tests and 13 original assertions, with 18 added lines and no deletion.
The complete recovery tuples, exact exhausted faults, real journal checks,
process isolation, strict fixture envelope and signed recovery quarantine are
retained. Same-process recovery is not presented as an executed operating-system
restart or a wall-clock expiry test.

These future candidates are archived as data. They have not been applied to
this source tree, compiled, run or counted as historical merges. The original
owner's canonical conflict inventory remains the authority for adoption and
later qualification. Existing stops on the rejected C2D production persistence
mutation and the unknown source-copy operation remain in force.

## Evidence format and publication limits

`evidence-index.json` identifies each evidence group and every member manifest.
Each group begins as a deterministic tar.gz containing only explicitly
selected original files. Its compressed bytes are divided into sequential
196,608-byte fragments. Each fragment is independently gzipped and stored as
`part-NNNN.bin.gz`, with a normal binary gzip header. The index binds stored
bytes, decompressed fragments, offsets, the full archive and every original
member using byte length, SHA256 and Git blob identity. No new spelling ignore
pattern is needed for this representation.

Run the read-only verifier from this directory:

```sh
python3 verify_evidence.py
```

It reconstructs and verifies every archive in memory, checks unique safe member
names and exact metadata, and reads every member without extracting or
executing it. This validates evidence integrity; it does not run product tests.

The selected evidence is explicitly a publication-safe subset. Original private
coordination prompts and signed transport receipts are excluded with their
identities and reasons retained. Their original frozen manifests are preserved
without claiming all private members are published. Original source, log,
artifact and fixture bytes have not been redacted.

The process artifact's complete 19,419,555-byte original ZIP was verified
against official metadata and all 22 member identities/CRCs. This package
includes its 20 original log/JSON/text members and the complete inventory; the
ZIP itself and its two actual helper binaries are deliberately not duplicated
here. That boundary is explicitly recorded as
`EXCLUDED_SIZE_BINARY_ARTIFACT_NOT_NEEDED_FOR_LOG_REVIEW`.
