# Native qualification failures and proposed repair — 2026-10-24

## Observed results

Two completed hosted runs are retained here. They are failed qualifications; neither ran the pretrained native model probe.

| Exact source | Run | Run / pass / fail / skip | Test wall time |
| --- | --- | --- | --- |
| `c11a9f7fe85f1bbc5e008ac02b5639e1e8502a92` | [40102780899](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/40102780899) | 510 / 506 / 4 / 13 | 95.272 s |
| `f2144a2451e0ca03f8c91e0c30755970cc1e4867` | [40103922428](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/40103922428) | 510 / 507 / 3 / 13 | 99.578 s |

The f214 blocked-stdin fixture repair passed in the second run (0.330 s). Each remaining failure occurred on both configured nextest attempts. Configured retries are not additional independent test cases.

## Three remaining failures

1. `real_agentd_remember_recall_correct_and_forget_revalidate_physical_sends`: `current projection rows did not match their generation receipt`.
2. `agentd_product_host_commits_through_canonical_cognitive_store`: `cannot terminalize lease with unresolved local occurrences: occurrence:product-writer:1`.
3. `agentd_product_host_recovers_exact_cut_into_fenced_writer_generation`: `SQLite recovery is indeterminate: the complete immutable file identity was not established`.

## Source analysis and candidate

The graph writer uses `revision_facts_v1`, introduced by migration 0014. It persists generation receipts and immutable revision facts rather than another full graph copy in legacy `kg_nodes` / `kg_edges`. The E2E oracle still counted those legacy tables. The candidate independently reconstructs the generation's selected revision heads, counts verified and active entity / relation facts, and requires the storage marker. It preserves exact source checks, immutable fact-set counts, physical tool receipt comparisons, canonical generation / publication digests, correction, recall, restart and forget assertions.

The first product-writer fixture admitted a queued occurrence and immediately released its lease. The actual lease correctly refuses that transition. The candidate renames that fixture to describe queue persistence and release fencing, asserts the exact failed release and still-queued state, then explicitly rolls the undispatched occurrence back before release. This is not a successful external action.

Positive canonical mutation coverage remains in the separate exact-cut host test: real remember, correct and forget operations, committed outbox status, canonical / durable provenance binding, invalid mutation rollback, live authority revocation and persisted reopen assertions are retained.

The recovery fixture dropped its pool without awaiting SQLite connection shutdown. The descriptor-bound recovery path rejects identity drift, including asynchronously changing sidecars. The lower-level exact-cut recovery test already awaits pool close and passed in both hosted runs (0.998 s and 1.381 s). The candidate exposes a consuming `CognitiveStore::close` that awaits the shared pool before the handle releases its fence, uses it before host recovery, and exercises the same public lifecycle in the existing positive recovery / reopen test. Other cloned handles retain their fences. The race diagnosis is source-supported; successful repair still requires execution.

The candidate changes 4 files, 66 additions and 22 deletions. It does not alter authority checks, recovery guards, runtime budgets, timeouts, model recipes or test skipping. It has not yet been Rust-tested or finally formatted in this evidence capsule. Root qualification must record subsequent results separately.

## Preserved data

- Original artifact ZIPs retain their GitHub SHA-256 digests; all 14 ZIP members were checked against the archives and recorded by path, size and SHA-256.
- Decoded job logs were saved as UTF-8 text. Their local hashes identify those decoded files, not an independently signed original HTTP representation.
- Exact f214 baseline files, candidate files, a binary-capable source patch and pre-test manifest are included.
- Artifact member `source.txt` identifies the exact commit and tree. Both hosted runs leave an empty final worktree diff and skip the model-runtime / model-probe stages after the scoped tests fail.
- Signed temporary download URLs are not retained.

All eight overall memory research blockers remain open in this capsule. These are native engineering diagnostics and a reviewable candidate, not future-task, compression, fission or production-acceptance evidence.
