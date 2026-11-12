# ACT3 joint recurrent and original async-owner recovery

This record qualifies cooperative Linux process-death engineering: the archived
trained GRU, its exact hidden bytes, the original pending invocation and the
original filesystem worker share one durable lifecycle. A real original worker
publishes after its original controller is killed, and the restored controller
only reads that original effect. Production authority and learned benefit remain
unqualified.

## Frozen execution identity

| Field | Original value |
| --- | --- |
| Async implementation PR | #6175 |
| Async qualification PR | #6180 |
| Synchronous predecessor PRs | #6152 and #6155 |
| Tested commit | `c66ebe41e03b2951e88f4c8c1e6d15be8e7fa165` |
| Tested complete tree | `205a4d1958f2d57d4dbb9a1368846e53022e79b2` |
| Async implementation source | `6ac3bcadcd01249073117b12f24b81a0dcb75e64` |
| Original local result | 58 planned, 58 started, 58 passed; zero skips/errors/failures |
| Test wall time | 14.842045041 seconds; test execution time, not policy efficiency |
| Runtime | CPython 3.12.14, NumPy 2.3.5, Linux; full values in MANIFEST.json |
| Before/after identity | Same commit/tree, clean worktree, source hashes and eight model hashes |

This evidence commit follows the tested code commit and adds only evidence. The
58 tests include the earlier 46 suites on the new exact source, plus five joint
async core methods and seven independent async controls. Do not add 46 and 58 or
interpret the cases as independent application tasks. PLAN.json and RESULT.json
retain every planned/started/passed test identity.

| Suite | Actual tests |
| --- | ---: |
| Skill lifecycle | 9 |
| Original filesystem owner | 3 |
| Durable lifecycle | 9 |
| Earlier durable async owner | 5 |
| Recurrent lifecycle | 8 |
| Independent recurrent controls | 12 |
| Joint original async worker and recurrent lifecycle | 5 |
| Independent joint async controls | 7 |

## One original checkpoint and actual worker continuation

AsyncRecurrentLifecycle uses the same FileOwner directory, owner identities,
writer lock and SQLite state row as RecurrentLifecycle. It does not create a
second destination or ledger. The row retains hidden bytes, decision sequence,
original pending invocation, unresolved effect, original budget/deadline and the
async attempt. The apply reservation and entered state are committed before
spawn; release uncertainty is committed before the original pipe send.

The original worker checks the saved model/configuration/source/UID/boot binding,
admission record, original owner identities, exact hidden/sequence/pending intent,
budget reservation and deadline. It can execute only its original apply. Worker
notifications are not completion receipts. A restored controller acquires the
original lock but has no reconstructed pipe or process handle. It can reconcile
through current reads of the original effect, never resend based on UNKNOWN.

The retained joint continuation case actually performs this order:

1. Start the archived GRU and original worker; retain the exact checkpoint and
   original worker specification after its real WAITING pipe notification.
2. Obtain the original worker pidfd and SIGSTOP that worker. Release through the
   original controller's live pipe and retain its completed-send observation.
3. SIGKILL the original controller and observe returncode -9.
4. Restore the original directory while the old worker is still alive. The same
   hidden/sequence/owner survive; reads return UNKNOWN, no pipe is recreated,
   inference and redispatch guards remain installed, and no effect is present.
5. SIGCONT the worker through the same held pidfd and observe that identity exit.
6. Read back exactly one original payload for `original:0`, preserving the hidden
   bytes and sequence, with no duplicate effect and only one original control.db.

The final observation is `CONFIRMED_COMPLETE` for that effect. The policy is
`ready`, its decisions are still `inspect, ensure`, and `claimed_success=false`.
This cutpoint does not claim that a post-recovery neural STOP ran. Separately,
the included synchronous full prepared-resume test compares uninterrupted and
restored final hidden/sequence/decisions/calls/effects/goal results.

Other joint cases cover death before release with no I/O recreation, live pipe
waiting and pause before release, elapsed original deadline after actual release,
and exhausted observation budget retained across reopening without inference.
The seven independent methods exercise actual worker processes and constructed
adversarial model weights; they test integrity, not learned accuracy. Their
controls cover spawn failure, uncertain pipe send and cold reopen, stale current
readback, original invocation replay, next distinct key, forged worker packets
and source replacement across a fresh interpreter.

The read-only independent audit checks 19 retained control databases and their
state digests/source bindings. Retained individual death originals comprise five
recurrent SIGKILL cases, two new joint async SIGKILL cases and two legacy abrupt
controller exits (17 and 18): nine retained death cases, seven SIGKILL cases.
Additional durable-lifecycle fixture cuts are asserted by passing methods but
do not have per-case originals in this archive. No count is a real-task sample.

## Development failures remain visible

Independent review reproduced two bugs in the unpublished async intermediate:

- After an effect was actually removed, a historically settled wait returned
  stale CONFIRMED_COMPLETE and charged no current read.
- A fresh incomplete observation then allowed a second actual worker to apply
  the same original invocation again without any checkpoint rollback.

The frozen RED reproduction retains four original SQLite snapshots, first and
second payloads, distinct worker observations, the failure log and source hashes.
The fixed driver always charges and performs a current original read on wait;
historical settlement is a permanent no-replay fence for the same or earlier key.
GREEN independent controls and final prepublication source checks are retained.

development-originals.tar.xz also retains the earlier six-case development run
and the final distinct 12-case prepublication run. One duplicate failed-pipe case
was consolidated into the independent test with its cold-restore assertions;
the final count is five core plus seven independent methods. Those development
attempts are not reassigned to the final frozen source. The predecessor record
separately preserves the configuration-alias RED/GREEN regression.

## Artifacts and reproduction

- RESULT.json, MANIFEST.json, PLAN.json and tests.log preserve the final execution.
- originals-and-source.tar.xz contains the complete frozen-run output: exact
  source, actual archived GRU copies, original checkpoint databases and hashes,
  worker specifications, original effect intent/value bytes, event timelines,
  child exit/stdout/stderr and before/after reports.
- SHA256SUMS.json binds the uncompressed runner output. FILES_SHA256.json binds
  the files committed here. The archive's contents were checked against the
  runner hashes after packing.
- INDEPENDENT_READBACK.json records a separate read-only audit of the originals.
- development-originals.tar.xz retains the failed and passing development stages.
- RESOURCE_OBSERVATIONS.json and BLOCKERS.json retain access/CI observations and
  the exact unqualified boundaries.

On a clean checkout of the exact tested code source with NumPy 2.3.5:

```sh
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 \
python scripts/act2_learning/qualify_recurrent_lifecycle.py \
  --output /absolute/new-directory-outside-checkout
```

The new output path must not exist. The runner requires a clean source, all eight
retained trained GRU artifacts, nonempty importable suites, unique test identities,
every planned test started and passed, zero skips, and unchanged source/model
identity. Original directory inodes are intentionally bound: archived copies
are read-only evidence and are not resumable replacement owners.

## Remaining product and scientific boundaries

The finite Notes caller at #6127 / b02850c04dcd40f2703e95cc670df531468fd0e3
already implements original Core callback checks, human AuthBus input, original
Root session/grant, protected sender/FinalUse and fresh Notes goal readback. It
still lacks full original product execution acceptance. Its seed-only native
test creates an unused thread and asserts zero model requests; neither that
seed nor fixture coverage proves the complete authorized effect chain.

The original host request timed out with MCP -32603. The dedicated native seed
run was still queued when the source-status observation was captured. The new
hosted recurrent gate was also queued; the 58/58 result above is an actual local
run, not a claimed GitHub terminal result. The separate opaque HTTP host must
continue refusing ActionSkill without an independent registered goal observer.

This record does not qualify async retries, production Root/AuthBus/FinalUse,
actual reboot continuation, common rollback, hostile-owner authentication, power
loss or full lifetime cost. Boot-mismatch refusal is a negative control, not an
actual reboot-and-resume. Admission.json is cooperative, not an independently
authenticated anti-rollback witness.

The policies still use existing guarded inspect/ensure/stop options. No new
complete-skill selection/composition learner is trained. Controlled file/browser
fixtures and deterministic generated goals cannot establish new real application,
version or fault-family benefit. New fits and independent real-task episodes are
both zero. ACT2/ACT3 efficacy findings are unchanged; learning gain, production
adoption and promotion remain false. The next empirical gate needs actual
application adapters and an externally sourced frozen task roster, both policies
using the same execution host, and original outcome plus lifetime-cost records.
