# Companion recovery and ownership repair — 2026-09-27

## Source and claim boundary

This continuation is based on remediation candidate
`7d07ffc2519bee04e26f2c2d514b569f05263192` in PR #1057, whose main base is
`a126987b84737dbc2ee2592442a314117bddb4a2`. It preserves the preceding signed
recovery, pinned-verifier, daemon owner-lifetime and exact-candidate CI work.
It does not assert completion of the five-stage production remediation.

## Defects addressed

### SUP-RECOVERY-MATRIX-001: restore charges before adoption

The Matrix companion wrote its restart window through the canonical restart
record, but public `Supervisor::recover` did not hydrate that window. Calling
the old unused restore helper would also restore the main Agent projection
from the companion record, conflicting with the independent main restart port.

`restore_release_state` now validates and stages only the companion window.
This happens in the fatal durable-state portion of startup, before any process
adoption can charge or publish a new companion window. `recover_slot` applies
the staged state using the caller's monotonic clock before reading process
leases. The canonical main budget is never replaced by that projection.

Foreign Agent identity and corrupt/unreadable state reject startup. Clock
rollback is normalized to exhausted budget and durably published before process
adoption; an expired window is durably cleared. Reopening the daemon cannot
repeatedly reuse a future-dated, undercharged window. Release mismatch alone
never erases charges: adoption may still recover an in-flight target release.
A partial budget reapplies conservative full backoff because the companion
journal does not retain an exact next-eligible timestamp.

The six unused legacy main-slot projection fields and their unused restore/reset
helpers are removed. The active main restart pending/attempt/not-before port and
the on-disk main/companion codec remain unchanged.

### SUP-OWNER-MATRIX-002: keep a handle through failed boundaries

Companion tick previously took its runtime out of the slot before several
fallible poll, signal and lease-cleanup operations. An early error could drop the
exact handle while the operating-system process remained live. Some signal
paths also published `Stopping` or `Killing` before the driver accepted the call.

Tick now borrows the retained runtime in place. Failed observation invalidates
cached health, while ownership remains available for retry. The handle is
removed only after an exit observation and successful exact lease cleanup.
Failed stop/kill does not publish the corresponding acknowledged phase. The
same signal ordering applies when stopping a companion for a deferred Agent
action. A deferred generation-bound action survives a callee that clears its
transient intent and then fails; success or proven inapplicability clears it.

Companion tick and its fault-injection tests are extracted into private sibling
files, without creating a second writer, public test API or parallel release
coordinator. These are driver-injection regressions, not real target-host crash
or power-loss qualification.

## Required regression cases

Seven cases in `restart_state_tests.rs` cover public recovery, repeated reopen,
foreign identity, clock rollback with main-budget preservation, expiry,
conservative backoff, and exhausted-budget replacement blocking.

Seven cases in `matrix_tick_tests.rs` cover poll, stop, kill, generation-mismatch
kill, exact lease-cleanup failure, deferred Agent stop, and deferred companion
stop. They assert retained ownership and retry semantics.

Both default and production-authority library plans now require all 29 named
binary/test pairs: the existing 15 owner/read cases plus these 14 cases. The
19 production product cases and nine default product cases are unchanged.
Missing, skipped or wrong-binary cases cannot be substituted by aggregate pass
counts. Three additional Python regressions enforce the new case inventory and
reject same-total and wrong-binary substitutions through the actual validator.

## Validation performed and pending

Executed in the editing container:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest -v \
  scripts.test_hepta_supervisor_evidence
```

Result: **29 Python tests passed, zero failed, zero skipped**. These use local
filesystem and synthetic reporter fixtures; they are not Rust execution
receipts. The unmodified validator and base copies used for editing were checked
against the fetched Git blob identities where reconstructed.

Rust/Cargo/just/rustfmt were not available in this editing environment, and the
container could not resolve the remote repository for checkout. Therefore the
14 new Rust tests, Rust type checking, rustfmt, Clippy, Bazel, real processes and
full qualification assembly have **not** been executed here. Native gates must
run against the final source/head and prospective merge, not this parent.

## Remaining production gates

Keep the gates in `PRODUCTION_CONTROL_RUNBOOK.md`, `OWNER_AND_READ_ISOLATION.md`
and `QUALIFICATION_EVIDENCE_V2.md`. In particular:

- Exact-candidate CI/Architecture/Agentd/Supervisor gates still need observed
  successful completion; written workflow jobs and queued runs are not passes.
- The named caller needs real external key provisioning/rotation/revocation,
  controlled durable writer ownership, and a full authenticated product chain.
- Mutations and tick remain serialized. Per-Agent actors, a short global commit
  boundary, 256-process mixed-load SLOs and histograms remain outstanding.
- Final artifact digests must bind named-host crash/storage/PID/drain/release/
  service/permission/soak evidence. Driver-injection and observation-cache tests
  are not substitutes for that execution.
- Independent security/operator acceptance and a real recovery drill must be
  performed by separately identified reviewers/operators before activation.

Do not rewrite historical `IMPLEMENTATION_MAP.sourceBase` to impersonate a
qualified head. The existing qualification assembler binds the actual tested
commit/tree and source blobs in an external execution receipt only after all
required suites succeed. No deployment, acceptance, activation or release flag
is raised by this continuation.
