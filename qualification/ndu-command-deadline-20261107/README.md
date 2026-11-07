# Bounded command termination and retained outer receipts

Status: **LOCAL_CONTRACT_PASS / PUBLICATION_BLOCKED / SCIENTIFIC_HOLD**.

The actual adapter canary at source `1e869d455fe2fb53b5221b84bc0a27e190b09ab2`
was cancelled by the 30-minute workflow limit. Its independent-session training
child had not returned, and the outer receipt remained `started`. This change
adds bounded parent supervision and signal-aware finalization. It does not
change the prior Failed/partial result or supply a missing model experiment.

## Behavior

The command meter accepts `--wall-timeout-seconds` and a finite positive
termination grace. The workflow declares a 1,500-second outer training limit,
leaving room before its existing 30-minute job deadline. The two-update design,
model dtype and internal 600-second CPU/wall allowances are unchanged.

Timeout, SIGTERM and SIGINT stop the inherited process group. After a bounded
TERM grace, the meter sends KILL even when the leader already exited and an
ignoring descendant remains. The direct child is waited for within a bounded
cleanup interval. The wrapper's timeout/cancellation status is kept separate
from the actual child return code, including a child that handles TERM and exits
zero. A normally exited leader with a remaining process group is also a failure.

Original signal handlers are restored. Repeated cancellation does not interrupt
cleanup. The final receipt is atomically replaced and cancellation observed
during cost collection or the final write is reconciled. It preserves observed
costs and explicitly marks unreaped descendant usage as unknown. Inclusive
command costs must not be added to nested trainer or action costs.

This is POSIX inherited-process-group containment. Descendants that create a
new session/group are outside the contract. A killed orphan zombie can keep
`group_still_present=true`; that fact is retained. SIGKILL, host loss, a blocked
kernel operation or failed receipt storage cannot be guaranteed away in Python.
The process-lifetime RUSAGE_CHILDREN high-water mark is explicitly labelled.

## Executed verification

- **79/79** original focused workflow tests passed, zero skips. This includes
  the **13** meter tests (11 new); those counts must not be added together.
- **7/7** independent real short-process probes passed on the final source:
  success, timeout, SIGTERM, SIGINT, repeated cancellation, a successful leader
  leaving an ignoring descendant, and spawn failure. Their original receipts,
  outputs, stderr and runnable probe are retained.
- `just fmt` exited zero and reported no changed files in its owned formatting
  scope. All three changed source hashes were unchanged. `git diff --check`
  passed.

[VERIFICATION.json](VERIFICATION.json) binds the source, counts and archive.
[execution-evidence.zip](execution-evidence.zip) retains both author attempts,
the focused outer CPU/wall receipt, initial and final independent reviews, source
snapshots and exact logs. These are command-lifecycle checks, not independent
training fits or scientific observations.

## Publication and learning boundary

GitHub rejected further writes with HTTP 403 and the message
`Sorry. Your account was suspended`. This change is local and included in the
reviewable recovery package; it has not been hosted or run with the real models.
The new branch is outside the adapter workflow's push-trigger list.

A timed-out command receipt does not by itself establish NoUpdate. Formal
learning still requires the prospective finite contract, complete inventory,
independent evaluation and authenticated owner continuation. No V5 update,
adoption or positive-gain reward is authorized by this work.
