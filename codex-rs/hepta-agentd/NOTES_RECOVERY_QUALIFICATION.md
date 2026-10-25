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
just test --locked -p codex-hepta-memory -E 'test(notes_explicit_previous)'
cargo check --locked -p codex-hepta-agentd
just test --locked -p codex-hepta-agentd --lib --no-run
```

The memory tests use an explicitly simulated application channel. They verify
that absent, queued and mismatched operations are rejected before channel I/O,
attachment leaves the source cut unchanged, discovery is unnecessary, old
dispatch is refused, and committed source retirement can resume after the
original SQLite owner is closed and reopened. They are not real app tests.

## Actual companion test

Build the same Desktop source's `trill-session`, `trill-app-window` and
`trill-notes-recovery` beside each other. The helper must include the
`TRILL_NOTES_RECOVERY_READY_V1` startup marker. Start an isolated test-owned
Xvfb/display, then use absolute paths:

```sh
TRILL_NOTES_PROBE_ISOLATED=1 \
HEPTA_NOTES_SESSION_BIN=/absolute/pinned-build/trill-session \
HEPTA_NOTES_CRASH_QUALIFICATION_OUTPUT=/absolute/evidence/notes-crash-owner.json \
just test --locked -p codex-hepta-agentd --lib \
  -E 'test(notes_actual_app_crash_original_owner_reopen_and_helper_ack_restart)' \
  --run-ignored ignored-only --nocapture --test-threads=1
```

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
