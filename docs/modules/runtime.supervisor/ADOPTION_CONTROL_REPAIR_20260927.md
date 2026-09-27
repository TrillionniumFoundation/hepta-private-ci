# Adopted-process control recovery amendment

## Scope and provenance

This amendment continues PR #1057 on `fix/runtime-supervisor-remediation-20260927`.
The reviewed parent is `90e366f61804e26c99efefe78caca0c2a469add8`, based on
main `a126987b84737dbc2ee2592442a314117bddb4a2`. It supplements
`MAIN_CONTROL_RETRY_REPAIR_20260927.md`; it does not replace prior qualification
records or certify another branch. The commit containing this amendment is a
source candidate, not a passing execution receipt.

## Corrected failure paths

The prior `recover_slot` called `request_stop` for a persisted Failed lifecycle
and `kill` for Stopped before installing the adopted process in `AgentSlot`.
A driver error returned from recovery while dropping that exact owned handle.
The lease remained on disk, but the running supervisor no longer owned a handle
that its ordinary tick could retry. The prior Draining branch also reconstructed
an acknowledged runtime phase without resending the drain request: the daemon
could have crashed after the registry CAS and before peer acknowledgement.

Recovery now computes fallible deadlines before adoption, installs the adopted
handle, and stages a generation-bound pending control request. Only a successful
driver call changes the acknowledged runtime phase and emits the corresponding
control event. A failed request retains the same handle and pending request.
For these normal lifecycle paths, companion recovery is still attempted before
the main signal failure is returned to the recovery report.

A separate defect affected adopted unadmitted releases. Recovery already retained
such a process as fenced and Stopping when its kill failed, but tick returned
before the Stopping escalation whenever `runtime.fenced` was true. The new tick
path retries termination of that owned exact process independently of ordinary
pending-control admission. Fenced work remains ineligible for serving, healthy
promotion and automatic restart. Ordinary pending control continues to reject
fenced or mismatched spawn generations.

Generation mismatch now establishes a logical fence before the main kill attempt;
it does not manufacture an acknowledged Killing phase. Tick polls the exact owned
process even after a main signal failure. An observed exit can therefore reconcile
its lease without requiring a successful kill against an already exited child.
A successful kill is not reissued on subsequent ticks merely because the process
has not yet been observed to exit.

## Regression source mapping

`codex-rs/hepta-supervisor/src/recovery_control_tests.rs` adds ten library cases:

| Requirement | Test |
| --- | --- |
| Failed recovery stop retains ownership and retries | `failed_recovery_stop_retains_exact_handle_and_retries` |
| Failed recovery kill retains ownership and retries | `failed_recovery_kill_retains_exact_handle_and_retries` |
| Durable Draining is not a peer acknowledgement | `recovered_draining_state_does_not_fabricate_a_drain_acknowledgement` |
| Repeated retry cannot extend the recovery stop deadline | `recovered_failed_stop_escalates_at_its_original_retry_deadline` |
| Release fencing does not suppress termination retry | `unadmitted_release_fence_does_not_disable_failed_kill_retry` |
| A failing poll cannot suppress a fenced kill attempt | `fenced_termination_is_attempted_before_a_failing_poll` |
| Failed kill does not hide exact observed exit | `exact_fenced_exit_is_reconciled_even_when_kill_returns_an_error` |
| Generation fencing does not mutate the newer registry generation | `generation_fence_signal_error_does_not_hide_an_observed_exit` |
| Acknowledged termination is not reissued or promoted healthy | `acknowledged_fenced_kill_is_not_reissued_and_never_becomes_healthy` |
| Rejected adoption never signals the unrelated process | `rejected_identity_never_gets_a_termination_signal` |

The fixture uses real temporary FleetRegistry and lease files with an explicitly
injected ProcessDriver. Signal and process observations are deterministic test
doubles. This is not native Agentd execution, a kernel PID-reuse experiment,
SIGKILL recovery, storage power-loss qualification, or a target-host measurement.

## Validation boundary

Original `recovery.rs` and `tick.rs` bytes were checked against their Git blob
identities before editing. The uploaded Rust candidate blobs matched the local
candidate bytes. A scoped local Git whitespace check was performed. No Cargo
manifest, dependency, authority key, workflow, CI result policy, main reference,
or production status flag is changed by this source patch.

Rust compilation, the ten regression executions, rustfmt and strict Clippy were
not performed in the editing environment, which has no Rust tools and could not
resolve GitHub for a direct checkout. The existing branch CI must execute the
actual candidate. Queued jobs, a new test source file, a parent result, or a
static check is not a successful native qualification.

Expected native verification includes the complete supervisor library, existing
main/companion recovery tests, default/production product profiles, formatting
and strict lint. The targeted regression entry point is:

```sh
cd codex-rs
just test --locked -p codex-hepta-supervisor --lib recovery::control_tests
```

## Remaining safety and delivery gates

This patch does not close the five-stage remediation program. In particular:

- Stop/kill supersession of a durable pending restart is still not a durable
  operator-command cancellation protocol. An adopted runtime is not, by itself,
  proof that a pending restart refers to a replacement rather than its predecessor.
- The follow-up `EXIT_FINALIZATION_RETRY_20260927.md` adds identity-bound local
  retry for main-process lease unlink and finalization. Cross-daemon crash cuts
  and Matrix cleanup still require separate work and target-host qualification.
  Missing leases are not globally accepted as a shortcut.
- Spawn lease-publication failure with failed cleanup, release conversion failure
  before handle installation, and the unadmitted-release early return before
  companion adoption require separate owned-handle/reconciliation coverage.
- Recovery deadlines are bounded within this daemon lifetime, not a durable
  monotonic budget across repeated supervisor crashes. This amendment adds no
  durable deadline or independent freshness witness.
- Per-Agent mutation ownership, a short global release commit boundary, and
  256-process mixed-load isolation are not implemented by this patch.
- Main CI, exact source and merge-candidate qualification, real external trust
  distribution/rotation/revocation, real caller-to-audit product execution, named
  target-host fault/soak tests and independent security/operator acceptance remain
  gates before activation or release.

Keep `IMPLEMENTATION_MAP.sourceBase` as historical provenance. Actual qualified
commit/tree and artifact identities belong in externally produced execution
receipts; inserting the source commit's own unknown hash is not a valid freshness
mechanism. No acceptance, activation or release declaration is raised here.
