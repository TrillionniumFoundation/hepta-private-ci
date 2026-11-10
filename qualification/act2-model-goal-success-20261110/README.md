# ACT-2 current-goal tool success

**Scoped native qualification passed independently on both the original and maintained exact sources. Full ACT-2 promotion remains HOLD.**

[PR #5619](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5619)
requires the original Notes REPLACE/STATUS success bit to agree with the current
goal observation. Historical Committed state and an applied receipt alone do
not establish that the document still satisfies the original goal.

## Source scope

The actual test source is `ae8a08059df73ccb875f4f541f76ad01080ba74b`, tree
`eedf15cce91f62cde4c85c6a2a9f124029ef6b5e`, based on canonical-fixture candidate
`8bebf0a3c207a49bfd0a99367fd6e06f52a6cb98` (#5618). The shared in-memory observer
fence and the existing original owner, writer, grant and recovery paths remain
in this source.

Run: https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42770759653

The official formatter successor is `631e99f78898543e8dc1e8671632baf73945940e`,
tree `9e5eb5acbed52758844804679647d316f401cb56`. Its only maintenance delta wraps
one test assertion expression. The complete published test file matches the
independent formatter's postimage, Git blob
`0cac78f0e1c3297dfa1080aaf114b2651d27d480`. Original test counts were not
transferred to this successor. Its separate
[run 42771121382](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42771121382)
completed successfully on the maintained source itself.

## Maintained exact-source execution

Run `42771121382` tested `631e99f78898543e8dc1e8671632baf73945940e`,
tree `9e5eb5acbed52758844804679647d316f401cb56`, without source mutation:

| Scope | Maintained-source result | Command elapsed |
| --- | --- | ---: |
| Automation package | 169 passed, 0 failed, 2 skipped | 286.417 s |
| Notes observer, projection and original owner | 12 passed, 0 failed, 778 skipped | 499.500 s |
| Selected real Session/App test | 1 passed, 0 failed, 789 skipped | 7.673 s |
| Pinned Session/App locked build | exit 0 | 121.347 s |
| Scoped lint/fix | exit 0 | 303.237 s |

The official formatter job and final formatter both produced empty patches.
Every command record binds the maintained commit/tree before and after, records
exit 0, and reports neither timeout nor output truncation. The actual App JSON
again records `[true,true]` for first/recovered/repeated current goals and
`[false,false]` after drift or readback loss, with three effect attempts, four
issuer requests, no replay and no new recovery grant. The full-handler,
production-authority, durable-tombstone, native-kernel and pixel flags remain
false. The maintained originals and their member hashes are retained under
[`maintained-run/`](maintained-run/README.md).

## What is checked

Two added tests call the shared original status assembly and the production
success predicate. They retain the same Committed/history/receipt fields while
varying unavailable readback, later revision, changed content, older revision,
missing receipt, missing goal projection, source Indeterminate and navigation
refusals. Existing READ behavior is retained. Receipt retirement does not erase
an otherwise confirmed current goal.

The real Session/App lifecycle also applies the same production helper to both
REPLACE and STATUS. The resulting JSON records the current-goal success flags
separately from historical receipt facts. It explicitly states
`complete_model_facing_handler_exercised=false`. This checks the shared predicate
on actual destination observations; it does not execute the full model-facing
DynamicToolCall/Root authorization/response transport loop.

## Actual execution and goal flags

| Scope | Original result | Command elapsed |
| --- | --- | ---: |
| Automation package | 169 passed, 0 failed, 2 skipped | 250.756 s |
| Notes observer, projection and original owner | 12 passed, 0 failed, 778 skipped | 427.393 s |
| Selected real Session/App test | 1 passed, 0 failed, 789 skipped | 4.510 s |
| Pinned Session/App locked build | exit 0 | 104.171 s |
| Scoped lint/fix | exit 0 | 267.712 s |

Both added tests appear individually as PASS in the original Notes log:

- `notes_act2_tool_success_requires_current_goal_after_readback_loss_or_drift`
- `notes_act2_tool_success_keeps_read_and_original_navigation_semantics`

The actual JSON records the following shared predicate flags in tool order
`[hepta_notes_replace, hepta_notes_status]`:

| Actual situation | Flags | Historical/current facts |
| --- | --- | --- |
| First current goal | `[true, true]` | Confirmed at revision 1 |
| Recovered current goal | `[true, true]` | Confirmed at revision 3 |
| Old goal after real edits | `[false, false]` | Committed/applied receipt retained; current goal unsatisfied at revision 3 |
| Three repeated fresh observations | Each `[true, true]` | Equal complete status values at revision 3 |
| Actual App closed and readback unavailable | `[false, false]` | Committed/applied receipt retained; current document absent and goal/runtime UNKNOWN |

The full-handler flag is explicitly false. This is the production helper applied
to real observations, not execution of the entire model-facing handler. The
lifecycle retains three effect attempts and four issuer requests across three
operations, including the existing deliberate denial. No replay or new grant
occurs in recovery or repeated observation.

All five commands exited 0 without timeout or output truncation. Their original
log byte counts and SHA-256 values were verified. Scoped fix left source clean;
final formatting produced the same 651-byte patch as the independent formatter
job (SHA-256 `dbc2f2147aa0e0a391305b3f134b289fdda9e7578a6ab82e87b02810e3f9f834`).
It changes only the test assertion line wrapping. The original run did not
execute behavior tests after that maintenance. Elapsed values include build and
runner work and are not policy-performance comparisons. Existing warnings remain
in the original logs.

## Original artifacts and limits

The unmodified native and formatter ZIP bytes, actual JSON, full command records,
log length/hash checks, archive-member manifests and exact source/maintenance
mapping are retained with this report. Skipped tests are not counted as passes.
Recorded Session/App binary hashes are compared with the actual JSON; complete
binary/lock bytes and a standalone Hepta test-executable hash are not supplied by
these artifacts, so no independent complete-file hash recomputation is claimed.

One App lifecycle supplies the real observations. Repeated reads and paired tool
flags are correlated measurements, not independent task trials. No future error
rate, learned hierarchy benefit or performance frontier is estimated here.

The in-memory fence lasts for one attachment. Durable rollback protection,
asynchronous report delivery ordering, actual App checkpoint rollback,
destination tombstones, cancel/commit races, late-commit exclusion, real
long-running/network wait adapters, full model-facing handler qualification,
production authority, native kernel/pixels, complete repository CI and independent
learned-hierarchy benefit remain open. No main merge, deployment, effect authority
expansion or scientific promotion is introduced by this evidence.

## Retained originals

- [native artifact](evidence/act2-native-42770759653.zip): 73,109 B, SHA-256 `a307ba24f571eaf47cbd129304e58d4b850e8efb9336592c9f98a1ec250f7fe1`.
- [format artifact](evidence/act2-format-42770759653.zip): 58,130 B, SHA-256 `b25541da6c46bf4f41d5129ffdfe76677aa7eb4c3898bc3ec9c3a7cfd0f79b48`.
- [Actual JSON](evidence/notes-actual.json), [official patch](evidence/official-format.patch), [RESULT.json](RESULT.json), [MAINTENANCE.json](MAINTENANCE.json), [original static review](goal-success-review.json).

ZIP bytes are preserved without repacking and match GitHub's artifact digests.
Archive-member manifests and original command/source/lock/binary records are
retained in RESULT. The formatter successor's complete postimage and its single
file commit delta were independently read back. Its new native acceptance is
the separate exact-source run above, not an inherited original-candidate pass.
