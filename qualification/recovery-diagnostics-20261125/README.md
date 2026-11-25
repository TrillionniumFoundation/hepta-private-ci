# Recovery rejection diagnostics

This change is a diagnostic candidate. It does not fix or qualify recovery.
The original Windows live-recovery fixture timed out before obtaining an idle
recovery epoch. The original GNU/musl cold-suspension fixture obtained its
public epoch, then returned `RecoveryStateChanged`. These are distinct observed
failure points; their causes have not yet been established.

The two existing fixtures register a bounded test-support observer for their
exact session. At most eight observers retain eight event summaries each.
Registration and observations use `try_lock`; unavailable or poisoned locks
remain unavailable. The snapshot is explicitly non-atomic and incomplete.
An absent observation never proves that a rejection branch was not taken.

The handle retains only the original state-only `TurnRecoveryAuthority` Arc
and a weak session identity. It does not retain a running task, execution
lease, environment, or admission guard. The authority contains an atomic Ready
flag and a mutex around generation numbers, states, hashes and replay DTOs; it
has no custom Drop implementation or execution guard.

Registered observations identify the original live-publication rejection and
four cold-admission rejection paths. Context comparison reports hashes,
booleans and the union of differing top-level field names, including fields
omitted from one side by serde. It does not print history or payload values.
With no registered observer, details are not constructed. No recovery
condition, epoch update, retry, timeout, lock waiting, or reset is introduced.

Validation so far: repository `just fmt` and `git diff --check` succeed.
No new Core build or native execution has been performed for this candidate.
The next original qualification run must bind its own exact source and retain
any failure; a diagnostic observation is not a passing recovery result.
