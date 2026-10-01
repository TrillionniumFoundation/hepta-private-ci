# hepta-native developer guide

The current ordinary implementation source is `0a129b41c2a2d42ca907ea8257bf780108bc664f`, tree
`f90313f067446c629b8da50058ee1bd2101e76e7`.

Native update owner, handoff and runner locks now return an opaque
`updater::UpdateLock` instead of exposing a File. Successful acquisition builds
one lifetime guard; dropping it explicitly unlocks before closing the handle,
including a failed post-acquisition root check. Failed acquisition never
unlocks another owner. Retain the runner guard for the existing orchestration
scope. Final-use and authority-lease stores also unlock on their last owner
Drop, including failed trust construction; Arc/token ownership remains intact.
No retry, test serialization, deadline change or new authority was introduced.

Windows private atomic snapshot/copy publication now validates
the existing destination and same temporary descriptor before private bytes and
before commit. Private-source copies recheck their retained source descriptor;
external installer inputs/targets keep their own policy. The shared Windows
utility validates staging and existing destinations before replacement, then
closes its non-delete-sharing verifier handles before the actual rename.
Checks reject unsafe evidence without repairing its ACL or replacing its bytes.

The cancelled-ACK fixture accepts BrokenPipe only after durable cancellation;
successful ACK delivery, candidate exit, rollback and predecessor-byte assertions
remain enforced. Qualification merge construction and reconstruction now send
fixed UTF-8 LF bytes to Git, producing the same ordered-parent commit on every
OS. The strict source/tree/parent/workflow/run/attempt checks remain unchanged.
Darwin same-descriptor ACL/ownership, Unix NONBLOCK admission, typed Windows
registrar and the three macOS baseline fixture corrections are retained.

CURRENT_SOURCE.json binds 420 Git blobs, 32 selection paths and 16 local Cargo
dependencies, inventory SHA256 `8865ed312eaff178ad8909e2e1fadb3a53ec009fe8297f5e09692afb4c3b58e6`. Production, deployment
and release flags remain false. Fifteen Windows atomic/ACL regressions remain in the new-source target suite;
passing D544 executions are historical evidence only.

Precommit Linux diagnostics for the lock repair passed application 245/245
(2.460 s; three independent scale entries ignored) and strict all-target/all-feature
Clippy (8.67 s). The exact-copy reduced contracts workspace passed focused 2/2
and full all-feature 196/196 (1.028 s), scoped fix and strict Clippy. These are
local diagnostics, not immutable-candidate qualification; the standard owner
workspace's offline metadata attempt stopped on an unrelated uncached imbl
package. The public UpdateManager runner API also passed a controlled fork
red/green with the same harness. Current qualification-tooling Python passed 239/240 in 15.191 s (one Windows
NTFS-only skip). Three locked/offline release binaries built in 23.09 s; binary
self-test and seven actual child-fault checks passed locally, with all effect,
activation and release authority false. A new complete same-run current-source
platform/storage run and packaged-artifact evidence remain required.
This is the publication-time metadata capture, before the final workflow completes.
The current exact-run receipts are attached to [draft PR #1308](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/1308).
The separately committed navigation guard and owner-guide precision repairs are
`9ca0e42e211e87cf3fd0d1a15ba9d484d20093a9`, tree
`9fa335e95a577c642683252b00d7f6d23708f5d7`; these scripts and guides are outside
the frozen native product closure. CI still binds the complete candidate commit.

Historical D544 candidate632d/run36838749224 completed FAILURE. All three
actual merge subjects matched canonical LF SHA7d22e1fa3576681ae721fe3effb4a30f6806ec2a.
Linux head (243 application/212 owner), macOS head (254/230), both Windows
subjects (209/173, including all fifteen named atomic/ACL regressions) and all
48 storage traces/hard budgets passed. Linux merge failed on update-lock
contention; macOS merge failed the legacy fixture's precise InvalidTrust
assertion, without printing its actual variant. Aggregate correctly stopped at
the failed-subject gate; deep aggregation and acceptance did not run.

Controlled same-Rust flock/fork, public UpdateManager API and actual Store
alias experiments reproduce the close-only lock lifetime defect. Explicit
unlock passes while inherited descriptors remain open and preserves the
successor's lock. These experiments prove a fixable mechanism and API defect;
the precise original CI scheduling cause remains unproved
(actualCiCauseProven=false). The original eighteen metadata fields, exact
platform children and later terminal observation are retained in
[632d historical record](../../docs/modules/ui.native/history/20261001-d544-632d-verification.json); no pass is inherited by this new source.

Historical candidate dc59/run36836809639 completed FAILURE: immutable identity
and storage succeeded, both macOS subjects failed shell parsing before checks,
and Linux/Windows correctly rejected productExecutionComplete=0 but failed the
fixture's stale error-message expectation. Both Linux and Windows merge subjects
actually matched
658914a3e602337e707901a9f8d11388b6486799; no Mac merge or Rust/ACL pass was observed.
The producer now defines its Python heredoc in a standalone shell function,
outside quoted command substitution, preserving fixed binary LF and every
identity check. The regression executes head and merge with Python single/double
quotes and an apostrophe comment, using native /bin/bash on macOS. The malformed
bool fixture now requires its precise rejection diagnostic; input0 and denial
remain. Forty-eight targeted regressions passed locally. Actual new-platform
execution is required. See [dc59 historical failure](../../docs/modules/ui.native/history/20261001-dc59-verification.json); its original 18
localAudit fields and independently captured platform children remain unchanged.

Historical source89/candidate8c/run36832001532 actually passed all seven producer
subjects: both Linux/Windows/macOS head and merge suites plus 48 storage traces
and unchanged hard budgets. Each macOS subject executed all 32 ACL and both
Unix FIFO cases. Aggregate nevertheless failed: the Windows merge's CRLF commit
message produced b09d1a4b409537432dec6b8876e4e63843b5cd0c instead of canonical
LF merge6a3cd7ea61a6e718c1065d323ec7022b9b3d68bd, with identical tree and ordered
parents. Exact Git bytes prove the difference. This is an executable identity
defect, not a physical-host gate. Old tests also omitted the newly repaired
Windows atomic-publication calls. See [20261001-89c64-verification.json](../../docs/modules/ui.native/history/20261001-89c64-verification.json); its original
18 localAudit fields and all three platform children remain historical only.

Intermediate source403's local suite passed242/failed1: the cancelled child had
already exited when the parent incorrectly unwrapped BrokenPipe. Its failed
raw log is preserved in 20261001-403df-verification.json. SourceEE6 repaired that
fixture and passed243; 20261001-ee6a1-verification.json retains those diagnostics
separately. Neither source had a completed metadata review workflow and their
results cannot qualify this new source.

Eleven affected shared-owner maps refresh complete current source observations
after the shared Cargo/contracts/utility changes. Historical sourceBase, operation
states, tests, delegates, callers, receipts and execution/acceptance/activation/
release claims remain unchanged. Navigation does not establish product execution.
The migration guard explicitly recognizes module-specific executable, host and
release qualification fields, requires actual bool values, and rejects stale
execution proof before metadata writes. Source and structural completion facts
remain distinct. Two pre-existing NDU source drifts remain whole-project blockers;
this work preserves their historical claims rather than rebinding those receipts.

Historical B537 source `b5378e29d0fe191225abe853d848b498552f5850` in candidate58/run36830035079
passed both earlier corrected fixtures, library 145/145 and all 14 native ACL
cases on macOS. Its full application suite then failed retirement recovery
because a fixture newly created head.json with default 0644 mode; each subject
had 208 passes/one failure/three ignored. Shared-owner ACL/FIFO, release and
package stages were not reached. Exact old localAudit fields and separate
actual raw failures are retained in [20261001-b5378-verification.json](../../docs/modules/ui.native/history/20261001-b5378-verification.json); no
historical pass or pending field is relabeled as current qualification.

Historical A1 source `a1abe5b2a083213c095cdabaf4b3048144e3cad0` passed Linux application 243/243,
Python 237/238 with one Windows-only junction skip and isolated owner 194/194.
Its F5 run 36827460737 actually passed strict macOS lint and all 14 native ACL
fixtures, but both application suites failed two older fixture assumptions.
Shared-owner ACL/FIFO cases were not reached after application failure. The
failure and local diagnostics are retained in [20261001-a1abe-verification.json](../../docs/modules/ui.native/history/20261001-a1abe-verification.json);
the distinct F5 and 8f CI candidates remain separate, and pending subjects are
not passes. This actual failure supersedes the prior review stop.

Historical source `703e9bf2871b26d646f1c4d748e0b0061f70ad3c` has fresh clean-review-head Linux diagnostics:
application 243/243 (three separate scale entries ignored, 4.803 s), Python 238
total (237 passed/one Windows junction skip, 14.970 s), strict application
Clippy (7.51 s), three actual external E0603 boundaries, three release binaries,
self-test and real child-fault recovery. Run 36823756631 passed both macOS
subjects and Linux storage; both Windows subjects failed their registrar
fixture because PowerShell marshaled `System.RuntimeType` as an object.
Its exact receipts and terminal status are retained in
[20261001-703e9-verification.json](../../docs/modules/ui.native/history/20261001-703e9-verification.json). The subsequent independent Darwin ACL/FIFO
review and Windows failure require this new freeze.

Historical source `ebd04a7ed458aa5feaba69525f48f3623c4db033` repaired checkout
bytes, macOS cfg/FIFO, Windows fixture PATH and the packaged PROPVARIANT ABI.
Its Linux debug application 243/243 (5.581 s), Python 238 total (237 passed/one
Windows junction skip, 20.778 s), combined map 104/104 (22.123 s), package/portal
36/36 (0.167 s), projection seven tests, strict application Clippy (150 s) and
full-symbol ACK 1/1 (3.020 s) are historical diagnostics. They and the subsequent
CI failures are preserved in
[`20261001-ebd04-verification.json`](../../docs/modules/ui.native/history/20261001-ebd04-verification.json).
Run 36822033441 is terminal and failed overall: identity, Linux head/merge and
storage succeeded, while macOS full tests, Windows owner lint and aggregate
failed. Both Linux platform subjects completed 18 checks, including the virtual
GUI lifecycle; storage retained 48 traces with all hard budgets passing.
The Linux record is
[`20261001-ebd04-linux-verification.json`](../../docs/modules/ui.native/history/20261001-ebd04-linux-verification.json).
macOS application tests failed copying absent `/bin/true`; Windows owner lint
rejected five helper `unwrap` calls. These executable failures motivated the
three repairs above. No EBD pass qualifies the new source.

Historical Linux checks of source `0c176c9d4df6055418529389bf0f749f74ac1a69`
passed 243/243 normal debug-profile application
tests (6.377 s), with three scale entries ignored by that normal suite, and strict
debug application Clippy with all targets/features (9.39 s). The full-symbol
helper-acknowledgement fixture passed in 3.358 s. The native qualification Python
suite succeeded: 236 tests, 235 passed and one Windows-only NTFS junction test
skipped (20.939 s). The combined native-map adapter and global-map regression
suite passed 104/104 (22.945 s); package/portal tests passed 36/36 (0.138 s).
Projection generation, verification, lint and all seven projection tests passed.
Structural verification bound 404 Git blobs, 30 selection paths and 16 local
Cargo dependencies to that historical source. Its complete local diagnostics
and real CI follow-up are preserved in
[`20261001-0c176-verification.json`](../../docs/modules/ui.native/history/20261001-0c176-verification.json).
Run 36820183453 passed both Linux head/merge subjects and storage with 48
retained traces and all hard budgets,
but failed macOS strict compilation and one Windows Python shell fixture.

Historical source `32310eefbef2a80164b669fe3bfcaef69b47b9da` and its tree,
local release results and later partial CI observations are preserved in
[`20261001-32310-verification.json`](../../docs/modules/ui.native/history/20261001-32310-verification.json).
Run 36796737020 failed overall: Linux storage and the Linux merge subject
succeeded, while Linux head ACK and macOS/Windows Python checks failed.
Its successful subjects cannot qualify the source above. Earlier ed5/ca66
counts and old queue observations likewise remain historical.

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

Source-path validation canonicalizes only the declared repository root alias,
including macOS `/var` ancestry and Windows short-path spelling. Dependency
components remain intact: internal symlinks and Windows reparse points,
including junctions to another directory in the same repository, are rejected.
Parent traversal cannot escape and re-enter through an outside alias. The
Windows junction regression creates real `mklink /J` fixtures; its Linux skip
does not establish Windows execution. Source metadata is written with explicit
LF and compared with committed Git bytes; JSON-equivalent CRLF drift still fails.
Windows shell fixtures select Git for Windows Bash explicitly and reject an
unrelated PATH Bash, including WSL, rather than guessing the shell that failed.
The Bash process gives its owned fixture commands first PATH priority and checks
`command -v`, preventing Git's bundled `strace.exe` from replacing the mock.
Root and application checkout attributes are frozen and workflow-triggered;
`codex-rs/Cargo.lock` has explicit LF checkout. A real `core.autocrlf=true`
checkout-to-supply-chain-to-Git-inventory regression preserves exact lock digests.

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

`[profile.test.package.sha2] opt-level = 3` optimizes executable hashing only in
the test profile. Restart fixtures still hash the complete actual executable,
including full debug symbols. Do not strip the subject, bypass the digest or
extend production deadlines to pass this fixture. The readiness and post-helper
exit observations have separate 20-second fixture deadlines and retain child
status, elapsed time and pending update diagnostics. Production 5/35-second
deadlines, complete executable-digest verification and update-owner fences
remain unchanged. The earlier full-symbol attempt failed readiness in 31.353 s;
that failed attempt remains diagnostic history.

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

Preparing a binding can open and verify an OS resource, so `PrepareBinding` runs
on the supervised runtime-owner lane. Capture the exact subject, operation ID,
action, payload and authenticated view. The worker rechecks that view under the
runtime owner; completion is displayed only while the input, connection,
Operations screen and exact view still match. Editing bound input invalidates
the result. Cancel before admission and join admitted work on shutdown. This
prepares independent authority input; the shell neither grants nor signs it.

Preserve `ui/binding_prepare_tests.rs` cases for blocked OS confirmation, edited
input, changed view, queued cancellation and admitted shutdown. The real headless
egui text snapshot in `ui/binding_prepare_snapshot_tests.rs` records pending and
stale-result projection. Its pinned `insta` dependency and snapshot are test
assets; this is not GPU, physical desktop or accessibility acceptance.

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

Keep the private-root capability through the complete persistence operation.
`StartupRecorder` pins an existing private parent at construction and publishes
through it. Update pending/result JSON, owner and runner locks, readiness,
ACK/cancellation and cleanup use the retained update root. Packages use its
verified `staged` child. Pass that child into digest/copy/removal helpers;
root replacement or trust drift is an error.

The updater helper activates through its existing `UpdateManager`, retaining
the manager's pinned root through admission and replacement. The standalone
path activation API is an independent entry boundary, not a reason to reopen
the root inside an already owned helper lifecycle.

Stage admission allows an empty directory or one exact `<digest>.package` whose
content matches the current manifest; a same-digest retry may reuse it. Another
digest, an unknown crash temporary, redirected entry or changed content rejects
staging and remains for explicit recovery. Do not delete unknown files
automatically. Each package is bounded to 512 MiB; an atomic replacement may
temporarily hold an additional copy of up to 512 MiB. This is not a 512 MiB peak
disk-space guarantee. Predecessor backup limits remain separate.

Legacy staging permissions may be tightened only on a verified current-principal
handle, with a single-link check before file mode changes. Mutable private opens
(`Write`, `Append`, `Lock`, `CreateNew`) require one hardlink. Unix `Read` is
non-mutating, accepts owner-readable files with no group/world permissions
(modes 0400, 0500, 0600 or 0700) and preserves immutable
migration aliases; identity/content validation remains mandatory. Windows checks
the actual opened child's owner and ACL. The shared utility's read/write
`open_file` also applies mutable-file checks, protecting its contracts callers.
An admission check cannot prevent a trusted principal from adding a later
hardlink. Preserve target-OS root replacement, ACL drift and alias regressions.

Private state requires a trusted filesystem and mount configuration that enforce
advertised owner and permission semantics. An absolute path does not establish
filesystem locality. Linux verifies UID, mode, type, links and identity; remote
named ACLs and mount policies need their own deployment qualification. For
example, [NFSv4 section 6.3.2](https://www.rfc-editor.org/rfc/rfc7530.html#section-6.3.2)
derives mode from selected principals, while the Linux
[CIFS documentation](https://www.kernel.org/doc/html/latest/admin-guide/cifs/usage.html)
describes mount options that disable client permission checking. Current local
POSIX execution does not establish privacy for those configurations.

On macOS, `codex_utils_private_state::verify_private_permissions` checks the
same opened descriptor through the Darwin ACL API and typed `fstatfs`. Private
roots, children, journal files, update locks/staging and final-use/lease state
reject every extended ACL entry, including deny-only entries, query failures,
unsupported queries and mounts with `MNT_IGNORE_OWNERSHIP`. UID, mode, identity,
regular-file and applicable hardlink checks remain separate requirements.

The wrapper accepts an absent ACL only for Darwin's documented `ENOENT` path;
a returned ACL is validated before iteration. Darwin entry success is zero,
and only `-1/EINVAL` on a valid empty ACL admits an empty list. ACL allocations
are freed without changing filesystem permissions. Callers retain
`forbid(unsafe_code)`; the small OS utility owns the FFI boundary.

Checks precede permission migration, private bytes/truncation and atomic
publication. Held roots, the staging descriptor and any existing destination
are checked again before replacement; a destination carrying an ACE is
preserved instead of silently replaced with a private temporary. Native
boundary tests inject actual ACEs after open and file sync. External installer
targets/downloads/backups do not acquire this private-state policy. All Unix
shared authority-store opens additionally use `NONBLOCK` before type validation
so an owner-only FIFO is rejected without waiting for a writer.

Create private fixture baselines with the existing
`tests/common/snapshot.rs::write_private_json` helper or create_new/mode0600;
create private directories with mode0700. Assert those baseline modes before
injecting a fault and assert the requested cut actually executes. Recovery
fixtures need valid private predecessors; intentionally unsafe predecessors
should test rejection. Public downloads, installed binaries and configuration
inputs retain their own input policy. Fixture-only ACL removal is confined to
fresh owned controls.

Real macOS ACL fixtures require unchanged 0700/0600 modes and compare original
bytes and ACLs. Fixture-only ACL removal establishes a control solely on newly
created owned temporary directories; production never removes an ACL. Source
presence and Linux execution do not qualify Darwin behavior. An ownership-ignored
volume still requires a real target-host mount receipt; no static bit assertion
or current ACL fixture is presented as that receipt. A trusted owner may change
permissions after validation; these checks do not provide filesystem transactions
or independent authorization.

On Windows, `current_user_sid()` identifies the process primary token's
`TokenUser`; it does not resolve a thread impersonation token or the effective
default owner. The OS uses the creating primary/impersonation token's default
`TokenOwner` for new objects, and a legal group SID may be that owner; see
[Owner of a New Object](https://learn.microsoft.com/en-us/windows/win32/secauthz/owner-of-a-new-object)
and [TOKEN_OWNER](https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-token_owner).
If that SID differs, creation may succeed and subsequent strict verification
reject it. The current support and qualification precondition is default-owner
SID equal to primary `TokenUser`, with no thread impersonation. Treat other
contexts as an unqualified, conditional fail-closed availability boundary,
without inferring an exploit or universal administrator failure. Physical
ordinary/elevated, owner-mismatch and impersonation tests remain pending.
Keep exact owner checks; do not admit owner groups or rewrite existing owners
to make qualification pass.

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

Notification support reads that marker as a bounded regular file: 128 bytes,
valid UTF-8 and the registered AUMID after trimming. Read failure denies support.
`tests/windows_registrar.rs` compiles the C# embedded in the actual packaged
PowerShell registrar using system PowerShell; the readonly property key is copied
to a local value before a `ref` call. Its PROPVARIANT union includes a sequential
count/pointer array, giving the SDK size of 24 bytes on x64 and 16 on x86; the
former pointer-only union incorrectly occupied 16/12 bytes. The Windows-only
test checks actual `Marshal.SizeOf` and field offsets, then creates an owned
temporary `.lnk` and exercises packaged `SetValue` plus COM `GetValue` AUMID
roundtrip with `PropVariantClear` cleanup. See the
[Windows SDK PROPVARIANT layout](https://learn.microsoft.com/en-us/windows/win32/api/propidlbase/ns-propidlbase-propvariant).
Linux test totals do not establish Windows execution; this fixture also does not
prove installed Start Menu identity or visible toast delivery.

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
