# ui.native current-source development guide

## 1. Candidate identity and scope

The single module candidate is `work/ui-native-current-source-20260925`, based
on main `7ddbfac88525196e7a4b31387ceae194958275f5`. The Rust application root is
recovered from #830 commit `3198549d80d6c59887b82e2c50018ab818217c53`.
Only `apps/hepta-native` is restored from that source tree. Current
`codex-rs/hepta-contracts`, gateway, runtime and domain owners are retained.
A history-only merge is not implementation delivery.

`CURRENT_SOURCE.json`, when generated and committed by the scoped freeze job,
binds every native source, configuration, document and native Cargo lock by
SHA-256. Qualification checks that file set before testing. Exact build SHA,
tree, candidate SHA and merge base are separately recorded by each runner.
Absent fingerprints or a missing lock is an unprepared candidate, not a pass.

## 2. Product and owner topology

`src/main.rs` bootstraps the eframe/egui/AccessKit desktop shell. `src/ui.rs`
contains the presentation. `backend.rs` consumes a signed endpoint manifest
and keyring bearer. `session_store.rs` stores only opaque session references.
Domain state is never written by the UI.

`runtime.rs` owns one mutable shell runtime and its local operation lifecycle.
`journal.rs` owns bounded shell dispatch records, not domain or authorization
facts. `security.rs` consumes the current kernel-owned final-use grant and
synchronous-effect fence; it does not create a UI-local authority issuer.
`platform.rs` applies an additional local permission ceiling.

The current main gateway does not yet accept `--auth-keyring-account` or expose
the authenticated health contract required by this backend. This is remaining
repository implementation work, not an external signing requirement. Do not
turn off backend authentication to make startup appear successful.

## 3. Operation identity and recovery

Operation identity is `(session_id, session_generation, operation_id)` plus
semantic binding to endpoint, subject, displayed revision, action, serialized
payload, final-use binding and grant digest. Same identity with changed
semantics is rejected. The runtime uses owned Rust request values and mutable
borrowing instead of re-reading mutable JavaScript objects after an await.

The journal persists `Prepared -> Invoking -> Indeterminate/Terminal` before
and after the adapter boundary. An uncertain invocation is reconciled, never
blindly re-invoked. The port additionally rejects duplicate recovered keys,
unknown root schema fields, endpoint drift and conflicting terminal receipts.
Persistence failure poisons the owner until reopen/reconciliation. Destructive
terminal cleanup is refused until a durable deduplication retirement frontier
exists; reaching the 4096-record/8 MiB ceiling is fail-closed, not silent eviction.

Final-use claims use the current kernel authority. The reviewed adaptation
uses its synchronous active-effect fence. This does not itself solve bounded
OS launcher waits, global registry lifecycle, or all physical-path races.
Those still require validation before enabling production effects.

## 4. Updates and rollback

`updater.rs` verifies signed stable-channel manifests, exact package digest,
platform/architecture, backend version, independent selector identity and
installed predecessor. The independent updater helper performs replacement.
`ActivatedUnconfirmed` must be confirmed against the installed running binary.

The adaptation adds a shared per-transition GUI/helper writer lock, signature
verification when reopening pending state, installed-target identity checks,
refusal to erase unresolved update state, and rollback comparison against the
admitted candidate/predecessor. An unrelated installed binary must not be
overwritten by stale recovery. Missing/bad predecessor evidence leaves durable
`RecoveryRequired`, not a fabricated rollback success.

Full pending-record path trust, hostile symlink races, interruption at every
filesystem cut, and physical OS update behavior remain qualification work.

## 5. Build and tests

The standalone app pins Rust 1.95.0. Once the source freeze has committed
`Cargo.lock`, run from the repository root:

```sh
cargo +1.95.0 fmt --manifest-path apps/hepta-native/Cargo.toml --check
cargo +1.95.0 clippy --manifest-path apps/hepta-native/Cargo.toml --locked --all-targets --all-features -- -D warnings
cargo +1.95.0 test --manifest-path apps/hepta-native/Cargo.toml --locked --all-targets
cargo +1.95.0 build --manifest-path apps/hepta-native/Cargo.toml --locked --release --bins
```

The current-source workflow tests exact candidate and deterministic merge on
Ubuntu 24.04, macOS 15 and Windows 2025 runners. Lint failure does not suppress
independent native test feedback. Test source presence is never a pass receipt.

`tests/journal_regressions.rs` adds terminal immutability, endpoint conflict,
duplicate recovery, unknown schema, persistence-failure fencing, retained
deduplication, session-generation separation and monotonic phase cases.
Existing runtime/security/update tests are retained rather than weakened.

`--self-test` and `--qualification-e2e` use isolated fixtures and fake platform
adapters. The latter kills fixture child processes at durable journal/update
cuts. These are release-binary fault checks, not physical GUI, keyring or
installed-package acceptance, and do not authorize real OS effects.

## 6. Configuration and ordinary-user acceptance

The Rust bootstrap expects absolute `--endpoint-manifest`, `--trusted-keys`
and `--state-dir` inputs. Effects additionally require independently provisioned
`--final-use-authority`; optional local ceilings include `--allow-root`,
`--allow-clipboard` and `--allow-notifications`. Private signing keys must never
be installed in the UI state root or source repository.

The historical setup examples are not presently an executable end-to-end
recipe against current main: authenticated gateway composition is still
missing. Acceptance must run the actual packaged application through normal
startup, trusted connection, displayed state, denied and authorized requests,
shutdown/restart and recovery without selecting a fixture-only profile.

## 7. Platform, accessibility and performance gates

AccessKit and native focusable widgets are implementation foundations only.
Keyboard traversal, screen-reader names/states, IME, Chinese rendering,
multi-monitor DPI, focus restoration and update restart need physical evidence.
Startup, RSS, event latency and long-running journal growth need measurements.

Current kernel sources do not establish Windows durable final-use qualification.
Do not restore obsolete Windows authority code or claim a three-platform pass
because a matrix exists. Windows notification identity is not implemented by
turning on a flag. Signatures, notarization, release selection and independent
operator acceptance remain separate gates, all false until observed.
