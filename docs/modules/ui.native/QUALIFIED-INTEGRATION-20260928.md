# ui.native qualified integration — 2026-09-28

## Change brief

Continue PR #1139 on `work/ui-native-qualified-integration-20260928`, from
`c84e0c760563ff0f8e67ab2208baf57bbe44ae44`. The fixed main snapshot is
`a126987b84737dbc2ee2592442a314117bddb4a2`. CANDIDATE.json owns branch/base
selection. Other ui.native candidates are superseded for integration, not
deleted; divergent changes are not claimed as absorbed. No unrelated branch,
signing key, production authority or independent approval is changed.

The scoped preparer materializes caller edits and tests, formats the exact
source with Rust 1.95.0, commits source, commits its inventory, then maps the
inventory-inclusive root. It never treats preparation as qualification.

## Changes and invariants

Runtime mutex waiting is cancellation-aware and bounded to 30 seconds. Lock
acquisition is not admission; begin() still linearizes cancellation with entry.
Admitted effects remain owned until joined; no timeout replays or detaches them.
A shutdown timeout blocks update activation rather than promising arbitrary OS
work can be killed. Update activation requires a real close request and confirmed
runtime close without a shutdown failure.

Legacy identity-only tombstones cannot acquire receipts, including in mixed
old/new retirement batches. Only receipts actually committed in the retirement
chain can be served after retirement; exact archived duplicates are immutable.

The source generator compares Git-normalized bytes and rejects wrong branch,
wrong pinned base and positive production/release claims. The complete app root
is observed only after CURRENT_SOURCE.json has been committed, avoiding a
self-invalidating source-map sequence. Document indexes remain generated.

## Required execution evidence

All six Linux/macOS/Windows head/merge subjects must have same-run/same-attempt
receipts for formatting, strict Clippy, native/owner tests, release binaries and
packaged checks. Xvfb/keyring observations are not physical-host acceptance.
Keep the PR draft until required qualification and projection checks pass.
A source/preparation/formatting run is not native product qualification.

## Remaining gates, not completion claims

Retirement membership is still memory-resident, and startup verifies the full
chain. An authenticated disk index and million-record native measurements remain
open. Path effects remain disabled until an OS adapter consumes a stable verified
handle; repeated canonicalization and test-only snapshots are not such a handoff.
Unknown observations remain unknown and cannot justify replay.

Signed installers, notarization, key custody/rotation/revocation, installed update
and rollback fault cuts, real screen-reader/Chinese-IME/focus/DPI/multi-monitor
acceptance, endurance measurements and independent approval require actual
external evidence. No editing-container test claims those events occurred.
productionQualified and releaseAuthorized remain false.
