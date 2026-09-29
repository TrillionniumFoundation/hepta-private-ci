# hepta-native developer guide

This guide applies to immutable implementation source
`0ef8638eaf7c4ae733ac2d10eba67d9308ef7e17`, tree
`7f52a91a42a612dfd7472fa5514ab81626dc13f9`. The module is an implementation
candidate; production, deployment and release flags remain false.

## Toolchain and identity

Use Rust `1.95.0` and `apps/hepta-native/Cargo.lock`. Product source must be an
ordinary commit. CI must not patch, format, commit or push it. The sole module
workflow is `.github/workflows/ui-native-qualification.yml` with read-only
permissions.

Run the structural checks from the repository root:

```bash
python3 scripts/check_hepta_ui_native_convergence.py
python3 -m unittest \
  scripts.test_hepta_ui_native_convergence \
  scripts.test_hepta_ui_native_package_security -v
```

The checker rejects retired writer/materializer workflows, patch capsules,
write permissions, mutation commands, stale state anchors, product-source drift
after the frozen commit and promoted release flags. It also checks journal/WAL,
retirement-index, storage-budget and fixed-launcher contracts. It does not
replace compilation, crash tests, physical acceptance or release review.

## Build, formatting and lint

```bash
cargo +1.95.0 fmt \
  --manifest-path apps/hepta-native/Cargo.toml --check
cargo +1.95.0 check \
  --manifest-path apps/hepta-native/Cargo.toml \
  --locked --all-targets --all-features
cargo +1.95.0 clippy \
  --manifest-path apps/hepta-native/Cargo.toml \
  --locked --all-targets --all-features -- -D warnings
```

A formatting change is source: commit and review it before qualification. Never
format inside a qualification job and then test a derived future tree.

## Tests

```bash
cargo +1.95.0 test \
  --manifest-path apps/hepta-native/Cargo.toml \
  --locked --all-targets
```

Preserve tests for final-use linearization, exact duplicates, journal transition
legality, WAL framing/checksum/sequence/partial tail, checkpoint recovery,
retirement chain/index integrity, legacy migration, private-root rejection,
update handoff/rollback, task admission, stale picker tickets and shutdown.
Targeted tests are useful while developing but are not a qualification pass.

Process-kill qualification must terminate a real process at each durable cut
point. In-process injected errors do not establish crash recovery.

## Running the application

```bash
cargo +1.95.0 run \
  --manifest-path apps/hepta-native/Cargo.toml \
  --locked --bin hepta-native -- <launch arguments>
```

`--check-connection` exercises bootstrap only. It does not prove GUI readiness,
platform effects, accessibility or installation. Credential and updater helpers
do not issue final-use authority or select a release.

## Final-use operation protocol

The shell never signs its own grant. Prepare the exact binding from the current
authenticated view; an independent owner chooses grant identity, nonce, epoch
and lifetime and signs the complete grant. Runtime order is:

```text
validate request
→ resolve adapter confirmation resource
→ durable Prepared WAL entry
→ local permission
→ final-use claim and current revalidation
→ durable Invoking WAL entry
→ final local policy and verified-use fence
→ platform boundary
→ durable terminal or Indeterminate observation
```

Do not reorder barriers, cache authorization across mutable work, or interpret
timeout/launcher exit/cancellation as known non-execution. UNKNOWN is never
automatically replayed. `OpenPath` and `RevealPath` remain unavailable until an
adapter consumes an already verified OS resource capability without reopening a
mutable path.

## Storage protocol

Current schemas:

```text
journal                  hepta.native-operation-journal.v7
WAL                      hepta.native-operation-wal.v1
retirement head          hepta.native-retirement.v3
retirement segment       hepta.native-retirement.v2
retirement index         hepta.native-retirement-index.v1
retirement index bucket  hepta.native-retirement-index-bucket.v1
```

A mutation appends and synchronizes a complete WAL frame before changing memory.
A checkpoint synchronizes the replacement snapshot before truncating the WAL.
The `.previous` snapshot is forensic evidence only; automatic restoration can
resurrect an effect identity. After persistence error the owner is fenced:
reopen and reconcile, never retry through the same object or delete history.

Retirement segments and archived records are authority. Manifest, buckets and
cache are rebuildable acceleration. Index uncertainty rejects or rebuilds; it
never makes a retired identity executable.

## Storage budgets and profiles

`STORAGE_BUDGETS.json` contains blocking provisional ceilings. Required measured
subjects use the same immutable source and record:

- 4096 active records;
- 1,000,000 retired identities;
- cold-start and mutation p50/p95/p99;
- fsync count per transition;
- WAL/snapshot growth and write amplification;
- peak RSS;
- deterministic index rebuild time.

Retain raw samples, host/filesystem, runner image, source, ordered parents,
command and artifact digest. Missing or cancelled data fails the budget.

## Picker and platform helpers

Picker results are untrusted paths bound to one exact target ticket. Reject stale
callbacks, multiple/relative paths, control delimiters and oversized output.
Reopen accepted paths through the bounded regular-file reader. A chooser result
is not a grant or resource capability.

Linux currently uses `/usr/bin/zenity`; portal-first integration remains
required. macOS/Linux notifications use fixed `/usr/bin` executables and a
cleared environment. Windows notification remains disabled until packaged
AppUserModelID and WinRT integration exist. Helper exit is not delivery proof.

## UI task ownership

Keep one serial mutation owner. `TaskAdmission::begin()` is the cancellation
linearization point; admitted work is joined. The approved evolution is a
picker-process lane returning ticketed input, immutable read snapshots,
generation-bound persistent history pages and one durable mutation lane. Do not
add a detached task or second journal writer.

## Qualification

Pushes check exact head on Linux, macOS and Windows. Pull requests also check a
fixed merge with exact target base as parent 1 and candidate head as parent 2.
The aggregate `ui.native / qualification result` succeeds only when every
applicable subject succeeds.

The final manifest additionally binds compiler-negative API tests, process kill,
cold restart, corruption, updater rollback, installed-package E2E, measured
coverage, sustained performance, physical accessibility, signing, SBOM and
provenance. Only an independent reviewer promotes release flags.

## Branch protection and troubleshooting

Required GitHub settings are in
`docs/modules/ui.native/BRANCH_PROTECTION.md`. A file does not enable an admin
ruleset. Review the normal commit chain in `REVIEW_DIFF.md`.

- journal already owned: do not delete the lock or state;
- persistence indeterminate: stop effects, reopen and reconcile;
- index failure: reject or rebuild from verified segments;
- picker unavailable: report it, never use ambient shell fallback;
- UNKNOWN effect: reconcile only through an operation-bound observer or close
  observation without replay;
- update readiness failure: deny activation and preserve recovery evidence;
- cancelled/skipped CI: rerun unchanged source or create a new candidate, never
  hand-edit the manifest to pass.
