# Rust consolidation: graph and CI audit, 2026-11-16

This checkpoint records reviewed history and source repairs for `TrillionniumFoundation/hepta-private-ci`. The requested final state, with `main` as the only Rust branch and the newly added HIA branches preserved, remains in progress.

## Scope and exact source

| Item                                                | Recorded value                             |
| --------------------------------------------------- | ------------------------------------------ |
| Remote branch snapshot                              | 7,294 branches                             |
| Protected HIA and dependent branches                | 63                                         |
| Other non-main branch names                         | 7,230                                      |
| Original non-HIA tips retained in this candidate    | 1,727                                      |
| Original non-HIA tips still outside this candidate  | 5,503                                      |
| Main at the audit snapshot                          | `732e934ba496d90fbe042b8d41d479ef901643e5` |
| Published source before this checkpoint             | `285e971b3af3a93a79169b56a42263069e473057` |
| Reviewed source commit                              | `d3746789d49ca8a4bb5600e0c6fbe682ef5f1765` |
| Exact reviewed source tree                          | `751e50a0172e467176be68a1331519c8ea171307` |
| Reviewed history head before audit artifacts        | `23a7b1bceda59d792762833920e0e16ed2b8ea5f` |
| Main merge and branch retirement in this checkpoint | Pending; no branch deleted                 |

Coverage counts record ancestry of exact original tips. The source reviews and executed checks below state their own scope. The complete initial graph has 76,776 commits. The graph package separately records later candidate and HIA objects, with the exact walk roots for each closure.

The protected set follows HIA ancestry as well as branch names. Two protected refs advanced independently during the audit: `codex/hia-example-validation-oracle-20261116-9f0b` and `codex/hia-union29-20261116-a90d`. Both original and observed tips are retained in the exclusion evidence. The candidate and incoming reviewed histories exclude both versions and the two protected lineage markers. No protected ref was reset, merged or deleted by this work.

## History retained

This checkpoint adds 32 ordinary two-parent merges after the published source. Their original incoming parent identities and exact resulting trees are recorded in the merge receipts.

- Twenty-seven reviewed histories add 972 source/evidence paths while preserving every existing baseline path. Six oversized evidence files are represented as ordered, lossless parts within the original 512,000-byte blob limit. Their original bytes, digests, restore checks and negative restoration checks are retained.
- Three further histories retain the MEM5 read-only verification receipt and readiness wording, and reconcile an older browser guard with the stronger current assertions.
- Two Rust histories retain original nonterminal-readback and claimed-state fixes, plus macOS fixture canonicalization. Each conflict was resolved using a complete incoming-change comparison. The entire 55-file repair tree is unchanged by those two merges.
- One malformed intermediate historical patch is explicitly recorded. Its corrected final source is retained; no successful-build claim is made for the malformed intermediate commit.

The full classification includes active JavaScript and policy text. Six old tips that change the blob-size allowlist remain held for review. An ordinary merge preview that reports a conflict is retained as a conflict; it is not counted as a successful merge.

## Source repairs

The source overlay manifest pins all 55 paths, original blobs and proposed blobs. The parent preimages and complete resulting tree were independently checked before publication.

| Area                                 | Change and preserved behavior                                                                                                                                                                                                             |
| ------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Original state ownership             | Move the unique boxed owner out of a private slot before awaiting. Return the same owner on lease drop, retain failure state, reject contention, and keep poisoned state closed.                                                          |
| Source and caller guards             | Update the exact source contracts and authenticated caller inventory to the repaired ownership/API shape. Preserve the original forbidden forms, required predicates, ordering constraints, verifier implementation and formatter policy. |
| Test helpers and feature compilation | Propagate fixture failures through typed results and qualify two existing error variants in the feature-gated writer assertion. Preserve all 258 helper assertions and the original test/ignore attributes.                               |
| Provider fixture                     | Canonicalize candidates, masks and complete routes by the same candidate ID before digest and registry construction. Keep each outcome, edge and selected activation bound to its original ID.                                            |
| Material fixture stack               | Retain heap ownership through constructors, panels, hosts and completion instead of moving large fixture values through nested debug futures. Preserve shutdown and join order.                                                           |
| Control transport                    | Accept `NotConnected` only from half-close after a successful complete frame write. Keep partial-write failures, other shutdown errors, frame limits and the original I/O deadline.                                                       |
| Shutdown diagnostics                 | Include the existing bounded task error in lifecycle diagnostics. Keep the failure latch, queue bound, cancellation and failed exit behavior.                                                                                             |
| Platform fixtures                    | Canonicalize the crash fixture root, inspect retained lock handles correctly, and make the PTY readiness marker impossible to satisfy through terminal echo alone.                                                                        |
| Platform CI inputs                   | Restrict Linux-only fixture methods appropriately, select GNU Wine only on the GNU path, disambiguate Windows test imports, and add exact custody for one original binary evidence shard.                                                 |

## Executed checks and their limits

| Check                            | Result                                                            | Exact scope                                                                                                                                                                                                     |
| -------------------------------- | ----------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Original full B4 suite           | **PASS: 1,315 tests**                                             | Clean independent checkout of `d3746789`; all 55 input hashes unchanged.                                                                                                                                        |
| Complete caller proof            | **PASS: 1,645 boundaries, 7,504 Rust files, 819 protected files** | Same exact source tree. The verifier implementation is unchanged; the parallel execution was previously compared with the original CLI.                                                                         |
| Scoped Agentd feature Clippy     | **PASS, with existing warnings**                                  | `just clippy --locked -p codex-hepta-agentd --features qualification-cognitive-write`. Source hashes unchanged. The source bridge records the six fixture/Windows-test differences from the complete candidate. |
| Linux lock fixtures              | **PASS: 19 tests**                                                | Recorded baseline plus the two exact lock-fixture repairs; their bytes match this candidate.                                                                                                                    |
| Linux crash recovery             | **PASS: 2 tests**                                                 | Recorded baseline plus the canonical crash-fixture repair; its bytes match this candidate.                                                                                                                      |
| Linux PTY suite                  | **PASS: all 28 tests**                                            | Recorded baseline plus the exact readiness repair; its bytes match this candidate.                                                                                                                              |
| Native v4 Agentd selection       | **FAILED: 102 passed, 6 failed**                                  | Earlier recorded input closure; original provider-binding and stack failures are retained.                                                                                                                      |
| Native v5 Agentd selection       | **FAILED: 62 passed, 16 failed, 1 timed out**                     | Earlier recorded input closure. The 16 registry failures motivated the route-order correction; the separate timeout remains under investigation.                                                                |
| Native v6 original failing cases | **FAILED: 9 passed, 1 failed, 16 timed out; 26 run**              | Eight control tests passed. Original 8 MiB stack, 60-second timeout, four test threads and zero retries were retained.                                                                                          |
| Hosted required checks           | **Pending on this checkpoint**                                    | The previous published head failed `CI required`; `Architecture required` passed there.                                                                                                                         |

The ninth native-v6 pass is the panel future-layout diagnostic. All sixteen provider-family nonpasses are 60-second timeouts; the separate deep-readonly case fails after 48.641 seconds with an uncertain original C Observer completion. The prior registry-binding assertion was not emitted in this run. The original 13:19:57 UTC CI-pack snapshot records the run as still active; its separate final addendum retains the completed outcome.

The native-v6 source bridge compares 7,748 Rust/manifest inputs with the complete candidate: 7,742 match, and the six differences are four separately tested lock/crash/PTY fixture files and two Windows-only test import files. This bridge supports the stated Agentd compilation scope. It does not turn a Linux subset run into complete Windows or macOS qualification.

Bounded native macOS experiments demonstrated the post-write `ENOTCONN` ordering and the terminal-echo readiness issue. They were standard-library experiments, not the full Rust suites, and they do not prove the cause of every earlier hosted macOS failure.

## Unresolved admission and security work

Four positive Windows functional tests still lack a qualified elevated admission path. The retained native ACL/MIC experiment has a real parent-delete counterexample. The production refusal and every original positive assertion remain in place. The large Windows aggregate also has 159 ordinary-merge conflicts, including 85 Rust files; it has not been used as a replacement source tree.

The previous CodeQL check has 23 annotations: 13 reported high and 10 reported critical. The exact analysis has 195 total results. The audit package retains the original SARIF, alert identities and source-level reviews. Buffer initialization, fixed test material, protocol counters, account metadata, explicit login instructions and actual diagnostic disclosures are reviewed separately. No alert has been dismissed and no CodeQL policy has been weakened.

All 23 check annotations now have individual source-level review receipts. The CLI's partial-key formatter, duplicated authentication diagnostics and unbounded upstream authentication error output require remediation. Existing non-HIA histories are being searched for relevant fixes. Reported severity alone is not a claim that every annotation is an exploitable defect.

## Evidence and continuation

The artifact manifest lists each stored file, Git blob, byte count and digest. Compressed evidence is lossless; split volumes preserve byte order and the original digest. The earlier proof package retains its historical source identity, and the final 55-file source proof has its own receipts. Original failed runs remain available alongside later results.

The next main merge requires the remaining source/conflict reviews and the required checks on the actual final head. Before retiring any branch, refresh the protected set and verify that the exact live non-HIA tip is contained in the new `main`; use the observed ref as the deletion lease. The final live branch list must independently demonstrate the requested state.
