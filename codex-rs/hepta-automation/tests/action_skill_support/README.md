# ACT-1 native conformance experiment

This fixture invokes the real `AutomationStore::execute_authorized_taskflow_effect_async`
path, with a real prepared/claimed TaskFlow step and signed FinalUse grant. The
new `GoalCheckedActionSkillDriver` wraps the existing provider driver. No test
calls a destination mutation as a replacement for the authorized dispatch.

The independent SQLite destination stores three different things: job execution
facts, append-only business events, and transport contacts. Its fault schedule
controls real mutation boundaries and delivery. The goal observer reads a
separate connection and retains complete evidence by content digest. The test
oracle uses another connection and directly queries business rows, independent
of fault labels, provider ACKs, execution exit codes and observer judgments.

## Matrix

Each of the three baseline organizations runs these cases once with the same
request, destination, observer, authorization, fence, limits and oracle:

| Scenario | Injected boundary | Expected actual events | Reported success |
| --- | --- | ---: | --- |
| no_fault | Normal transaction and response | 2 | yes |
| committed_ack_lost | Commit completes; dispatch returns unknown | 2 | after original-key lookup |
| waiting_for_input | Real child process blocks on stdin | 0 | no |
| partial_success | First requested event commits; job returns exit 0 | 1 | no |
| rejected_after_partial_effect | Target reports rejected after first mutation | 1 | no |
| cancel_before_commit | Cancellation writer wins before mutation | 0 | no |
| commit_before_cancel | Mutation commits before cancel request | 2 | yes; cancel remains recorded |
| exit_zero_without_effect | Job returns exit 0; no business events | 0 | no |
| lookup_unavailable | Commit and lost ACK; status service unavailable | 2 | no; UNKNOWN retained |
| sigkill_after_commit | Parent SIGKILLs execution owner before ACK | 2 | after reopen and original-key lookup |

The target's completed ACK describes its job invocation lifecycle. The requested
business goal separately requires the exact ordered event set. This deliberately
exercises the difference without redefining a real provider contract.

The three baseline implementations have distinct control organization: an
explicit deterministic state machine, a parsed handwritten macro with lookup and
assert opcodes, and a flat primitive verification loop. All use the durable
TaskFlow owner, invoke once, and allow at most two lookup calls. These are
**single-effect conformance baselines**. They do not establish a speed advantage,
learned hierarchy, neural predictor benefit or generalization to held-out skill
compositions. Equivalent behavior here is expected.

`ACT1_METRIC` lines contain one JSON object per matrix run. Reported success is
checked against the independent oracle; metrics include false success, actual
business success, duplicate effects, UNKNOWN retention, physical dispatch
contacts, recovery queries and the common dispatch/lookup budget. The suite
produces 30 matrix rows, not 30 statistically independent task samples.

Additional tests complete a real waiting stdin worker under its original
operation, finish only a missing partial subeffect, reject changed wire bytes
before target contact, reject recovery under a changed contract, reject an
unsupported target before sending, and preserve UNKNOWN across reopen when
status lookup is unavailable. Recovery does not allocate another dispatch.

## Scope and limits

- The target is a controlled local SQLite service, not an HTTP production service.
- The subprocess tests are Unix-only and use the native test executable.
- No universal exactly-once property is claimed. The controlled target has its own
  durable key and dedupe transaction; an opaque target remains unresolved.
- Per-call limits are 16 KiB wire bytes, 30 seconds provider timeout and 5 seconds
  observer timeout. The harness enforces one dispatch and two lookups per run.
  This does not claim a new durable global budget scheduler.
- A real pipe is used for waiting input. Cross-session prompt/reader handoff and
  arbitrary stale callbacks are not qualified by this fixture.
- Reopen reuses the same TaskFlow fence. New-owner epoch transitions and
  competing TaskFlow writers are covered by existing owner/fencing suites, not
  newly proved here.
- Cancellation is a destination-domain request, not the TaskFlow Cancel command.
  Cancellation requests and effects coexist as separate facts. There is no
  implicit rollback or compensating action.

A separate positive failure test seals a rejection tombstone in the destination's
writer transaction after checking zero business events. The observer supplies an
absence proof only for that original key/payload and immutable tombstone, allowing
normal `Failed` settlement. Reopen, a late target worker and an owner replay must
leave the tombstone intact and business effects absent. This test is separate
from the 30-row baseline matrix.

Native compilation and execution are required before making result claims.
