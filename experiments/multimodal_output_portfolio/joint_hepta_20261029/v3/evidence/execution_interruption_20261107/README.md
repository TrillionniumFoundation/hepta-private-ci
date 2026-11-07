# Blocker continuation checkpoint — 2026-11-07

## Current decision

All blockers are not closed. The research decision remains
`NO_GO_FOR_LARGE_SCALE_TRAINING`.

This additive checkpoint records the work completed through draft PR #5290,
the separately running ARM43 proposal, and the execution-environment interruption.
It leaves the existing status matrices, historical failures, product source,
scientific results, and qualification gates unchanged.

The durable source before this documentation commit is:

- PR #5290: `28e15e4e564dddc95d8de51cbdecaa2b435e2ed4`.
- Tree: `fcef393dc13503ea35c8ffcb8770cb4565dc0574`.
- Evidence branch: `research/ndu-arm42-terminal-failure-evidence-20261107`.
- Recorded publication counts before this commit: 169 main evidence entries and
  83 side proposals. No merges were performed.

## Execution environment

The platform marked the workspace environment unavailable after process creation
failed with an exec-server transport disconnection and recovery timed out after
45 seconds. This is an execution-availability failure; no approval rejection was
reported. Subsequent local checks did not execute.

GitHub connector reads remain available. The published commits and already
running GitHub job are separate from the disconnected workspace. Files that
existed only in the workspace have not been read again since the interruption;
their previously observed identities are recorded in `CHECKPOINT.json`.
Their current accessibility or persistence is not assumed.

## Completed publication

| Draft PR | Published scope |
| --- | --- |
| #5283 | Windows44 packet builder and bounded supporting evidence |
| #5284 | Independent Windows44 packet audit and preserved failed predecessors |
| #5285 | Windows44 terminal checkpoint |
| #5287 | ARM43 bounded store diagnostic source, based on #5271 |
| #5289 | ARM42 terminal audit tools |
| #5290 | ARM42 terminal failure evidence |

ARM42's original case failed with original `just` exit 100: zero JUnit passes
and one failure. The qualified declared view contained 1,474 selected files and
68,665,776 bytes. The observed terminal failure was the Agent B authority-probe
decryption timeout. An earlier record reported durable Core reconciliation
unavailability. That record did not identify the underlying SQLx site, error
class, SQLite code, or a particular failed event.

Windows44 recorded four selected case passes and two failures. The two original
failures remain, and no FULL probe record was emitted. F0–F4 therefore remain
unobserved. The outside-deletion P0 and migration of existing ACLs remain open.

## ARM43 original run

The source proposal is draft PR #5287:

- Head: `558cf97e25f5b6627aa1d799795e9a3247efa94c`.
- Tree: `0c71d4360882418630111024d5d64382f2e2a4ab`.
- Sole parent: `8b0fcf80afb95c5199be9b5f131d6454663c1632` from #5271.
- Original run: [42360673915](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42360673915),
  attempt 1, ARM job 128368922412.

The latest captured API observation has the run and ARM job in progress,
with the ARM job on step 4. This broad step contains preparation and the business
qualification; its API status does not identify the current internal subphase
or a testcase outcome. The complete jobs page has 11 of 11 entries.

The finite store diagnostic preserves the original Unavailable return and emits
only a fixed site, fixed error class, and bounded numeric SQLite code when
available. Actual runtime diagnosis and terminal qualification remain pending.
After the workspace interruption, no new declared-view ZIP, CRC, catalogue,
or original-evidence qualification was performed.

## E18 native entry: reviewed, unpublished

The nine-file candidate was fully read by root and an independent reviewer.
Root bound 17 original files, the nine new paths, 12 complete Git trees, and the
12 official released-asset API identities to actual product parent #5285.
The original whole `just fmt` returned zero. All nine candidate files and all
153 previously owned files remained byte-identical; the resulting owned
inventory had 162 files.

Four planned review units have 456, 427, 342, and 444 changed lines.
Formal A/B publication manifests had not been generated when the environment
failed. Zero of these four stages have been published and no E18 native job has
been triggered.

The entry is intended to qualify four combinations through original `just`:
Darwin ARM default, Darwin ARM sandbox, Windows x64 sandbox, and Windows ARM
sandbox. Each requires the six existing tests and all 20 original evidence
slots. Its declared scope is `RELEASE_ASSET_RUNTIME`; qualification of the
current canary's source-built assets remains separate.

Forty bounded synthetic model checks completed before the interruption. Their
scope included loading candidate evidence, contract, and asset modules; calling
AST-extracted guard functions on a tiny owned Git repository; and calling the
original asset and collector functions on synthetic files with recorded test
doubles. They did not invoke the controller's native execute phase, the download
entry, Cargo, or Rust tests. The real ambient scanner independently rejected
`AMBIGUOUS_SHORT_CREDENTIAL`; the environment was not filtered or changed.
The initial PRE_REVIEW statement about no imports describes its earlier
snapshot, before these synthetic checks.

The old actionlint 1.7.7 failure for the official Windows ARM runner label is
retained. The separately verified official actionlint 1.7.12 returned zero.
Neither result is a native test outcome.

An additive contract correction narrows `platform.machine()` to its machine-type
observation. It does not independently establish the Python interpreter's process
instruction set. Rust host, selected target, nextest metadata, and actual test
outcomes remain required.

The independent review found no blocker within this source scope. Its final
peer-only Codespell and format-check attempt was not confirmed to execute after
the environment disconnected. That unfinished check is not recorded as a pass.

## Research and remaining gates

At 09:58 UTC, root re-read the eight scientific remote leaves at #5290. Their
Git blob identities, file modes, and sizes matched the already published frozen
baseline in `ndu_status_20261107_0114/SOURCES.json`. This was a remote identity
check; local file bytes were not rechecked after the interruption.

The current candidate still has 0 wins, 143 ties, and 1 loss against the strong
same-data myopic VOI comparator. At the declared primary lifecycle M=1000,
0 of 144 cells are positive and all 144 absolute lower bounds are negative.
The 88,866.778 acquisition cost is a declared synthetic score, not provider money.

The three frozen local-model procedures remain development runs on reused
disclosed tasks. They do not provide independent held-out net-benefit evidence.
A new learned stateful algorithm near the information-cost bound, independent
task net benefit, and new RL originality remain unestablished.

Other open engineering gates include the Linux trusted live authority producer,
Windows native authorization and ACL lifetime, credential-rotation readiness,
complete original evidence for selected Core/AppServer cases, stronger storage
durability, historical timeout diagnosis, and complete repository qualification.
The original failures and refused evidence remain in force.

## Resume from original bytes

1. Restore access to the existing workspace and read the recorded original
   files by hash before making changes.
2. Reconcile actual remote branch heads and this checkpoint with local
   publication state. This documentation commit occurred after disconnection;
   the unavailable local state file could not be updated.
3. Inspect the current ARM43 original attempt. Qualify terminal evidence with
   the original declared-view and source guards.
4. Recover and hash the nine E18 candidates and their review receipts. Preserve
   the existing synthetic checks and their failures without rerunning them.
5. Generate the formal E18 manifests, then publish the four strict stages from
   actual #5285, binding each actual head and tree in sequence.
6. Run and qualify the four native combinations through original `just`.
7. Refresh the complete status and history using the resulting original
   evidence. Keep frozen scientific findings and unresolved gates explicit.

No assertion, timeout, retry, concurrency, scanner, or source guard was relaxed.
