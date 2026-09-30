# hepta-native developer guide

This guide applies to immutable implementation source
`ed5fd2229502099addd6bedec2fae18783d5c162`, tree
`4641d2abbf7db038404863b2f6a7975c28977fe1`. The source is an implementation
candidate; production, deployment and release flags remain false.

## Toolchain and source identity

Use Rust `1.95.0` and locked dependencies. Product changes must be ordinary
commits. The sole module workflow is
`.github/workflows/ui-native-qualification.yml`; it has read-only repository
permissions and must never patch, format, commit or push source.

Run structural checks from the repository root:

```bash
python3 scripts/check_hepta_ui_native_convergence.py
python3 -m unittest discover -s scripts -p 'test_hepta_ui_native_*.py' -v
```

These checks reject retired writer/materializer workflows, patch capsules,
write permissions, source drift after the frozen implementation, changed portal
or packaging adapters, stale state anchors and promoted release flags. They do
not replace compilation, crash tests, physical acceptance or release review.

## Build, format, lint and tests

```bash
cargo +1.95.0 fmt \
  --manifest-path apps/hepta-native/Cargo.toml --check
cargo +1.95.0 check \
  --manifest-path apps/hepta-native/Cargo.toml \
  --locked --all-targets --all-features
cargo +1.95.0 clippy \
  --manifest-path apps/hepta-native/Cargo.toml \
  --locked --all-targets --all-features -- -D warnings
just test --manifest-path ../apps/hepta-native/Cargo.toml \
  --locked --all-targets
just test --locked --all-targets --all-features \
  -p codex-hepta-native-gateway -p codex-hepta-contracts \
  -p codex-hepta-private-state -p codex-utils-private-state
```

A formatting change is source. Commit and review it before freezing a new
implementation SHA. Preserve tests for final-use linearization, duplicate
identity, transition legality, WAL framing/checksum/sequence/partial tail,
checkpoint recovery, retirement authority/index rebuild, private-root rejection,
update rollback, task admission, stale picker tickets, resource identity change,
final symlink rejection, durable history paging and shutdown of all lanes.

## Final-use protocol

The shell never signs its own grant. Prepare a binding from the current
authenticated view; an independent owner chooses grant identity, nonce, epoch
and lifetime and signs the complete grant.

```text
validate request
→ resolve adapter confirmation resource
→ durable Prepared
→ local permission
→ final-use claim/current revalidation
→ durable Invoking
→ final policy and verified-use fence
→ platform boundary
→ durable terminal or Indeterminate
```

Do not reorder barriers, cache authorization across mutable work or interpret a
timeout, helper exit or cancellation as known non-execution. UNKNOWN is never
automatically replayed.

## Journal, WAL and retirement

Current schemas:

```text
journal                  hepta.native-operation-journal.v7
WAL                      hepta.native-operation-wal.v1
retirement head          hepta.native-retirement.v3
retirement segment       hepta.native-retirement.v2
retirement index         hepta.native-retirement-index.v1
retirement index bucket  hepta.native-retirement-index-bucket.v1
```

A mutation synchronizes a complete WAL frame before changing memory. A
checkpoint synchronizes the replacement snapshot before truncating the WAL. The
`.previous` snapshot is forensic evidence only. After persistence error, reopen
and reconcile; never retry through the same object or delete history.

Retirement segments and archived records are authority. Manifests, buckets and
cache are rebuildable acceleration. Index uncertainty rejects or rebuilds; it
never makes a retired identity executable.

## Linux picker and verified resource handoff

Linux file selection defaults to XDG Desktop Portal. The selected URI is bounded
to one local absolute path and remains untrusted. Use Zenity only when explicitly
requested:

```bash
HEPTA_NATIVE_PICKER_BACKEND=zenity cargo +1.95.0 run \
  --manifest-path apps/hepta-native/Cargo.toml --locked --bin hepta-native -- \
  <launch arguments>
```

There is no silent fallback. Portal and compatibility adapters use owned child
processes, bounded observation and cleared environments.

Linux Open/Reveal opens with `NOFOLLOW`, binds the open descriptor's
resource identity into final-use confirmation, revalidates the final handle and
passes that descriptor to XDG OpenURI. Do not replace it with `xdg-open`, shell
commands or a second mutable path lookup. Non-Linux path operations remain
fail-closed until they have an equivalent capability adapter.

## Windows identity and notification

The unsigned package includes:

```text
HeptaNative/Register-HeptaNativeIdentity.ps1
```

On a physical Windows qualification host, run the registrar against the exact
packaged executable, inspect the Start Menu shortcut's AppUserModelID, launch the
packaged process and exercise a WinRT toast. Preserve the shortcut identity,
script digest, package digest, logs and screenshots/automation evidence. The
marker must never be pre-created to bypass registration.

## UI lanes and persistent history

Keep one mutation authority. The GUI uses:

- `pending_runtime`: mutation owner;
- `pending_read`: bounded persistent-history page read;
- `pending_picker`: owned native dialog.

Read and mutation admission are mutually exclusive. The picker may run
independently but cannot mutate runtime state. `operation_history_page` returns
newest-first bounded pages; the GUI uses 64 receipts and never clones the full
journal history. Shutdown must cancel only pre-admission work and wait for all
three lanes before update activation.

## Storage qualification

`STORAGE_BUDGETS.json` contains blocking provisional ceilings. The ignored
subjects require the optimized release profile and exercise:

```bash
just test --release --manifest-path ../apps/hepta-native/Cargo.toml --locked --lib \
  --run-ignored only -E 'test(=storage_qualification_tests::storage_active_scale_qualification)' \
  --test-threads=1

just test --release --manifest-path ../apps/hepta-native/Cargo.toml --locked --lib \
  --run-ignored only -E 'test(=storage_qualification_tests::storage_retirement_scale_qualification)' \
  --test-threads=1
```

A manual run is not qualification. The workflow additionally records Linux
write/sync syscalls, validates all hard ceilings and retains raw trace and JSON
artifacts. Process-kill qualification must terminate a real process at each
durable cut point; injected in-process errors are insufficient.

## Packaging, SBOM and provenance

Build a deterministic unsigned package with:

```bash
python3 apps/hepta-native/tools/package_unsigned.py \
  --platform linux --architecture x86_64 \
  --release-dir apps/hepta-native/target/release \
  --out-dir /absolute/new/output
```

The archive has a closed file inventory. Windows includes the AUMID registrar.
Linux declares portal-first picker behavior. Unsigned package receipts always
keep signing, notarization and release flags false.

The qualification seal runs `scripts/hepta_ui_native_supply_chain.py` against the
exact package receipt and emits `sbom.cdx.json`, `provenance.intoto.json` and a
binding manifest. These artifacts bind exact/merge source, candidate, ordered
base, implementation SHA, runner, both Cargo lockfiles and package digest. They
are evidence inputs, not release authority.

## Qualification and troubleshooting

Pull requests evaluate exact head and deterministic ordered-parent merge on
Linux, macOS and Windows. Linux additionally runs gateway/keyring/Xvfb lifecycle
and exact-source storage scale. The aggregate succeeds only when every required
subject succeeds in the same run and attempt.

Common failures:

- **journal already owned:** do not delete lock or state;
- **persistence indeterminate:** stop effects, reopen and reconcile;
- **index failure:** reject or rebuild from verified segments;
- **portal unavailable:** report it; use Zenity only through explicit policy;
- **UNKNOWN effect:** reconcile with an operation-bound observer or close
  observation without replay;
- **Windows toast unavailable:** run and verify the packaged identity registrar;
- **update readiness failure:** deny activation and preserve recovery evidence;
- **cancelled/skipped CI:** rerun unchanged source or create a new candidate;
  never hand-edit the qualification manifest to pass.

Required GitHub administration is recorded in
`docs/modules/ui.native/BRANCH_PROTECTION.md`. A checked-in file cannot enable an
administrator ruleset. Only an independent reviewer may promote the false
production/deployment/release flags.

## Audit regression and measurement semantics

`ADVERSARIAL-AUDIT-20261001.md` records the revision defects and evidence limits.
Keep real child-process tests for readiness/ACK loss/cancellation and bounded
owner contention, copied-content drift, anchored directory replacement, stale
session close, exact filename handling, egui paste/focus and diagnostic-limit
invalidation. The updater confirmation owner is `src/update_confirmation.rs`.

Storage probes run in 20 fresh processes per population; OS page cache is
uncontrolled. The page metric is exact serialized receipt bytes, not an
allocation profiler. Local manual measurements cannot promote the workflow
manifest. Explicit staged cleanup removes only digest-bound owned packages.


The million legacy fixture uses mixed chronological batches and 20 distinct
roots without derived index assets. Its support builder is
`src/retirement_qualification_fixture.rs`; it measures identity-only tombstones,
while archive-content integrity is exercised by the rebuild regressions.
`src/retirement_rebuild.rs` uses deterministic private spools. A crash remnant
blocks migration instead of allocating another spool set: preserve the old head
and affected files, stop all writers, and explicitly move remnants for recovery.
Do not delete unknown files automatically. Synchronization failure after head
publication leaves a commit-uncertain result and requires inspection.
