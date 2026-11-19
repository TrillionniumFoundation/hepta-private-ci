# Native agent-loop cancellation successor validation

Exact parent #3649: dade1c7958bae627662e1ad6ff1484fa0d9ef191, tree d7ee0dbd7f3430a010195d338297df1730f773ea, based on #3619. Not a composition/merge of older #3510 ShadowAgentLoopV1. The current parent has 12 controlled-adapter tests, not the PR body’s older count of 10. Source search found implementations of the three owner interfaces only in its test fixture, not a concrete durable product composition.

## Reproduced defect and limited fix

Normal successor validation checked binding and exact revision increment, but cancellation-intent and cancellation-acknowledgement commits checked only binding/phase. Eight controlled bad-owner cases returned unchanged or skipped revisions, changed rounds, or changed consumed-token counters at either cancellation stage. The original implementation accepted all eight as Ok(Cancelled). All eight rejecting regressions failed, including the repository’s configured retry.

The minimal runner patch reuses validate_successor for these two cancellation transitions. It requires binding preservation, checked exact revision +1, allowed predecessor/successor phases, and unchanged round/tokens. Both owner cancellation calls remain concurrent, and both acknowledgements are still required.

This validates returned owner frames after commit. It does not roll back a bad owner’s persisted writes or prove a concrete durable owner, provider authority, process restart, real model quality, context-compaction preservation, physical effects, or performance parity. The eight new cases begin in Model phase; they are not exhaustive Tools-phase or adversarial-owner coverage. Persistence-after-commit/ACK-loss remains an explicitly open product-composition test.

## Executed results on dot

- Initial offline baseline failed before compilation because the new workspace required an uncached rama-tls registry entry. Preserved; normal registry resolution with --locked then succeeded without lock edits.
- Unchanged parent baseline: 12 passed, 0 skipped.
- Eight added regressions before runner fix: 0 passed, 8 failed, 0 skipped; every failure explicitly reports accepted invalid cancellation successor: Ok(Cancelled).
- Patched crate: original 12 + new 8 = 20 passed, 0 skipped. Legal dual-ACK, unresolved effect cancellation, stalled cancellation, deadline, partial EOF, and original-request recovery cases retained.
- just fix succeeded with four fixture unwrap warnings, retained in its original log. A narrowly documented test-only unwrap allowance was then added for the four fixed identifier/generation constructors; no production lint was relaxed.
- just fmt exit 0; final all-targets Clippy with -D warnings passed; git diff --check passed. Following repository instructions, tests were not rerun after formatting/fix. Post-green edits were formatting/import expansion and the test-only lint annotation, not behavior changes; final bytes were independently reviewed.

No socket tests, live providers, credentials, cloud quota tasks, security setting changes, merge or deployment. No production activation. Existing SHADOW/DENY_ALL posture remains unchanged.
