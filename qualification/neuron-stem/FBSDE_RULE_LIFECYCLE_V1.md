# Identified rules remain revocable: current use, observed drift and paid relearning

Base: d4304b2a43c7d016db8c3b08d279951c15acd156, existing Draft PR #1550.
The previously offline budgeted identification patch is landed first unchanged.
This additional experiment uses the original TransferTable and first-informative
identification, not a new production inference/artifact owner or review service.
The original entry gains `revocable_rule_transfer_v1`.

## A past proof is not a current environment fact

An in-family six-state table identifies a stationary historical rule. A caller
holding that table and its old context cannot thereby establish that the same
rule still governs the environment. A research RuleSlot represents one live
owner's current context; it separates known generation changes from silent drift.
A generation increase immediately quarantines the table and invalidates pending
results. A mismatching selected effect does the same even without a new external
generation. Invalid receipts and source errors also fail closed. An immutable
use handle is process-local, one-use and checked again at publication under the
same lock. Reconstructed handle fields, foreign slot instances, late receipts,
and publication while a selected verification is pending are rejected.

Malformed or oversized receipts are reduced to bounded error records before ledger
serialization. They cannot leave a selected verification publishable because
serialization failed. Source error messages are bounded; attempts remain charged.

The source callback executes outside the lock. Its exact request is copied before
exposure, and its reply is checked against the originally issued request, not a
mutable request returned by the callback. A generation change during source work
cannot let that old reply reactivate the table. Actual threaded and reentrant
regressions cover these paths. This is a single-process research state machine,
NOT authenticated distributed authority, a durable WAL or a crash-recovery owner.
A new RuleSlot must be created by an owner that supplies genuinely current context;
constructing arbitrary old slots is not made safe by this class.

## Recovery changes the evidence epoch without deleting history

Retirement leaves prior observations in an append-only, bounded research ledger.
New observations are gathered for a new stationary-model hypothesis; old effects
from the retired environment are not incorrectly conditioned into the new law.
All observations within an unfinished recovery are retained across source errors.
A whole slot has FIVE recovery attempts total, including failed calls. Another
retirement, a resumed call or generation increase cannot refill that allowance.
Reactivation reconstructs full-domain agreement through TransferTable; there is
no method to reinstall an old snapshot after revocation. Unsupported copying or
an inconsistent new rule remains refused. Initial learning is separately charged
up to five calls; verification calls are also separately counted.

This reset source is the same explicit simulator intervention capability as the
parent. It is not an actual production permission. The chosen experimental
recovery cap is not a reset of any original two-observation task. The old 100ms
identification decision check remains; normal RuleSlot use and recovery-decision
work are separately bounded. Source callback time, construction, audit and ledger
work are measured, not assumed free or covered by a preemptive realtime limit.

## Fixed full comparison and unavoidable limits

All 33 source rules are evaluated with no filtering. Scenarios are stable, an
announced move to the next rule, the same move without notification, and a silent
nonbijective copy. The successor is fixed by inventory order before execution.
Each scenario has 33 episodes, each with all six target states. Five controls
produce 660 episode records / 3960 target requests. These are related generated
finite mechanisms, not independent authors, neural learning or future windows.
The source is stationary after the single declared change in each episode.

First complete run, correct/published out of 198 target requests per scenario:

| Scenario | Unguarded historical table | Generation fence | One sentinel | Verify each | Direct source |
| --- | ---: | ---: | ---: | ---: | ---: |
| Stable |198/198|198/198|198/198|198/198|198/198|
| Announced new rule |94/198|198/198|198/198|198/198|198/198|
| Silent new rule |94/198|94/198|160/198|198/198|198/198|
| Silent copy |0/198|0/198|0/0|0/0|198/198|

In silent in-family drift the one-sentinel method still makes 38 wrong results.
Checking one state does not authenticate the other five; the regression explicitly
constructs indistinguishable observations with different unobserved transitions.
Verify-each uses 231 validation calls plus 112 recovery resets there; the direct
source uses only 198 calls and is cheaper in local CPU. Initial learning consumes
112 calls per scenario for each table-based control and zero for direct source.
No resource or capability dominance over direct observation is claimed.

A mismatching proposed result is not published. After at most one paid recovery,
a fresh handle may make ONE additional verification attempt for that target;
both observations are recorded. This is a fixed two-attempt research comparison,
not retry-until-green. Copy is refused by the narrow family even though direct
source measurement can report its realized result. Zero errors after complete
verification depends on correct observations and no intervening change; it is not
a calibrated risk bound or protection against arbitrary hidden nonstationarity.

Run with the original entry and saved-evidence mutations:

    python fbsde_study.py --profile revocable_rule_transfer_v1 --output /new/lifecycle
    python fbsde_lifecycle_artifact_checks.py -v /new/lifecycle

The auditor imports neither the lifecycle controller nor learning/planning code.
It reconstructs the finite source effects, exact query sequence, current-use ledger,
retired handles, restored support, denominators and CPU sums. Hashes are not source
authentication. Native final-use, revocation persistence, independent efficacy,
new pretrained inference and full repository CI remain separate. Keep Draft.
