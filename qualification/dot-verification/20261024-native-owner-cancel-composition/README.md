# Restore cancellation validation on actual native-owner composition

Exact parent #3649: `95943a632f607f497f9ce63b001cd297276e1d7e`, tree `5cb9d33969c8e14a6b2f0a41673fb20d8a905072`. The newer source already implements TaskFlowTurnOwner and AutomationStatusEffectOwner over the original AutomationStore. This change reuses those owners, not another SQLite fixture/ledger or the earlier simplified #3654 file owner.

## Verified repair

The original #3652 cancellation-successor repair was absent from this newer composition. Its public runner still accepted owner replies with unchanged/skipped revision or altered round/token count at either cancellation commit. Eight controlled-owner mutation cases reproduced this exact omission on the new source: **8 failed, 0 passed**, exit100, explicit zero retries. This is a generic TurnOwner contract-validation defect; the real TaskFlowTurnOwner itself was not shown to produce corrupt commits.

The production patch is the same narrow donor change: apply existing validate_successor to cancellation intent/ack, requiring identical binding, exact revision+1, unchanged round/tokens and the appropriate phase. No new SQLite state, authority, grant, provider output or cancellation API is introduced. Bad owner writes are not rolled back by this validator. The donor mutation fixture only gains the newly required maximum_provider_input_tokens field; its pre-existing test-only unwrap lint annotation is retained, not added to production code.

## Actual local verification

- Unmodified original automation-effects target: **7/7 passed**, 0 skipped, zero retries.
- Original runner with adapted eight donor mutation cases: **8/8 failed**, zero retries, retained raw negative result.
- Patched composition: **37/37 passed**, 0 skipped, zero retries across automation_effects (9), cancellation_successor (8), owner_loop (12), taskflow_owner (8).
- New true-owner case: persist CancelRequested via TaskFlowTurnOwner, drop/close/reopen original SQLite and reconstruct effect adapter, then drive with a fresh uncancelled token. Outcome remains CancellationPending, original frame unchanged, zero controlled-provider dispatch/lookup, no effect attempt created. The controlled inference ACK cannot substitute for the real effect adapter's missing stop ACK.
- New generation case: changed generation cannot reopen original cursor or attach the original admitted effect; original identity remains recoverable with exact frame equality. No replacement run/grant/dispatch is created.

The first combined command failed before tests because the new child test's assert_eq import was ambiguous. The explicit existing pretty_assertions import fixed only that fixture compilation error. The misleadingly named combined-green.log is that original FAILED attempt and is retained unchanged; combined-after-import.log is the actual 37-pass result.

`just fmt` and `git diff --check` pass. Tests preceded formatting per repository AGENTS; four exact preformat files are retained for independent comparison.

**Strict scoped Clippy FAILED exit101** in two unchanged production locations: taskflow_serde.rs:45 (trivially_copy_pass_by_ref on serde serializer signature) and automation_effects.rs:78 (collapsible_if). No production allow/expect, signature rewrite or macro bypass was added. Default-warning scoped Clippy is separately recorded as supplementary diagnostics, not a strict pass. Full dependency Clippy, all features, managed HTTP/provider tests, whole workspace and hosted CI were not run in this task. Existing nextest metadata/profile and dependency AsyncFd deprecation warnings remain in logs.

## Durable identity design decision

A second immutable admission snapshot was considered but NOT implemented. Existing final-use/store admission already verifies Running/uncancelled state, definition, legal claimed step, exact intent/payload/fence and active lease within an immediate transaction. A separately authorized new operation must not be classified as an unauthorized replay merely because it is different.

Reusing a generic TaskFlow cursor as frozen metadata needs unresolved compatibility decisions: legal grant renewal versus immutable identity, legacy attempt history across all steps, first binding retained before final-use failure, strict single-revision constraints, and concurrent SQLite busy/CAS behavior. A late rejection must not unnecessarily destroy recoverability. No new mapping table, cursor payload, runtime state or schema was added while those semantics remain undecided.

The current status tool deliberately projects original terminal status and labels it status_only_no_output_artifact; it is not arbitrary original tool bytes. Cancellation remains Unresolved without real stop proof. Local fixture coverage establishes neither live provider authority, remote stop ACK, process-kill/power-loss recovery nor production readiness. No sockets, external provider request, secrets/security changes, merge/deploy or remote CI monitoring. Publication is a reviewed draft only.
