# Repository consolidation: current reviewed checkpoint

## Status

The source checkpoint is `4a5630661b1fee17582b452520c32fb5805831aa`, tree
`3c2c8718270bc8c45eb22918e81fbc35cc695189`. The evidence commit containing
this page is intended for the existing integration PR #6293. At preparation,
the published integration head is
`60658ec54cf7f857197733fecf455ba44fecd3d4`; publication is verified separately
by an exact reference readback. Main remains
`732e934ba496d90fbe042b8d41d479ef901643e5`.

The source ancestry contains 1,835 of the original 7,230 eligible ordinary
branch heads, leaving 5,395 to review and integrate. The previous published
head contained 1,826. These are ancestry coverage counts, not a claim that
every covered behavior or every required CI job has passed. No branch has
been deleted and no change to main has been made during this consolidation.

The latest captured complete reference scan ran from 2026-11-17 01:16:44 to
01:17:01 UTC and contains 7,353 heads. Its protected set contains 122 heads.
All 104 previously protected references were unchanged; eighteen additional
cell experiment heads were independently proved to descend from the protected
HIA history. The candidate contains none of the current, prior, or original
protected heads and neither protected marker commit. The complete original
ordinary name set still matches, and no reference was moved or deleted in
this scan. A final live reference check is required before publication.
New HIA-related branches remain outside the ordinary merge and deletion scope.

## What this source checkpoint adds

Eight actual ordinary merge commits after the preceding published checkpoint
retain their incoming parent identities and complete reviewed histories.
Three preceding merges added four covered heads; the next five added five
covered heads. Resolutions preserve the current stronger behavior when an
incoming patch was already present or would weaken a guard. They do not use
a blanket merge strategy that discards an incoming tree without review.

The ordinary source additions include a seven-stage learning iteration
router, private creation of an initial cognitive database with explicit
regular-file, link-count, permission, and synchronization checks, and a
historical database root canonicalization fix. Recovered database pointers
remain subject to their existing validation and are not silently recreated.
The relevant new Agentd and Memory source has passed formatting; complete
native validation at this combined source tree remains pending.

The reviewed 14-file source and workflow correction includes the total-source
propensity correction, strict workflow dispatch decisions and omitted
dependency triggers, and v6 workflow closure. Its experimental outputs do not
establish finite-sample unbiasedness or production training qualification.
The complete large incoming family has not yet been merged.

The Windows launch correction supplies the validated absolute LOCALAPPDATA
value to the original child environment; it preserves the original process
creation flags, parameters, ACL behavior, and five-second budget. Exact
source pins and checkout long-path handling were repaired. Linux call capture
passed fourteen cases and retained two old-production counterexamples.
Native Windows results for the new checkpoint remain pending.

The B4 correction updates exactly the one protected caller row to require the
complete v2 envelope from the same record. All other 818 protected rows and
all 1,645 boundaries remain unchanged. Thirteen mutation regressions reject
comments, dead code, nested functions, and incomplete or mismatched evidence.
The original verifier and loader are retained.

The control-layer composition adds the reviewed role admission, durable
control receipt, publication, bounded checkpoint, and Windows identity
changes. The Windows implementation compares the complete 128-bit file ID
and volume identity using existing dependencies and propagates API failures.
It retains the existing reparse-point, size, type, and poisoned-writer
behavior. No atomic path binding, private ancestry, single-writer ownership,
or cross-platform durability qualification is claimed.

A separate narrow decoder fix rejects noncanonical optional receipt tags.
Three regressions exercise actual terminal and reconciled snapshots, all
254 invalid tag values with recomputed checksums, unchanged durable bytes
after rejection, and valid round trips. The complete incoming control family
has not yet been merged; its remaining paths and histories are still under
review.

## Actual validation results and their source limits

| Validation                       | Actual outcome                                                   | Source and interpretation                                                                                                  |
| -------------------------------- | ---------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------- |
| Original formatter               | Passed; 13,817 input files and modes unchanged                   | Actual source checkpoint 4a563; 30,178 indexed paths; all 84 reviewed source paths physically present                      |
| Original B4 suite                | 1,344 passed                                                     | Earlier 9839 source plus the four B4 changes; not the full later tree                                                      |
| Complete caller verifier         | Passed; 1,645 boundaries, 819 protected rows, 7,552 Rust files   | Same frozen B4 input vector; authority remained false                                                                      |
| Original full earlier native run | 1,971 passed, 11 failed, three timed out, 193 originally skipped | Exact earlier 2ba source; original failed records retained                                                                 |
| Exact helper-case replay         | Ten selected cases passed                                        | Same earlier source after the original helper build; original test budgets, stack, filters, and retry settings retained    |
| ROG diagnostic cases             | Four passed twice                                                | Instrumented source on tmpfs; not a successful replay of the original unchanged desktop ext4 run                           |
| Initial control composition      | 351 passed, then 357 passed after the bounded checkpoint repair  | Exact recorded composed source inputs; old role and checkpoint counterexamples retained                                    |
| Final control composition        | 369 passed; zero skipped or failed                               | Six original build, formatting, Clippy, and test steps; 13,683 recorded inputs unchanged; base 287374 plus reviewed layers |
| Windows-only additions           | Seven tests pending native Windows                               | Not executed on Linux; no Windows success claimed                                                                          |
| v6 original command sequence     | All 17 wrapper command receipts passed                           | Twelve shell steps executed; five setup/build contexts reused and recorded; earlier exact 2ba source                       |
| v6 Python and finite oracle      | 102 and 128 passed                                               | Original input and output identities retained                                                                              |
| v6 smoke                         | Passed in 163.250 seconds under the original 900-second budget   | 56 rows, eight native receipts; all consumer outputs reopened and verified                                                 |
| Fixed nextest 0.9.103 replay     | 552 executed tests passed across six steps                       | Exact same test identities/results as the preceding run; original ignored tests and filters retained                       |

The exact-version replay reused completed smoke outputs and prerequisites; it
did not claim to repeat training or the smoke experiment. The calibration
target was compiled, not executed. The stricter local AppArmor user-namespace
setting differs from the workflow setup, and no system setting was changed.
The initial nextest 0.9.137 run remains available alongside the later pinned
0.9.103 evidence and verified release-asset identity.

The final control test vector is not the complete 4a563 tree: it excludes
unrelated newer Agentd, Memory, and workflow changes. The final formatter
checks the actual combined tree, but formatting is not a substitute for
native execution.

## Required work still open

The hosted checkpoint still has failing required checks. A natural status
capture at 00:34 UTC recorded 215 checks: 178 successful, 15 failed, 14 skipped,
five running, two cancelled, and one neutral. This is a dated observation,
not a statement about later check status.

Ninety-eight actual strict Clippy errors are being repaired in existing test
and helper code. The work propagates errors through fixture call chains and
preserves production callback signatures. No lint suppression, relaxed
assertion, increased retry count, or larger time or stack budget is used.
That repair is not included in this source checkpoint.

Four original positive Windows sandbox tests encounter the explicit elevated
filesystem admission guard. The guard remains closed because earlier actual
deletion experiments found ambient parent delete-child authority bypassing
the intended restriction. It is unconditional; it is not a new per-test ACL
check. A qualified replacement backend is required before reopening it.
The guard must not be removed, tests skipped, or expected success changed to
expected rejection merely to make CI pass.

The repaired AppContainer and LPAC launch probes still require native Windows
execution. Their previous error occurred before a child was created, so that
result does not qualify or disqualify the proposed isolation mechanism.

Two other Windows failures remain separate: subagent notification delivery
timing and WebSocket turn-state isolation. One original desktop latency
failure and three desktop timeouts also remain unresolved by the selected
helper replay or the ROG diagnostics.

Large unmerged families include the remaining control and v6 histories,
Windows sandbox, Landlock, HCSN, directory-handle, worker, repair, and outbox
branches. One large family has multiple merge bases and needs a real virtual
merge-base resolution. The full ordinary branch audit and consolidation are
not complete.

Main integration and retirement of ordinary branches require the actual
combined required checks, architecture constraints, exact ancestry, and
fresh reference protection checks. No HIA reference is to be updated or
deleted. New ordinary two-parent proposals prepared after this source
checkpoint are not included in the coverage count above.

## Evidence navigation

- [Latest 122-head protection snapshot](branch-fresh122-20261117T011644-v1/manifest.json)
  retains all 45 original reference, ancestry, parent graph, and coverage files,
  including the eighteen new immutable commit responses.

- [Root source and validation archive](root-checkpoint-20261117T0105/README.md)
  contains the ordinary merge resolutions, exact source creation records,
  full B4 gates, original helper builder and selected replay, frozen failed
  native records, ROG diagnostic handoff, and formatter scope corrections.
- [v6 command, fixed-version replay, and protected reference evidence](branch-v6-and-fresh104-20261117-v1/README.md)
  retains all original wrapper receipts, output files, input maps, test
  identity comparisons, tool provenance, and the 104-head protection proof.
- [Initial control source layer](c2d-control-source-union/README.md) and
  [bounded checkpoint repair](c2d-checkpoint-repair/README.md) retain complete
  native records and old-production counterexamples.
- [Windows launch and exact source pin repair](../windows-launch-and-pins/README.md)
  retains the original failures, proposed source, and Linux call captures.
- [Final control, Windows identity, and canonical receipt evidence](c2d-windows128-receipt/README.md)
  retains the final 369-test run, invalid-tag counterexamples, complete inputs,
  and independent Windows source review.

The previous CURRENT page is retained byte for byte as
[root-checkpoint-20261117T0105/previous-CURRENT.md.gz](root-checkpoint-20261117T0105/previous-CURRENT.md.gz).
Each package documents its captured originals and explicit exclusions.
Compressed carriers preserve original raw logs and failed attempts without
rewriting their content to satisfy format or spelling checks.
