## Problem and source changes

Native CI on the previous integrated source exposed fixture/control failures and unresolved product boundaries. This draft preserves those original failures and adds the reviewed repairs needed for an exact-source qualification.

Current pure source: `b0547d2f874c0aeb54dabd3491caa2bee49fcb0b`; tree `3f89ddeff13d0af85f4abe2690699107357f1038`. Its parent is the reviewed pre-format source `421d15080b3cb942be8ac51bbe443e268d124a9e`, based on `9bd2f589debdba4a93baa363817c3669cb103721`. The separate qualification harness is not in this source ancestry.

This source has 109 cumulative changed paths against `2ae5215beaf8d7b7df111a090b82134beae2683d`. The latest increment changes ten paths:

- Cache caller authority fields only within one invocation and avoid owner parsing when a method cannot match. Full caller output remains equal to the frozen golden, except the explicitly derived Rust file count. Two cache and sixteen typed-caller cases cover the boundary.
- Keep the same neuron request in read-only observation while its result is CommitUncertain, within the original deadline. A new persistent-uncertainty negative case must reach the original deadline and retain the original dispatch count.
- Run the ordinary Windows delete control in an isolated, suspended child with an explicit handle allowlist and an owned job. Remove only the child's Backup/Restore privileges; verify the complete parent token is unchanged. The original elevated outside-delete assertions remain.
- Match the hardlink integration test to the actual public error contract, retaining both physical alias-content checks and the outside-write proof.
- Include the four formatter postimages produced by the actual V6 source gate, with no assertion, privilege-policy or deadline change.

Earlier reviewed changes remain: owner/custody paths, fresh-owner qualification lease clocks, wire/cache and remote-control fixtures, bounded failure-stage diagnostics, pinned Nextest JUnit location, same-handle pre-truncation Windows hardlink checks, and explicit durable-holdout retirement.

## Completed V6 source qualification

[Original source-only run 43032289667](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43032289667), job 130562136934, attempt 1, succeeded.

- The original 600-second operation completed in **283.467004 seconds**.
- All **18 distinct Python cases passed**, with no skips or retries.
- All **109 input/output paths** and three complete Git trees were independently checked.
- The original thirteen retired case names had **zero hits**, with no path exclusions.
- Caller verification scanned **6,201 Rust files**, retained `authorityGranted=false`, and matched the full 75,046-byte golden JSON except the complete-tree-derived count 6200→6201.
- Both lock files were byte-identical. The operation left four staged formatter changes; it was not a clean-after checkout. Those exact postimages form the current pure source tree.
- The original ZIP, full raw log, per-phase receipts, complete trees and source/tool identities were independently audited. This gate did not compile or run Rust/native tests.

## Original 9bd2 results retained separately

These results belong to the previous source and do not qualify the new head.

- Exact-source Bazel lock run 43020939762: one actual `just bazel-lock-update`, 26.462319 seconds within its original 1,200-second budget; exit 0 and unchanged source/lock files.
- Private CI: 34 distinct selected cases passed, with separate positive and expected-failing mutation controls.
- MEM native: 34 executions / 33 distinct cases; MEM Python: 154 executions / 120 distinct cases. Architecture source-head: 664 executions; its separate merge-head job: 136 Python executions.
- Blocking run 43021840778 ended with **37 jobs: 19 success, 9 failure, 5 cancelled and 4 skipped**. Its required gate rejected an invalid or absent Bazel result.
- Windows-current run 43021840561 ended cancelled after **124 of 167 distinct cases: 122 strict PASS, one LEAK and one FAIL**. Forty-three cases did not complete; no final source-after receipt exists.
- Original failures remain recorded: elevated outside-root deletion, captured-pipe LEAK, Linux network namespace denial, Fence inventory unavailability, hook completion observations, and the Mac Intel failure. The Mac execution artifact is preserved; its full job-log read is currently incomplete.

## Native qualification and adoption

The new source is admitted to its ordinary native CI once this branch advances. All five changed native cases still need exact-head execution. Source checks and old native passes do not establish current Windows isolation, retained-memory benefit or owner/effect recovery.

All ten adoption gates remain open. Existing provider UNKNOWN state, independent trust/exposure requirements, original budgets, assertions and adoption thresholds are preserved. This update does not authorize real model generation, replay of the original provider request under another key, or Provider G execution.

Evidence and owner ledgers remain in draft PRs [#5889](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5889) and [#5897](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5897). This PR remains draft; no merge or deployment is performed.
