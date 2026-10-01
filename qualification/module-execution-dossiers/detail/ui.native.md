# ui.native: implementation and qualification dossier

Parent: `docs/modules/ui.native/TECHNICAL.md`. Lane: `LANE-B-RUNTIME`.
Canonical branch: `work/ui-native-qualified-integration-20260928`.
Audit revision: `work/ui-native-adversarial-audit-20261001`.
Immutable implementation source: `32310eefbef2a80164b669fe3bfcaef69b47b9da`.
Implementation tree: `90e28eb295688c11e93d4aec0ad983ba53e0e612`.
Status: implementation candidate; cross-platform execution, physical acceptance
and release remain separate evidence gates.

The authoritative source SHA/tree and verification state are recorded in
`apps/hepta-native/CURRENT_SOURCE.json` and
`docs/modules/ui.native/CURRENT_DELIVERY.json`. Detailed development instructions
are in `apps/hepta-native/DEVELOPMENT.md`. Read the audit findings in
`docs/modules/ui.native/ADVERSARIAL-AUDIT-20261001.md` alongside these documents.
The previous dossier is preserved in
`qualification/module-execution-dossiers/history/ui.native-before-20261001-audit.md`;
its journal-v3, 32768-retirement and single-task descriptions are historical.

## Product position and ownership

`apps/hepta-native/src/main.rs` composes authenticated runtime reads, bounded
platform operations, the operation journal and signed-update coordination.
The shell presents facts; it cannot mint grants, publish domain truth, select
releases, sign its own permissions or grant deployment authority.

The read-only loopback gateway authenticates native protocol v2 with the OS
keyring MAC contract. `kernel.authority` owns final-use grants, nonce claims,
expiry, epoch and revocation. `NativeShellRuntime` is the sole mutation and
journal owner. History and picker workers cannot become another authority.

## Durable operation contract

Identity includes endpoint, session incarnation, operation ID, subject,
displayed revision, action, payload, final-use binding and grant digest.
Exact retries read the recorded observation; changed identity semantics conflict.
The effect order is durable Prepared, current final-use claim, durable Invoking,
verified-use and local-policy fences, adapter entry, then durable observation.
UNKNOWN effects are never automatically replayed.

The current active journal is v7 with a checksummed, hash-chained v1 WAL.
Mutation synchronizes the WAL before publishing memory. Bounded checkpoints
replace and synchronize the snapshot before truncating the WAL. A previous
snapshot is forensic evidence, never an automatic replay source.

Retirement v3 binds immutable v2 segments and archived receipts to a rebuildable
disk index. Segments and archived records retain authority. Missing or corrupt
acceleration rejects or rebuilds; it cannot authorize a retired operation.
4096 active records, 8 MiB snapshots, 4 MiB WALs and bounded index buckets are
source ceilings. One-million-retirement performance is a qualification target,
not a demonstrated capacity claim. The scale fixture contains legacy identity-only
tombstones in mixed 1024-identity chronological batches. First-migration workers
start from zero derived assets; production migration uses bounded authenticated
spools and constructs each final bucket once. Crash remnants fail closed and
require explicit operator recovery. Hard budgets are in `STORAGE_BUDGETS.json`.

Windows validation checks the same file handle's owner/DACL, including child
ACL drift under a still-private root. Native mutable opens and the shared
utility's read/write `open_file` reject multiple hardlinks. Native Unix Read
does not chmod owner-only private files, and immutable migration aliases remain
readable with identity/content checks. The held-handle check cannot prevent a
trusted principal from adding a hardlink afterward.

## Platform and presentation contract

Linux file picking is XDG Desktop Portal-first; Zenity requires explicit policy.
Linux Open/Reveal binds a no-follow regular-file/directory descriptor and its
resource identity into final use, then hands that descriptor to XDG OpenURI.
Non-Linux Open/Reveal currently rejects because an equivalent resource-capability
adapter has not been implemented. This is a capability gap, not merely a missing
physical acceptance receipt.

Clipboard completion requires exact immediate readback. Notification/open helper
exit proves submission only, so uncertain effects remain Indeterminate.
The Windows unsigned package includes the AppUserModelID registrar and WinRT
toast adapter; visible installed notification requires physical-host evidence.
Notification identity input is strict UTF-8, bounded to 128 bytes and checked
against the exact AUMID. The packaged registrar's readonly property key is
copied before passing it by `ref`; a Windows test compiles the actual packaged
C# source, separately from registration and toast acceptance.

The GUI supervises mutation, bounded history-read and native-picker lanes.
Read and mutation admission are mutually exclusive. History pages are bounded
to 256 records; the GUI requests 64. Escape cancels pre-admission tasks on every
screen. File-input tickets preserve exact target and filename identity.
Shutdown joins all lanes and closes the runtime before update activation.

Resource-bound grant preparation runs in the supervised runtime lane, captures
the exact subject/operation/payload/authenticated view, and rechecks that view
under the runtime owner before confirmation. Completion is displayed only for
the unchanged input, screen, connection and full view identity. Cancellation
before admission never calls confirmation; admitted work is drained at shutdown.
The prepared binding remains input for the independent authority owner, with
no effect entry, grant creation or signing. The actual egui pending/stale text
snapshot is headless evidence, not GPU or physical-platform acceptance.

## Update contract

Independent signatures bind channel, target tuple, candidate, predecessor,
evidence, compatibility and lifetime. Critical copies hash the actual source
handle and verify copied bytes before atomic publication. Recovery cannot
overwrite an unrelated target.

Startup recording pins an existing private parent and rejects parent
substitution. Updater JSON reads/writes/removal, owner/runner locks and handoff
transitions use retained private-root capabilities. The helper activates through
its existing manager's pinned root. Staging retains a verified child capability
and admits only an empty directory or one exact current-digest package retry.
Unknown, abandoned or crash-remnant entries are preserved for explicit operator
recovery. The 512 MiB package bound permits an additional transient atomic copy;
it is not a 512 MiB peak-directory guarantee.

New-process readiness is process/session/view-bound. Readiness alone leaves
ActivatedUnconfirmed; the candidate commits Confirmed only after receiving the
helper acknowledgement. Failed or unobserved startup remains recoverable.
Rollback failure preserves RecoveryRequired.

## Required evidence

The read-only `ui-native-qualification.yml` evaluates exact head and a fixed
ordered-parent merge on Linux, macOS and Windows, plus exact-implementation Linux
storage qualification. Output directories are separate from the checked-out
source. The aggregate requires one run/attempt and revalidates source, workflow,
lockfiles, logs, package, SBOM, provenance and storage evidence.

Required cases include duplicate/revoked effects, real process death after
Invoking, WAL corruption/partial tail/checkpoint recovery, root and file
substitution, retirement rebuild, update-copy drift, helper acknowledgement loss,
rollback failure, stale picker tickets and shutdown of every lane.

The 212 application, 226 Python and 210 owner test counts belong to historical
`ed5fd2229502099addd6bedec2fae18783d5c162` evidence. Final source
`32310eefbef2a80164b669fe3bfcaef69b47b9da` passed 243 of 243 normal release
application tests in 1.469 s, including actual egui text snapshot matching,
and strict release application Clippy for all targets/features in 4.78 s.
The three ignored entries are two separate scale subjects and their worker;
native qualification Python passed 227/227 and the strict native-map adapter
suite passed 86/86. Both full release scale subjects passed: 4096-active in
2.461 s and one-million-retired with 4096-active combined load in 52.572 s.
Each open/rebuild population contains 20 fresh processes. Active, retired and
combined open p95 were 31.413, 0.414 and 462.509 ms; mixed first-migration
rebuild p95 was 1866.871 ms, within unchanged ceilings. All three release binaries
built and passed self-test and real subprocess qualification-e2e, with seven
fault/fence checks true and three authority-grant flags false. Package/portal
36/36 and projection generation/verification/lint with 7 tests passed; the
registry inventoried 84 files. These are local Linux diagnostics with uncontrolled
OS page cache and no durability syscall trace. Earlier ca66 results remain
historical. Actual Bazel 9 dependency metadata update/check passed against the
revised manifest with an unchanged module lockfile. Current owner and Windows
results remain pending. Queued CI is not a passing receipt.
Independent static review found no additional reproducible issue in the reviewed
scope, while the
candidate remains incomplete.

Source coverage, sustained soak, all storage ceilings, physical Windows/macOS/
X11/Wayland behavior, IME, mixed DPI, screen readers, keyboard navigation,
production key custody, signing/notarization, independent supply-chain acceptance
and promotion review remain explicit gates. Local tests cannot close these gates.
`productionQualified`, `deploymentQualified` and `releaseAuthorized` remain false.
