# c895 original blocking CI terminal evidence

Original run **43048568477**, attempt **1**, ended `failure` at the API's `2026-11-11T16:27:29Z` update. Its 37 jobs are **20 success, 9 failure, 4 cancelled and 4 skipped**. The source is `c89540598693697577cda8cba31cb07f6ce65317`; the actually tested PR merge is `f0a379f3ae78e6cb01abcc6ac6458bacef23997b`. Both have tree `5a7c897a33e4eef48ea8f4bf52eaf48ea7c866ae`.

This packet retains 17 complete original job logs, complete terminal run and job API objects, earlier status observations, precise source and merge objects, a complete 14,053-leaf source tree, original artifact metadata, all parsing corrections and a standalone offline verifier. It includes the complete 2,677,695-byte original Mac Intel job log. There is no Mac full-job read gap in this packet. The cargo-deny job is API-successful, but its two original log reads returned `Transport closed`; both responses are retained and no cargo-deny case count is invented.

## Results and counting boundaries

| Original scope | Retained result |
| --- | --- |
| GNU and musl, each main command | 414 passed target labels, 2 failed and 167 skipped |
| GNU and musl, each separate operator command | 1 passed target label, separately reported |
| Windows shard 1 | 93 passed target labels, 51 skipped |
| Windows shard 2 | 108 passed target labels, 1 failed, 42 skipped |
| Windows shard 3 | 102 passed target labels, 45 skipped |
| Windows shard 4 | 109 passed target labels, 1 failed, 33 skipped |
| Mac Intel | 402 strict passed targets, 3 FLAKY, 4 failed, 3 timed out, 172 skipped |

These are Bazel target counts, not Rust case counts. Mac's original summary says 405 pass; that number includes its three FLAKY targets. Of the 402 strict passed Mac targets, 381 are marked fully cached and 21 are not marked cached. The parser retains original cache annotations, including partially cached shards, and separate command summaries. Repeated output in the post-job tail is not counted as a new attempt.

All complete displayed libtest blocks are checked against their original passed/failed/ignored summaries. Some parameterized display names occur twice in a block and its original summary counts both rows. Every occurrence and the non-unique display names remain in the audit; they are not asserted to be unique test IDs. On Mac, `core-all-test` reports 16 failed attempts out of 28 and prints 16 log paths, but the full job displays only seven corresponding libtest bodies. The other nine paths establish no per-case result in this packet.

The Mac memory target began a 429-test block and later timed out. Its retained partial output has 364 `ok`, one `FAILED` and nine `ignored` rows, with no complete libtest summary. The failure row names `product_v2_reports_peer_truncation_before_aggregation`, but this original block emits no detailed failure reason before termination. The historical b054 assertion text is not transplanted into this run. The evidence and paired-process targets likewise have incomplete output before their 300-second target timeouts.

## Original failure categories

The original v0.10 Fence action failed before checkout with `local_control_inventory_unavailable`; its specific historical subreason remains unknown. The SDK job failed its apt prerequisite after `azure.archive.ubuntu.com` DNS failures. Neither is counted as a native test failure. The independent later Fence v0.13 qualification does not change these original c895 outcomes.

GNU, musl and Windows shard 4 expose the two subagent-fixture routing failures. Windows shard 4 also reports `CreateProcessWithLogonW` error 1326 in two later attempts of the workspace-metadata case after an earlier pass. That login error is a separate observed boundary. Windows shard 2's unprivileged ordinary-host control succeeds; the elevated outside-delete assertion fails, followed by two shared-lock poisoning failures in the same process. Those subsequent poisoning errors are not classified as independent permission defects.

Mac has four failed targets: code-mode, Agentd's authbus text product, Agentd's supervisord product, and core-all. The code-mode failure reports an elapsed bound while waiting for concurrent results behind the blocked bulk writer. The supervisord case reports a read timeout. The authbus case reports a first delivery that unexpectedly required recovery with two delivery attempts. These error observations do not by themselves establish a deterministic implementation root cause. Its three FLAKY targets retain their original failed attempts and later target-level outcome.

The final required job rejects the original `needs.bazel.result = abandoned`; its complete `NEEDS` object also records an abandoned repo-checks aggregate despite the successful individual build-test job. The packet preserves this distinction. The four cancelled Mac ARM jobs have runner ID zero and no steps; no execution was observed, and their cancellation cause is unknown.

## Replay and recovery limits

Run from the extracted packet:

```sh
python3 records/verify_package.py
```

It checks the complete member inventory, every byte/SHA/Git blob, terminal metadata, all raw bindings, the full source-tree Merkle root, and reruns only the offline text parser. The seven original test-job records must match the frozen audit exactly; all complete displayed libtest summaries and all command-level target summaries reconcile. No Git, Rust test, host, workflow, model or provider request is executed.

The initial reader omitted one cached Mac target because the original raw payload contains an interior UTF-8 BOM immediately before its GitHub timestamp. The correction strips that structural marker for parsing only. Two other interior BOMs occur in Linux diagnostic lines. Original bytes, the earlier reader/report, its over-narrow inventory assertion failure and the corrected inventory are retained in `audit-preparation-history/`. Two previously inspected Windows diagnostic/status interleavings also remain explicitly pinned; no test status was changed.

All eleven Bazel execution-artifact metadata objects are retained, including Mac artifact `13872750986`, but their ZIP payloads are not included or claimed recovered. The 34-case Private qualification is a separate original run and separately published package, pinned in `QUALIFICATION_SUMMARY.json`. MEM, Architecture, Windows-current, the five-case campaign and source-only gates belong to separate scopes and are not merged into these totals. The original model/owner/cold-recovery/adoption blockers remain unchanged.
