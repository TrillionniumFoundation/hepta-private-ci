# ui.native qualified integration — 2026-09-28

## Change brief

Continue PR #1139 on `work/ui-native-qualified-integration-20260928`. The fixed
synthetic-merge base remains
`a126987b84737dbc2ee2592442a314117bddb4a2`. `INTEGRATION_CANDIDATE.json`, the
current-source manifests and same-run qualification receipts own the exact
candidate identity; this document does not substitute a historical SHA for that
machine-readable binding. Other ui.native candidates are superseded for
integration, not deleted, and divergent changes are not claimed as absorbed. No
unrelated branch, signing key, production authority or independent approval is
changed.

The scoped preparer materializes caller edits and tests, formats the exact source
with Rust 1.95.0, commits source, commits its inventory, then maps the
inventory-inclusive root. It never treats preparation as qualification.

## Changes and invariants

Every background path that needs the runtime owner now waits through the same
cancellation-aware, bounded pre-admission lock path. This covers refresh,
reconciliation, history compaction, observation closure, final-use execution and
runtime shutdown. Waiting is limited to 30 seconds. Lock acquisition is not
admission: `TaskAdmission::begin()` remains the only linearization point between
cancellation and entry into the runtime owner. Tests cover cancellation during
lock contention, the lock-wait deadline and successful lock acquisition without
implicit admission.

Admitted effects remain owned until joined; no timeout replays or detaches them.
A shutdown timeout blocks update activation rather than promising arbitrary OS
work can be killed. Update activation requires a real close request and confirmed
runtime close without a shutdown failure.

Runtime status JSON is rendered when a new authenticated refresh result is
installed, then reused by subsequent GUI frames. Starting or failing a refresh
invalidates the cached presentation. This removes repeated pretty-serialization
from the paint path without caching across runtime revisions or changing the
authenticated status value.

File-input intent remains explicit and single-use. Cancellation, replacement,
wrong-target delivery, multiple files, missing filesystem paths and relative
paths do not silently retarget a later operation. Selected files are reopened
through the bounded regular-file reader before admission; drag/drop is not a
verified-handle handoff.

Legacy identity-only tombstones cannot acquire receipts, including in mixed
old/new retirement batches. Only receipts actually committed in the retirement
chain can be served after retirement; exact archived duplicates are immutable.
Unknown observations remain unknown and cannot justify replay.

The source generator compares Git-normalized bytes and rejects wrong branch,
wrong pinned base and positive production/release claims. The complete app root
is observed only after `CURRENT_SOURCE.json` has been committed, avoiding a
self-invalidating source-map sequence. Document indexes remain generated.

## Required execution evidence

All six Linux/macOS/Windows exact-head/fixed-base-merge subjects must have
same-run, same-attempt receipts for locked dependency resolution, formatting,
strict Clippy, native and owner tests, release binaries, fault qualification and
packaged checks. Missing, queued, skipped, cancelled or failed subjects are not
success. Keep the PR draft until the exact candidate and all required projection
checks pass. A source/preparation/formatting run is not native product
qualification.

The Linux installed-product lane additionally exercises an isolated real gateway,
system keyring service, packaged visible GUI, keyboard traversal and normal
window-manager close, and records launch-to-readiness, launch-to-visible-window,
normal-close and resident-memory observations. Those hosted-runner observations
remain non-promoting: Xvfb, virtual input and a CI keyring session are not
physical-host accessibility, IME, DPI, multi-monitor, endurance or production
key-custody acceptance.

## Remaining gates, not completion claims

Retirement membership is still memory-resident, and startup verifies the full
chain. An authenticated disk index and million-record native measurements remain
open. Path effects remain disabled until an OS adapter consumes a stable verified
handle; repeated canonicalization, picker strings and test-only snapshots are not
such a handoff.

Signed installers, notarization, production signing and key
custody/rotation/revocation, installed update and rollback fault cuts on release
artifacts, real screen-reader/Chinese-IME/focus/DPI/multi-monitor acceptance,
endurance measurements and independent approval require actual external evidence.
No editing-container or hosted-runner test claims those events occurred.
`productionQualified`, `deploymentQualified`, `independentAcceptanceComplete`
and `releaseAuthorized` remain false.
