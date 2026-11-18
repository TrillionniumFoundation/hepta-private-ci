# Rust consolidation checkpoint — 2026-11-18 UTC

**Consolidation is incomplete.** This checkpoint completes the recorded branch/parent inventory, advances reviewed source fixes and ten original histories, and preserves the protected HIA/Cell families. It does not establish that every remaining source family is audited or that this candidate may be merged into `main` before the required checks pass.

## Scope and ancestry

The pre-publication advertisement contains **7,487 branch names**: **7,234 ordinary consolidation candidates**, **252 protected HIA/Cell names**, and `main`. The initial complete parent graph contains **77,392 commits**. Every initial parent was present; the graph digest and pinned branch chunks are recorded here.

At source commit `3c44b57a5ff75d9321051202c7768672a0553255`, **1,953 ordinary names** are represented in ancestry and **5,281 ordinary names remain pending**, corresponding to **1,839 independent frontier heads**. This commit has **40,669 ancestors**. The report commit itself adds no original branch history. See [ancestry.json](ancestry.json), [inventory/manifest.json](inventory/manifest.json), and [pending-frontier-heads.txt](pending-frontier-heads.txt).

All **258 protected pins in this audit's initial/current union** are absent from candidate ancestry, as are the HIA and Cell marker roots. Protection is based on the existing exact-name classification plus commit/PR ancestry, rather than an indiscriminate substring filter; twenty older ordinary histories containing `hia` retain their earlier classification. The latest advertisement detected one external advance of `codex/hia-union29-20261116-a90d` to `bbb534d8be9098c041d5f3dd1ca1214fbcc2fd8a`; its new commit descends from the HIA root and remains protected. No protected ref has been written by this checkpoint. See [protected-heads.json](protected-heads.json) and [inventory/external-ref-changes.json](inventory/external-ref-changes.json).

## Integrated source and history

The existing validation line `d2422433dccc232e10256973df68823331928a28` contributes 118 original ancestors beyond the prior PR head `5ec371387c47fe1af3cb511c076867ff2678f940`. Forward cleanup restores 25 original files and deletes 40 temporary diagnostic/source-transfer files, preserving that history. The exact 65-path plan is in [cleanup-plan.json](cleanup-plan.json). The 110 retained delta paths were inspected separately; their review is in [retained-delta-review.json](retained-delta-review.json).

- **Objective → NDU:** derive exact unit-mass Q32 weights with integer proportional allocation, largest remainders, and stable axis ties. Preserve the admitted Objective and receipt; reject nonempty zero-total weights through the existing error type. The original half-weight fixture remains. Five end-to-end regressions cover normalization, zero axes, a real Pareto frontier, whole-receipt reorder invariance, and invalid baselines.
- **Prompt Optimizer:** call the existing tuple, registry snapshot, and realization validators before sealing candidates; require the selection-grammar digest and all eight realization/model bindings. Six negative tests recompute outer digests to prove intrinsic input validation rather than incidental checksum rejection.
- **Agentd model material tests:** retain all eight original fixtures, assertions, request limits and operation deadlines while separating independent scenarios into named native tests. This change is awaiting native Agentd qualification; it does not resolve the separate 500 ms next-use owner deadline by assertion.
- **Canonical consumer test lint:** retain its missing-profile panic and input assertions while removing a denied `expect` call.
- **RBE PR coverage:** add the missing helper-directory trigger and a read-only PR job for offline helper/tool-supply/metadata tests. All existing image build, publish and native jobs, their permissions and their source/ref/run conditions remain byte-for-byte unchanged.

[reviewed-branches-01.json](reviewed-branches-01.json) and [reviewed-branches-02.json](reviewed-branches-02.json) record ten additional original heads. Three reviewed fixes are already represented semantically in the stronger current microbatch/WAL source. Seven dated evidence packages contribute **118 original files byte-for-byte** plus four storage files. Three oversized historical paths are preserved losslessly in deterministic gzip carriers with original paths, modes, lengths, SHA-256 and Git-blob identities; each original byte stream was restored and checked. Old failures and no-native statements are retained. Archived programs are not invoked. No blob-policy limit or allowlist changes.

## Validation at this checkpoint

| Check | Observed result | Scope |
| --- | --- | --- |
| Locked native tests for eight packages | **540 passed, 0 failed, 2 existing ignored measurement tests** | Prompt Optimizer, Intelligence, Objective, NDU, Context Compiler, Cognitive Types, Cognitive Read, Cognitive Store; Rust 1.96.0 on Linux GNU |
| Caller closed-set verifier | **PASS** | 1,645 boundaries and inventory entries, 819 protected files, 7,672 Rust files scanned; authorityGranted=false |
| Scoped `just fix` and final `just clippy` | **Exit 0** | Intelligence and Prompt Optimizer; one existing dependency advisory remains |
| New RBE workflow's exact offline commands | **25 passed, 0 failed** | 9 helper, 13 tool-supply and 3 metadata regressions; no OCI image build/publication qualification |
| Four B4 classes after restoring original checkout inputs | **28 passed, 0 failed** | Resolves the four setup errors from the initial incomplete-checkout run |
| Complete B4 rerun | **Running when this report was assembled** | Pinned pre-report source tree `ebd406b6ac3c88d5d76ccf82407dcbd54eeea360` |
| Agentd/worker native validation | **Pending** | Local V8 preparation was blocked by network proxy 403 before tests; an isolated ROG attempt is being prepared |

Full logs and exact commands are retained in [validation/artifact-manifest.json](validation/artifact-manifest.json). The complete 766,890-byte caller receipt is stored as a lossless gzip file; its original length and SHA-256 are recorded. Earlier preparation failures and the initial incorrect helper invocation are retained separately, without being relabeled as passes. The complete B4 result and Agentd result must be added when observed.

## Remaining merge gates and work

`main` remains at `732e934ba496d90fbe042b8d41d479ef901643e5`. Required `CI required` and `Architecture required` protections remain in force. The prior PR head had a failed required CI result; successful scoped tests here do not supersede platform checks for the new head. Known unresolved prior failures include the Agentd next-use evidence deadline, Windows peer-identity and private-state positive-path qualification, macOS PTY/peer timing, musl Core timing, a TypeScript SDK timeout, and the cargo-deny gate. Existing CodeQL findings and review threads are not dismissed or suppressed by this work.

The full 1,849-head metadata audit, including 190 heads with multiple merge bases, is summarized in [frontier-metadata-summary.json](frontier-metadata-summary.json). Metadata coverage is not content review. The remaining frontier needs real source integration and conflict resolution; unused `ours` merges or deletion of unintegrated refs would not satisfy the requested consolidation.

No ordinary branch is deleted by this checkpoint. Deletion is eligible only after its exact fresh tip is reachable from successfully merged `main`; protected HIA/Cell names remain excluded. The prior published PR description is preserved in [pr6293-prior-checkpoint.md](pr6293-prior-checkpoint.md) so earlier qualifications and limitations remain reviewable.
