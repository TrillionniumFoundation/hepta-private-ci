# Independent CI and local follow-up qualification evidence

## Scope and immutable source identities

- Hosted run **40144148314**, job **121021816101**, PR **3787**: head `f6b97dca1a8621e96a58d98dfb8c9dcc7b4b5ee5`, tree `afd6e2286bb48206fff7d38b4fe85bb63f1e2565`. Both values are independently retained in the original artifact `source.txt`.
- The hosted command covers three crates (memory, agent-protocol, agentd). Local attempts002–005 cover six crates, including arg0, neuron and cognitive-store. Their counts must not be treated as the same test population.
- This package preserves completed historical runs only. No tests, Rust builds, model executions or remote writes were performed during collection. Original source and earlier evidence were not edited.

## Exact outcomes

| Run | Exit | Executed | Passed | Failed | Skipped | Test time | Total command time |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Hosted CI f6b97dc | 100 | 510 | 509, including 1 flaky | 1 | 13 | 96.767 s | Full timestamped job log retained |
| Local 002 | 101 | 0 | 0 | Compilation blocked | No test run | Not started | 42.550 s |
| Local 003 | 101 | 0 | 0 | Compilation blocked | No test run | Not started | 95.609 s |
| Local 004 | 101 | 0 | 0 | Compilation blocked | No test run | Not started | 79.047 s |
| Local 005 | 100 | 651 | 650 | 1 | 13 | 50.455 s | 97.416 s |

**Actual pretrained-model calls are zero in every run represented here.** The hosted evidence-driver regression suite separately ran 3 tests and passed; it is not counted as 510 Rust tests or as model execution.

## Hosted CI: retain both the failure and the flaky retry

- `agentd_product_host_recovers_exact_cut_into_fenced_writer_generation`: failed both attempts (0.913 s and 0.651 s), at the post-writer-lease full-anchor equality assertion on line204. Complete original left/right anchors are retained.
- `killed_agent_recovers_same_turn_then_dispatches_queue_once_while_peer_stays_live`: attempt1 failed after 9.080 s with `queued turn reached unexpected terminal state Interrupted`; attempt2 passed after 20.874 s. It remains explicitly classified as flaky.
- The remember/recall/correct/forget product fixture passed in 17.758 s; the queued-intent/fenced-release fixture also passed. No HEPTA_FLEET_ROOT or Broken pipe error occurs in the hosted job log.
- Job steps11,12,13 were **skipped**: actual daemon-probe build, measured CPU runtime installation, and fixed fresh training/control-socket probe. No trained-model claim follows from the unit/integration pass count.

## Local attempts002–005

- **002:** compilation stopped with 8 E0432/E0599 diagnostics for missing shadow types/methods. Original cache-mtime observations and byte-preserving timestamp-refresh records are retained. Zero tests ran.
- **003:** compilation stopped on 14 E0659 macro ambiguities in neuron shadow tests. The explicit macro-import correction is preserved with before/after source bytes checked against the frozen maps. Zero tests ran.
- **004:** compilation stopped on 3 unresolved pretty_assertions imports and a missing ProductionCognitiveMutation trait import for forget_with_kg. Those compile defects were corrected before005; zero tests ran in004.
- **005:** 651 tests ran. Every one of the14 cases that failed in local001 now has an independently matched PASS line; the per-case mapping is in comparison/attempt001-to005.json.
- The single005 failure is `shadow_delivery_is_immutable_owner_bound_and_late_withdrawal_closes_owner`, failed twice at native_memory_tick_owner_tests.rs:80:48. Original error: `Store(Invalid("source content must exactly bind the product mutation input"))`. Its source content did not bind the forget reason, so the actual store rejected the test mutation before successful tombstoning.
- Root reports source corrections applied for the next qualification; this snapshot ends at005 and makes **no claim that the new withdrawal fixture or the complete six-crate gate has passed**.
- Each local run retains its complete before/after source maps (9,704 files) with equal byte hashes. Source changes between attempts are listed separately; within-run stability is not conflated with cross-run identity.

## Raw bytes and verification boundaries

- All artifacts returned by the run-artifact listing are preserved: one original ZIP, artifact12581120131, 37,502 bytes. Its SHA256 `b8a273be9491781e0f497b0f6666fb14fb01780bad63b722b852e29d28d9ad70` matches the GitHub-published digest. All7 ZIP members were safely extracted with byte hashes recorded.
- Full job logs are returned by the GitHub connector as decoded text. The exact UTF-8 re-encoding, including BOM, is preserved as job-121021816101.decoded-utf8.log. Its hash identifies that saved representation; it is not mislabeled as an independently authenticated original HTTP-body hash.
- Original artifact scoped-tests.log keeps ANSI bytes intact. The separately named ansi-stripped log is derived for readability. Retried-attempt records preserve original failure and retry blocks.
- Local logs, receipts, source maps, candidate patches, runner scripts and available cache observations are copied without modification. Original tool-install receipts are included.
- The earlier517,404-byte local001 archive remains unchanged: SHA256 `1961117cc071d571779608e850f4caf6647de1f5c3e6c6e1471624fab8913e2e`.
- archive-members.json contains SHA256/size for every payload member. The external manifest binds the final deterministic tar.xz; all archive entries are relative regular files with fixed uid/gid/mtime and read-only modes.

This archive distinguishes final failures, flaky retries, compilation-only attempts, and real executed tests. It does not establish pretrained-model success or full memory-system blocker closure.
