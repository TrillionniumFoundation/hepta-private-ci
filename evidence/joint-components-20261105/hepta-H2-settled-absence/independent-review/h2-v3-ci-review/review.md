# Independent review: H2 v3 persistent CI wiring

No concrete CI wiring blocker was found. This review extends the v2 source review only to v3's added workflow delta; it does not confer formatting, Clippy, compilation, native-test, or joint qualification credit.

## Exact source binding

The reviewed v3 patch is 26,569 bytes, SHA-256 `9507e363818b094f4453d5d91496b14a28438a15603b65625d5736c93635cb30`. Its implementation manifest is SHA-256 `c0f9c5a85ca777952febb792bf822725a6095c1d9c0401487689bef92db61570`.

The four Rust file records, actual candidate bytes, and their complete patch chunks are identical to reviewed v2 patch `906788c15547a5a21f0f90bcfc95f45d4aa25d163a83a51d29981c3919adba7e`. Their semantic review is retained in `pq_recovery/h1-effect-reconcile-review/candidate-v2-safety-review.md`; it was not repeated here.

The workflow base was independently fetched at exact H1 `9f785cb201ba12ab0ae0f0d341c0f7912cc65efc`. Its complete bytes match Git blob `4295f31ac8e901f427695f320d2c1da07890d0ce` and SHA-256 `4f331d94dc8927d537873f976ce8c459a5e09673ef8431d3b310419ecf21f2ad`. The candidate workflow is Git blob `487bf796005439547ff1ac0366648a0f2daf236c`, SHA-256 `f1e3b05fbdf39ff22d9837ca92595cf84e48a038e8a1c60e1bbee6bb4f39d584`.

## Permanent execution and exact-name guard

A separate `effect-settled-absence.json` stage runs package `codex-hepta-automation`, integration binary `authorized_effect`, with these two exact nextest selectors:

- `owner_recovery_tests::settled_absence_fact_read_survives_reopen_and_new_owner_without_redispatch`
- `owner_recovery_tests::settled_absence_fact_read_rejects_unknown_unsettled_and_corrupt_evidence`

The wrapper requires at least 2 tests and retains a 600-second stage cap. The command includes `--locked`, `--no-capture`, `--retries 0`, `--test-threads=1`, and `CARGO_NET_OFFLINE=true`. The stage is enabled under the same dependency-success and not-cancelled condition as the original native stages. It is placed after the PQ contract stage and before the ordinary Agentd process stage; every original step retains its relative order.

The original 69 exact case names and their grouping are unchanged. The added guard group contains only the two names above, for a total of 71. After removing the `expected` inventory assignment, the parsed guard AST is identical to the base guard. It still requires a passed receipt, command exit 0, the exact raw-log hash, exactly the expected passed/failed counts, the exact number of raw case records, and equality of the passed-name set. Thus a missing receipt, skipped case, duplicate case, renamed case, or extra/missing selected case cannot satisfy the count alone.

The source workflow guard and the supplied extracted guard script have identical text after trimming trailing whitespace. The existing implementation proof, SHA-256 `8ae62f2200c59f286993442eb396e62d94852c50710e58ad71a6019e2a204eac`, records four synthetic controls: complete inventory succeeds; missing receipt, selected-case skip and duplicate case fail. This reviewer verified the source/hash correspondence and read those results, but did not re-execute those controls. They are not native evidence.

## Resources, ordering and unchanged gates

Independent YAML comparison confirms that the original top-level permissions, trigger paths, concurrency, matrix, runners, lane selection, job environment, and 90-minute total cap are unchanged. All original test-stage commands and individual limits are unchanged. The existing nextest per-test configuration is not part of the patch.

Apart from the new stage and its inventory entry, the only original step modification appends `-p codex-hepta-automation` to `just fix`. All earlier package arguments remain in the same order, and the original 1,200-second lint cap remains unchanged. The original formatter follows tests and lint under its existing 300-second cap. Source checks and artifact retention are unchanged. The new 600-second stage remains inside the unchanged 5,400-second job window; this static review makes no claim that a future execution will complete within that window.

The workflow explicitly distinguishes the new classical owner/store fixtures from the unchanged native PQ boundary controls. H1's 9-pass/2-fail PQ owner result remains a failure, and H2 must complete the original assertions and remaining gates on its own exact committed source and executed binaries.

## Review evidence

`workflow-v3-review.json` records the independent byte, patch-chunk, YAML, command-argument and guard-AST comparisons. Only constant inventory data was evaluated while extracting the case names. No synthetic guard was rerun, no desktop process or Cargo task was started, and no frozen H1/C4 source or candidate file was changed by this review.
