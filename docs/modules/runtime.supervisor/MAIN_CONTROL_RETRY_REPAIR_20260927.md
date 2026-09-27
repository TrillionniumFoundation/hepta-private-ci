# Main-process control acknowledgement and retry repair

## Scope and evidence boundary

This is a continuation of PR #1057 on its existing supervisor remediation
branch. The input candidate is `986561699bbe4869023813004311db8be7694784`.
The amendment does not claim completion of the five-stage production plan.
No independent acceptance, production activation, release, key provisioning,
branch-protection exception or main merge is supplied by this change.

The former `control.rs` assigned Draining, Stopping or Killing before the
corresponding driver call succeeded. In particular, a failed explicit kill
could leave a live process in Killing with no subsequent signal retry. Initial
health-timeout handling had a related cut: the durable lifecycle could become
Failed before stop failed, without retaining an explicit stop intention.

## Implemented control boundary

`control_pending.rs` provides one bounded in-process pending control per Agent.
It names the owned process spawn generation and retains the original deadline.
A control error is not evidence that the OS or the child observed no effect.
Retries use the same managed handle and rely on the driver's exact-process
identity checks; they do not resolve an unrelated PID or mint new authority.

The transition rules are:

| Input | Retained intention | Acknowledged phase/event |
| --- | --- | --- |
| Drain/stop/kill driver error | Keep the exact intention and handle | Do not acknowledge the failed call |
| Successful driver return | Clear pending intention | Publish the corresponding phase/event |
| Repeated drain or stop | Keep earliest applicable deadline | Never replenish the same action's time budget |
| Stronger pending action | Kill dominates stop; stop dominates drain | A later weaker request cannot downgrade it |
| Delayed pending drain | Escalate against the original drain deadline plus stop grace | A sufficiently late retry may proceed directly to kill |
| Different spawn generation or fenced runtime | Discard stale in-process intention | Do not signal the replacement process |
| Exact observed process exit | Reconcile the existing durable lease and lifecycle | Clear intention only after successful exit finalization |

`tick.rs` attempts retained control before polling, but still polls after a
signal error. This lets an exact observed exit progress through existing durable
cleanup even when a signal to an already exited process returns an error. A
poll error cannot prevent the preceding pending kill attempt. Registry, probe
or control errors invalidate stale readiness and retain the process handle.

A retrying control operation cannot enter the healthy-start promotion branch
in the same tick. A restart whose control request encounters a retryable driver
error retains its already-published restart claim in memory rather than silently
losing the intended replacement. Earlier non-driver failures are not converted
to successful control requests.

## Regression traceability

All following names are under `control::tests` in the library binary
`codex-hepta-supervisor`; `control_retry_tests.rs` is a separate test module.

| Requirement | Regression names |
| --- | --- |
| SUP-CTRL-ACK-001: no false acknowledgement; retry exact handle | `failed_kill_is_retried_by_tick_without_false_acknowledgement`, `failed_stop_is_retried_without_publishing_stopping`, `failed_drain_is_retried_without_publishing_draining` |
| SUP-CTRL-TIME-002: monotone control and original time budget | `repeated_stop_preserves_the_first_deadline`, `delayed_drain_retry_cannot_replenish_termination_budget`, `pending_kill_cannot_be_downgraded_by_a_later_drain` |
| SUP-CTRL-GEN-003: stale intention cannot affect successor | `stale_pending_control_never_signals_a_replacement_generation` |
| SUP-CTRL-OBS-004: error/exit observations retain correct ownership | `main_poll_error_invalidates_readiness_and_retains_ownership`, `pending_kill_is_attempted_even_when_polling_fails`, `signal_failure_does_not_block_exact_observed_exit_cleanup` |
| SUP-CTRL-START-005: failed startup stop is not promotion | `failed_startup_stop_cannot_repromote_on_a_later_healthy_probe` |
| SUP-CTRL-RESTART-006: preserve the published restart claim | `restart_retains_its_claim_when_the_first_drain_signal_fails` |

The fixtures use a real temporary FleetRegistry and exact persisted process
lease, with a deterministic injected ProcessDriver. They do not launch real
Agentd children and are not target-host fault or performance qualifications.

The local CI follow-up patch extends both default and production-authority
library plans from 29 to 41 mandatory named owner/read/recovery/control cases.
It retains the seven independent plans, 19 production product cases, nine
default product cases, exact binary binding, zero-retry policy, strict lint and
failure-preserving aggregation. Four local Python policy regressions reject
missing cases, foreign binaries and the old record minimum.

The remote write of `scripts/hepta_supervisor_ci.py` was blocked by the tool
safety check. That update and the dependent change to
`scripts/test_hepta_supervisor_evidence.py` were NOT published or retried through
another write route. Consequently this remote source continuation retains the
parent CI plan and its 29 mandatory library cases. The 12 new Rust tests are
part of the normal library test suite, but their explicit 41-case receipt gate
remains an unapplied local follow-up. Do not infer that it is already enforced.

## Validation actually performed for this continuation

The editing container ran 32 selected Python evidence/record/filesystem tests
against the LOCAL CI follow-up overlay, with zero failures and zero skips.
These are not execution results for the remote source-only commit. This selection comprises TranscriptTests,
JsonTests, FileTests, MainControlRequirementTests, and the two companion
transcript-substitution tests. The companion source-inventory test, the wider
workflow suite and full receipt assembly were not executed in this selection.

The retrieved originals of all five modified existing files were reconstructed
and matched to their Git blob SHA before editing. The unchanged evidence parser
also matched its source blob. Python AST and patch whitespace checks are local
preflight checks only. Rust compilation, rustfmt, Clippy and the 12 new Rust
regressions have not been executed in the editing container; its Rust toolchain
is absent and direct GitHub download/clone access failed. Exact-candidate hosted
execution remains mandatory. A queued workflow is not a successful execution.

## Remaining production gates

The retry intention is deliberately in memory. It is not a replacement for a
crash-persistent operator command journal, signed recovery, registry CAS or
external approval. Daemon restart still uses the existing lease/lifecycle,
restart-budget, release-transaction and signed-intent recovery boundaries.
Explicit stop/kill cancellation of every durable restart cut, late I/O failure
after lease removal, and artifact/system-manager crash recovery still require
separate audit and real fault-injection evidence.

The current daemon still serializes mutation/tick ownership. This change does
not introduce per-Agent actors, a short global release coordinator, 256-process
mixed-load qualification or a target-host latency guarantee. Existing immutable
read observations are not equivalent to those results.

Required checks must pass on the final source and deterministic merge candidate,
then on main after a non-bypassing merge. Preserve `IMPLEMENTATION_MAP.sourceBase`
as historical provenance; use execution receipts outside the source commit to
bind the actually tested commit/tree, commands, profiles, logs and artifacts.
Do not replace a historical provenance field with a self-referential head claim.

The real caller-to-daemon-to-process-to-durable-state-to-audit chain, externally
provisioned key distribution/rotation/revocation, named Linux/macOS deployment
fault matrix and soak, final artifact digests, separately identified reviewer
acceptance and an independent recovery drill remain release gates. None is
made true by passing these local policy tests or by writing the Rust tests.
