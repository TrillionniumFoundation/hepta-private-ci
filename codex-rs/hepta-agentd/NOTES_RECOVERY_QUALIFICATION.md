# Original owner and real Notes process crash qualification

This is a source-bound qualification recipe. Results must record actual commit
and binary digests; the existence of the recipe or an ignored test is not a
passing receipt. Production Root/issuer wiring, native guest, power loss and
physical display/input are separate qualifications.

## Implementation paths

| Module | Responsibility |
| --- | --- |
| `hepta-memory/src/production_notes_previous.rs` | Match the explicitly selected old target/op ID to the original retained operation and expose only original recovery/retirement |
| `hepta-agentd/src/notes_recovery_process.rs` | Verify and seal helper bytes, create the private pair, bound startup, constrain child lifetime, restart only after its own observed reap |
| `hepta-agentd/src/production_writer_host.rs` | Associate predecessor recovery with the fixed current Notes destination without registering an old effects dispatcher |
| `hepta-agentd/src/notes_organ.rs` | Run the existing finite Notes control/reconciler after successful explicit predecessor attachment |
| `hepta-agentd/src/production_notes_crash_owner_tests.rs` | Original SQLite/FinalUse path with actual companion Session/App/helper processes and deliberate response loss |
| Desktop `ui/core/src/notes_store.rs` | Application-owned durable document, one pending receipt and exact last retirement acknowledgement |

## Source-only checks

From `codex-rs`, using the repository's locked toolchain and dependencies:

```sh
just test --locked --cargo-profile dev-small -p codex-hepta-memory \
  -E 'test(notes_explicit_previous)'
cargo check --locked --profile dev-small -p codex-hepta-agentd
just test --locked --cargo-profile dev-small -p codex-hepta-agentd --lib \
  -E 'test(notes_literal_)'
```

The memory tests use an explicitly simulated application channel. They verify
that absent, queued and mismatched operations are rejected before channel I/O,
attachment leaves the source cut unchanged, discovery is unnecessary, old
dispatch is refused, and committed source retirement can resume after the
original SQLite owner is closed and reopened. They are not real app tests.

## Actual companion test

Build the same Desktop source's `trill-session`, `trill-app-window` and
`trill-notes-recovery` beside each other. The helper must include the
`TRILL_NOTES_RECOVERY_READY_V1` startup marker. Cargo's development output may
be group-writable and hardlinked to its dependency output. The recovery guard
correctly refuses a group-writable executable. Copy all three unchanged
binaries to a fresh private qualification directory, verify both SHA-256
values, and record their custody before running:

```sh
set -euo pipefail
notes_source_build=/absolute/pinned-build
notes_qualification=$(mktemp -d /absolute/evidence/notes-owner.XXXXXX)
notes_qualified_bin="$notes_qualification/bin"
install -d -m 0700 "$notes_qualified_bin"
for notes_name in trill-session trill-app-window trill-notes-recovery; do
  install -m 0500 "$notes_source_build/$notes_name" "$notes_qualified_bin/$notes_name"
  notes_source_sha=$(sha256sum "$notes_source_build/$notes_name" | cut -d ' ' -f 1)
  notes_staged_sha=$(sha256sum "$notes_qualified_bin/$notes_name" | cut -d ' ' -f 1)
  test "$notes_source_sha" = "$notes_staged_sha"
  printf '%s source=%s staged=%s\n' "$notes_name" "$notes_source_sha" "$notes_staged_sha" \
    >> "$notes_qualification/companion-sha256.txt"
  stat -c '%n uid=%u gid=%g mode=%a links=%h' \
    "$notes_source_build/$notes_name" "$notes_qualified_bin/$notes_name" \
    >> "$notes_qualification/companion-custody.txt"
done
chmod 0500 "$notes_qualified_bin"
```

Do not change permissions on Cargo's hardlinked originals or relax the helper
guard. The staged files are independent single-link copies with the same
bytes. Keep any failed runtime log alongside the staging records. Start an
isolated test-owned Xvfb/display, then use these absolute staged paths:

```sh
TRILL_NOTES_PROBE_ISOLATED=1 \
HEPTA_NOTES_SESSION_BIN="$notes_qualified_bin/trill-session" \
HEPTA_NOTES_CRASH_QUALIFICATION_OUTPUT="$notes_qualification/notes-crash-owner.json" \
just test --locked --cargo-profile dev-small -p codex-hepta-agentd --lib \
  -E 'test(notes_actual_app_crash_original_owner_reopen_and_helper_ack_restart)' \
  --run-ignored ignored-only --no-capture
```

Only this ignored durable lifecycle qualification has a 240-second complete-run
watchdog and no automatic retry. All original per-operation deadlines and
assertions remain in force. Its elapsed stage diagnostics explain progress;
only the complete successful oracle and retained JSON qualify the run.

The test uses a temporary Fleet and real original SQLite writer, an explicitly
test-only source authority/verifier and FinalUse issuer, and three actual
Desktop binaries. It sends one complete real effect through the original
dispatcher, discards that effect response, waits for the app's saved state,
SIGKILLs only its retained Notes child pidfd, and asks the same original Session
to reap it. It closes every original writer/store handle and reopens against
the independently retained exact current cut with that same fixture authority.

A second real Session creates a fresh current target. Its previous receipt
query must still return null. The original writer then attaches only the old
operation through the independent real helper. Its actual Observe receipt
must move source state from `Indeterminate` to `Committed`. A test wrapper
drops the first retirement response only after the helper has returned from
its durable retirement. After killing and reaping that helper, the same
original source retries its exact ACK against a second helper and receives
`already_released`.

Assertions cover exactly one effect entry and one fixture grant request, no
old dispatcher, unchanged fresh-incarnation document, unchanged old text and
revision across retirement/helper restart, exact target/payload/receipt hashes,
and two helper starts. Output includes real binary digests, source cuts, actual
application/retirement responses and the Session logs. It explicitly marks
production authority, native kernel, power-loss and pixel qualification false.
Read test logs on a failure; do not remove old locks, reset identity, manually
edit the source ledger or mark an unknown effect as failed to force a pass.
