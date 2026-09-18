# Durable timer-owner lifecycle

The existing `AutomationStore` owns the timer schedule/occurrence data. Schema 4
adds one durable lifecycle row in `migrations/0005_timer_lifecycle.sql`;
`src/timer_lifecycle.rs` implements `timer_status`, `quiesce_timer`,
`handoff_timer`, `resume_timer` and `retire_timer`. The existing scheduler uses
the same fenced `claim_due`; there is no second scheduler, owner registry or
alternate effect path.

The trusted Agent host retains its per-Agent writer lock and management
approval. To replace a compatible timer consumer, stop new claims with
`quiesce_timer`, settle each leased occurrence and explicitly reconcile unknown
queue admissions. An expired lease or timeout is not proof of non-admission.
`handoff_timer` refuses undrained work, increments the writer epoch in the same
SQLite transaction, and returns a separately pooled successor that remains
**draining**. Install the successor consumer before calling `resume_timer`.
All predecessor timer mutation methods reject with `TimerFenced`; closing the
old pool cannot close the successor. Timer fencing degrades only the optional
automation task, unlike an Agent identity/generation violation.

Compatible rollback follows the same sequence into another newer epoch, reusing
current authoritative data. It never restores old receipts, occurrence counters,
writer handles or cancelled schedules. A crash after epoch publication but
before the successor opens leaves a draining store that the authorized host can
reopen. A missing lifecycle row is corruption, not an instruction to reactivate.
Epoch exhaustion rejects rather than wrapping.

Retirement publishes a permanent tombstone after leased/uncertain work drains.
Pending occurrences, schedule state, counters and receipts remain for audit but
cannot be dispatched by reopening the timer. This is one row update rather than
an unbounded backlog rewrite. It does not certify terminal external effects:
App Server queue acceptance is still only acceptance. Schema migration requires
exclusive maintenance with old binaries stopped; schema-3 binaries cannot be
used as rollback readers/writers of schema 5.

This concrete path covers the local **timer domain**, not TaskFlow structural
runs/step effects, arbitrary schema conversion, cross-host transfer, signed
fleet topology selection or automatic live Agentd consumer replacement. Those
boundaries need their own existing owner adapters and qualification; timer
retirement must not be reported as whole-module or whole-framework retirement.
`tests/retirement_recovery.rs` exercises real stores, scheduler cutover, restart,
unknown admissions, stale writers, concurrent handoffs, retained evidence,
independent Agents, corruption, epoch overflow and 32 compatible replacements.
Source test presence is not a test-pass or production-admission receipt.

## Reproduce the owner regressions

From `codex-rs`, run the repository's normal entry point:

```text
just test --locked -p codex-hepta-automation --test retirement_recovery
just test --locked -p codex-hepta-automation --test automation
cargo clippy --locked -p codex-hepta-automation --all-targets -- -D warnings
just test --locked -p codex-hepta-agentd
```

The scheduler regression uses the real store and scheduler with a recording
queue adapter; it is not a real App Server process or external-effect test.
The full Agentd process qualification remains required independently. The
recorded local SQLite smoke checks use the actual migration SQL and statements,
not the Rust compiler or SQLx runtime. Keep those evidence classes distinct.
