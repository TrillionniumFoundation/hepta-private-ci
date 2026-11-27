# Rust consolidation follow-up from b3

This batch adds two real history merges and five maintenance files to the existing PR. It is ready for new-head CI, and is **not qualified for main**. Main remains `732e934ba496d90fbe042b8d41d479ef901643e5`; no branch has been deleted. HIA references are unchanged.

The source commit is `2aadf0f1ebebebdb8772e8b6a5f429754e8ada93`, tree `e4f470c7a0f9e0b4fced446b548943c13da5bf83`. The following QA commit only appends this evidence directory. [SOURCE.json](SOURCE.json) binds all eleven source paths, the ordered parents and the intermediate trees. [VALIDATION.json](VALIDATION.json) records the actual tested inputs, results, remaining failures and protection boundary.

## Real merges and behavior

| Original tip | Published merge object | Change retained after conflict review |
| --- | --- | --- |
| `233e77ececa9f144bf5d538a24ff060f92f34fd3` | `309c1f8916998c1b768127c6519dfb953fffde9b` | Seven test-only V8 mutex lines; current production guards, signed recovery decisions and later APIs retained. |
| `6fb3e33043b3b3220c035943caa0da115be83d36` | `2aadf0f1ebebebdb8772e8b6a5f429754e8ada93` | Original Bazel alias engine and 35 cases, adapted to the current wrapper; read-only lock verification workflow. |

Both merges ran the default merge and resolved actual conflicts. No `ours` strategy or parent-only attachment was used. The second merge was replayed against the actual newer maintenance parent `0aec1013d65ec5ce45d1aa0cf973cc9f971023a5`, and its full 59,490-leaf tree equals that parent plus the five reviewed Bazel paths. The six newer paths, including the V8 fix, were retained exactly. The original 233 review covers 21 commits and 17 ordinary refs; the 6fb review covers ten commits and nine ordinary refs. These are candidate-history coverage counts, not retirement permission.

The maintenance child checks out the actual deterministic operator merge commit and verifies HEAD, tree, ordered parents, index and tracked contents before and after qualification. It keeps the complete base-to-merge whitespace gate. Seven real-Git controls cover the correct checkout and rejection of wrong source, conflicts, whitespace, wrong HEAD and later edits. The original workflow fails four of those seven controls.

The Windows junction fixture now builds `System32` and `cmd.exe` as separate path components, preserving its arguments and every assertion. Native success is pending. A separate same-runner diagnostic repeats the unchanged six AppContainer cases under a fresh owned runner-temp location; original job failures remain failures. The location change can affect paths, ancestors and volumes, so it does not by itself identify a single ACL cause. The original three jobs remain byte-identical, and neither credentials, tokens, ACLs nor sandbox environment flags are changed.

## Validation and limits

- V8: six original tests pass; the same original binary also passes all six cases in one process with six test threads. All 137 compiler dependency records bind 1,435 inputs with none missing. The fifteen repository inputs match the final source tree.
- Bazel: 35 original analysis tests pass, zero failures or skips. The current wrapper loads 216 distinct targets across eleven packages. Loading is not configured analysis or native Rust execution. All 33 explicitly recorded repository inputs match the final merge; the forty total bindings are not a complete dynamic action trace.
- Path utilities: original Linux tests pass 9/9 and Windows-target compilation succeeds. Compilation does not establish native Windows behavior.
- The operator Git controls pass 7/7. Original scoped fixes and formatters complete, final source bytes remain bound, and no tests were rerun after final formatting for these source waves. Changed-source spelling, whitespace and size checks pass.

Original preparation failures are retained, including sparse formatter/Bazel inputs, the regression harness's missing source variable, and local filtered-object transport failures. The final remote Git object was verified against its canonical SHA before local import. These failures are not relabeled as test passes.

## Existing CI remains a real barrier

On b3, Windows Clippy and release build, cargo-deny, the contract gate and operator exact-source qualification succeed. All four Windows Bazel shards fail: twelve unique hard cases comprise one junction fixture, nine FILE_DELETE_CHILD boundaries and two non-Unix AuthBus owner refusals. Four distinct natural retry flakes are recorded separately. The native private-artifact job is 8/9; all six original command-location observations still fail.

The Linux musl job fails the original next-use evidence timing case, while Linux GNU fails read-only cold orphan inspection with `WriterUnavailable`. Their actual checkout is GitHub merge `20a13b578ff7ade9bab63d38a8d4454251f42c59`, not a claimed exact b3 checkout. macOS ARM is failed but its specific cause is unconfirmed because the original log could not be retrieved; Intel is still running at the archived snapshot.

The operator deterministic-merge job remains failed. Its exact remote error text was unavailable. Local reproduction of the unchanged full-diff whitespace gate reports 294,828 diagnostics across 1,057 paths. This batch fixes checkout identity and preserves that gate; it does not erase historical evidence or claim to resolve those whitespace diagnostics. A successful exact-source receipt is DENY_ALL and does not authorize production activation. Every result remains bound to its actual source and run; the new head must run its own CI.

## Branch protection and remaining work

The November 22, 2026, 11:16:17 America/New_York snapshot contains 7,914 refs. Protection covers 558 refs and 1,496 nodes, including 414 names without HIA. All old 556 protected refs remain unchanged; only two new HIA refs were added. The candidate's complete 45,084-node ancestry has no intersection with the known protection set and does not reach STOP. The historical 551st pin identity is still unresolved and is not silently filled by guessing.

Main has 33,794 ancestors. No current ordinary branch tip is in that ancestry, so the retirement list remains empty. The 151 Neuron merge, AuthBus platform-contract correction, complete ec6 history and other ordinary histories are not included in this batch. Full-repository audit, main consolidation and final branch retirement remain incomplete.

Automatic approval previously rejected C2D persistence commit `d783273c25b3164f5f632482cb7b017fdcb9d756` for **cybersecurity risk**. Its payload, descendants and equivalent workaround remain stopped. The known signed/File::lock stale-history issue is not declared fixed. This boundary is not generalized to unrelated Windows work.

## Retained evidence

[ARCHIVE-MANIFEST.json](ARCHIVE-MANIFEST.json) lists ordered archive parts and every member's size and SHA-256. Decompress each numbered `evidence.tar.gz.part*.gz` file, then concatenate the resulting bytes in filename order to recover one gzip-compressed tar archive. The complete archive and every member were read back and verified. Each decoded part is at most 491,520 bytes, and every stored gzip wrapper is below the original 512,000-byte blob limit. An initial raw shard caused Codespell to decode binary bytes as text; that failed attempt is retained. Standard gzip wrappers preserve every decoded byte and leave all spelling rules unchanged.

The archive contains the original merge decisions and patches, native logs and receipts, source input bindings, failed attempts, independent reviews, branch snapshot and protection metadata, and the previous PR description. Reproducible full-tree/parent inventories and local Git indices are listed with hashes rather than duplicated. The 65 MB whitespace diagnostic stays local with its exact hash and reproduction command; its classification is included and the failure is preserved. No claim is made that omitted local artifacts are embedded in the archive.
