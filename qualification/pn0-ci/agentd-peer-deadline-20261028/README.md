# PN0 Agentd peer admission and deadline source follow-up

This is an incremental source handoff under the existing PN0 plan. It does not
replace any original native test or acceptance condition. The source is an
uncommitted ROG candidate on d3284e385e2b6037dd86752ddd246b616144a87c; local root
alone integrates, commits and normally publishes the original docs branches.
The reviewed published input is bf36d10a54db1d9453409a432cb4641c9fbe38e8,
tree803e1e9b12efa4dd236ecd99333a717b5d52b033, with actual preview
c4f58e535d69a8748484df722743e279cbb1dea5. A patch context match is not an
execution receipt for that tuple.

## Responsibility and interface

`hepta-agentd/src/control.rs` owns admission. It now calls the existing
`UnixStream::ensure_current_user_peer` before allocating a permit, emitting an
overload response or spawning a connection task. An unsupported or failed peer
check still closes the stream. In particular, the Windows implementation remains
`Unsupported`: this patch introduces no PID-to-SID substitute or authority.

`codex-uds` exports `guard_future_before_deadline(Instant, Future)`. The private
module checks the monotonic deadline before each poll of the original future.
Its result is `Some(original_result)` or `None` at expiry. It has no timer,
dependency or feature addition. The two actual Agentd futures remain inside their
existing `timeout_at`, which supplies wakeup and cancellation. Acceptance uses
one two-second deadline; overload uses its minimum with the original fifty
milliseconds. The original thirty-two connections and all frame bounds remain.

This is a poll admission check. It cannot interrupt synchronous work in one poll,
future construction, or a blocking destructor. It does not claim hard realtime,
physical accounting, grant validation or complete caller isolation.

## Actual verification

The attached raw logs and terminal records cover only this new UDS component:

- `just test --locked -p codex-uds --lib --success-output immediate`: thirteen
  passed, zero skipped; 6.631686102 seconds for the owner command. The seven
  original Linux tests and six new tests ran. The original socket tests printed
  no PermissionDenied early-return marker. Nextest's existing configuration and
  package-metadata warnings remain in the raw output.
- `just clippy --locked -p codex-uds --lib -- -D warnings`: exit0, 1.900898118
  seconds. Three existing `clippy.toml` unreachable-type configuration warnings
  were retained, including their duplicate lib-test diagnostics.
- The same scoped cfg(test) Clippy with `--target x86_64-pc-windows-gnu`: exit0,
  7.547444038 seconds. This is conditional compilation only, with no Windows
  link or execution.

The new deterministic tests use a private unit clock for expired, pending,
completed, error and cancellation behavior; a sixth test calls the real public
monotonic entry. That private clock is not a runtime authority. No original test,
assertion, permission, guard, workflow, dependency, feature or lock was modified.
The original UDS test file and all sixty-eight Agentd test/resource files are
preserved. Final formatting and source pins are recorded separately in the
manifest. Commands ended naturally; no earlier model, worker, SDK, supervisor or
PN1 validation budget was restarted.

The initial source-only review blocker is retained: the first candidate checked
only the two-second connection deadline inside the overload future, leaving a
late-poll opening at fifty milliseconds. Its original patch and independent
finding are archived, rather than replaced by this candidate's component PASS.

## Remaining dependency order and acceptance

Local root must first review and integrate the four source paths against the
actual source tuple and preserve the already active CI. This requires fresh
Agentd package validation, actual native Windows tests, exact head/base-preview
checks and normal cross-repository pairing. None ran here.

Windows still needs a genuine consumed peer identity and private namespace,
complete token/ACL/PE-DLL/desktop/stdio/Job/caller and terminal chain, and retained
owner validation. The original broad-delete/legacy-delete and terminal failures
remain OPEN. The FinalUse ordinary protected-clock/external-CAS provider gap is
also OPEN. No identity or guard was enabled to manufacture success.

Ordinary real-model three-round installation and next-task readback, genesis,
I09/I10 custody and release, paid identities and independent WAN acceptance
retain their existing PN0–PN6 contracts. `task_complete=false`,
`merge_ready=false`, **NO_GO**.
