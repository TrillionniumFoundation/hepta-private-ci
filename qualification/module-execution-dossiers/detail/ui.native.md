# ui.native: implementation and qualification dossier

Parent: `docs/modules/ui.native/TECHNICAL.md`. Lane: `LANE-B-RUNTIME`.
Canonical branch: `work/ui-native-qualified-integration-20260928`.
Audit revision: `work/ui-native-adversarial-audit-20261001`.
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
releases or grant deployment authority.

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

The GUI supervises mutation, bounded history-read and native-picker lanes.
Read and mutation admission are mutually exclusive. History pages are bounded
to 256 records; the GUI requests 64. Escape cancels pre-admission tasks on every
screen. File-input tickets preserve exact target and filename identity.
Shutdown joins all lanes and closes the runtime before update activation.

## Update contract

Independent signatures bind channel, target tuple, candidate, predecessor,
evidence, compatibility and lifetime. Critical copies hash the actual source
handle and verify copied bytes before atomic publication. Recovery cannot
overwrite an unrelated target.

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

Source coverage, sustained soak, all storage ceilings, physical Windows/macOS/
X11/Wayland behavior, IME, mixed DPI, screen readers, keyboard navigation,
production key custody, signing/notarization, independent supply-chain acceptance
and promotion review remain explicit gates. Local tests cannot close these gates.
`productionQualified`, `deploymentQualified` and `releaseAuthorized` remain false.
