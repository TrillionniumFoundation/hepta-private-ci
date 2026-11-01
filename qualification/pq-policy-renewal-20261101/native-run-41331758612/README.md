# Native AuthBus qualification for candidate `cd3c1b860f2b0f05c24bfb8d4b5da6ba7f99704a`

All four jobs in [run 41331758612](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/41331758612) completed successfully on attempt 1. Each job ran the exact 13 dispatcher controls and 3 text product controls listed in `expected-tests.json`, with no selected skip and no test retries. The original scoped linter and formatter also passed without changing the tested source.

## Source identity

- Candidate source: `cd3c1b860f2b0f05c24bfb8d4b5da6ba7f99704a`.
- Source tree: `8010f83386f4effdcd6123aad99f1ab3775709e3`.
- Stacked base: `0f7c63418a7eec6cff5e4348e8cdc733850f8386` (#4552).
- Prospective merge: `7aaccdc384b36706b7d89a81bf87151c26a2bf0f`, with parents `[base, candidate]` and tree `8010f83386f4effdcd6123aad99f1ab3775709e3`.
- PR: [#4558](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4558), left draft and unmerged.
- This evidence commit is a child of the qualified source solely to retain records. Its additional evidence files were not part of the tested source tree. The candidate branch remains at the source SHA above.

The source and merge lanes executed separately on x64 and ARM. The CI executor checked the commit, tree, parents and clean state before and after every command; merge lanes also recomputed the merge tree from the actual base and source parents.

| Environment and checkout | Job | Dispatcher passed | Product passed | Selected skips | fix / fmt / identity |
| --- | --- | --- | --- | --- | --- |
| ubuntu-24.04-source-head | [`124923994371`](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/41331758612/job/124923994371) | 13 / 13 | 3 / 3 | 0 | pass |
| ubuntu-24.04-base-merge | [`124923994608`](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/41331758612/job/124923994608) | 13 / 13 | 3 / 3 | 0 | pass |
| ubuntu-24.04-arm-source-head | [`124923994538`](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/41331758612/job/124923994538) | 13 / 13 | 3 / 3 | 0 | pass |
| ubuntu-24.04-arm-base-merge | [`124923994477`](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/41331758612/job/124923994477) | 13 / 13 | 3 / 3 | 0 | pass |

The original workflow uses Rust 1.96.0, the unchanged Cargo.lock, the repository's `just test`, `just fix` and `just fmt` entry points, and the existing native prerequisites. The selected test commands pass `--retries 0` and `--test-threads=1`. The source workflow and execution scripts are available at the qualified commit.

## Evidence provenance

Each lane contains five `*.recovered-stdout.log` files, five `*.reconstructed-receipt.json` files, and one `verified-summary.json`.

The command outputs were recovered from the complete GitHub job log by removing only the GitHub runner's timestamp prefixes and selecting the exact command-output boundaries. Each recovered output's byte count and SHA-256 independently match the original execution JSON printed by `scripts/hepta_ci_exec.py`. ANSI bytes and final line endings are retained. Empty formatter output is an actual zero-byte log, with its successful command result in the receipt.

The receipts were reconstructed from that original emitted JSON using the pinned script's `indent=2`, `sort_keys=True`, and final-LF serialization. The original artifact receipt files were not directly downloaded, and their disk bytes were not compared. The reconstructed receipt values were compared with the original JSON in the full job log. `manifest.json` records hashes of these reconstructed files, not a claim of directly downloaded receipt bytes.

The derived lane summaries record command arguments, source identities, original output hashes and counts, all observed selected test names, and the final GitHub job steps. Full job logs are linked by job URL and their locally retrieved byte counts/hashes are recorded; the large full logs are not duplicated here. Actions artifact digests, where listed in the manifest, identify GitHub's uploaded archives; those archives were not downloaded for this verification.

## What the product controls cover

| Exact product test | Authentication profile | Scope |
| --- | --- | --- |
| `signed_text_crosses_real_queue_once_and_current_trust_rejects_invalid_ingress` | `Ed25519V1` | Retained classical signed-text positive and invalid-ingress regression. |
| `pq_signed_text_crosses_real_queue_after_rejection_without_downgrade` | `MlDsa65V2` | Actual PQ AuthBus text submission through the real Agentd/App Server/queue processes, invalid-request rejection, and subsequent normal service. |
| `real_agentd_without_explicit_trust_rejects_signed_text` | `Ed25519V1` request | Missing-trust rejection control. |

The process tests use `MockResponsesConfig` as a test response service. This is not an independently deployed model acceptance result. The 13 dispatcher tests include the new policy-bound renewal controls and a deterministic same-owner checkpoint synchronization test that executes both `Ed25519V1` and `MlDsa65V2` profiles. The latter requires two valid synchronizations to finish normally, actual stale witness bytes to remain rejected, and restoration of the actual committed witness to permit a subsequent signed submission. It uses explicit scheduling barriers without sleeps or retries.

## Retained predecessor failure

The earlier source candidate failed its ARM PQ product control in [run 41328688564, job 124913972865](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/41328688564/job/124913972865): 2 product controls passed and 1 failed with `AuthBus external replay checkpoint indicates rollback or drift`. That was an actual native failure, not a timeout. Its 29,522-byte recovered command output remains in the candidate's `checkpoint-sync-predecessor-product.log`, SHA-256 `128a9dc77372cf96d107c8ab923f022f0e516ad4c50e8d5e632fcff7bd834976`, with its execution record. The later successful jobs do not erase this failure.

Source review identified a possible same-owner interleaving in which two checkpoint synchronizations read the same external predecessor before one advances local state. The repair serializes the complete read/reconcile/publish/promote sequence with the existing owner mutex. The deterministic control proves the repaired serialization and retained rollback rejection; the historical failed run was not instrumented to identify its exact interleaving.

## Qualification limits

These results qualify the named AuthBus controls on this exact candidate and its prospective merge. They do not qualify the whole Chain, all Hepta paths, production activation, or an independent full-system deployment.

The renewal transaction is the policy linearization point; revocation after commit and before a remote effect remains outside this guarantee. The checkpoint mutex protects one owner instance; it does not implement cross-process compare-and-swap or an independent external monotonic witness. Full Cell V2 composition with #4497, FinalUse/CURRENT/installation/publication/settlement consistency, versioned RunStart/ObjectiveStart and journal/recovery migration, WAN/private-data protection, and whole-system acceptance remain open as documented in `../MIGRATION_DEPENDENCIES.md`.
