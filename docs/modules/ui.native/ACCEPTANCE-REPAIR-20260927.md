# ui.native acceptance repair — 2026-09-27

## Current candidate and provenance

The single candidate advanced here is `work/ui-native-acceptance-repair-20260927`. It directly continues
`work/ui-native-full-closure-20260927` (#1107), source HEAD
`43da94c5fa48675a3e0956a80fac201fa3ce8b34`, tree
`fc16515c91608c37bd6e85af8aaa1e7eadc7eecd`. No unrelated module branch is updated.
The pinned integration main is `a126987b84737dbc2ee2592442a314117bddb4a2`.
`apps/hepta-native/CURRENT_SOURCE.json` is the one generated source inventory.
`docs/modules/ui.native/CURRENT_SOURCE.json` is navigation, not a competing status database.
Implementation-map anchors name an already committed source tree, not the future
metadata commit. Qualification receipts always name the actual tested SHA/tree.

## Implemented changes

Full closed operation records now survive compaction. A record is serialized and
written to a content-addressed immutable file before its hash and operation identity
are published in a v2 retirement segment, before the chain head, before active journal
replacement. The head hash transitively binds each archived record. Ordinary checksums
are corruption detection, not a signature, a trusted anti-rollback frontier, or protection
against an attacker able to replace all private state.

A repeated identical request returns its original archived terminal/unknown-closed
receipt without authority claim, permission interaction, or platform dispatch. The
subject, endpoint/session, action, payload, view revision and exact signed-grant digest
must still match. A different payload or grant conflicts. Reading a historical receipt
is not permission for a new effect and does not require a fresh displayed view.

Legacy v1 retirement segments and v2–v6 journals remain readable. Previously retired
identity-only entries cannot be reconstructed: they remain replay-fenced and do not
produce invented receipts. New v2 segments can reference old segments without rewriting
history. Missing/corrupt referenced records make historical lookup fail, never create a
fresh operation. An ahead retirement head reconciles only identical closed records;
active-record/archive disagreement fails closed. Orphan record files have no authority.

The UI offers explicit closed-history compaction for terminal-only workloads as well
as unknown-observation closure. Unknown means unknown after archiving. There is no
ordinary replay/retry action. A journal-clear operation is not recovery. OpenPath and
RevealPath remain explicitly unavailable in the system adapter until an OS API consumes
the verified resource capability; tests now match this inherited security restriction.
The unused path snapshot research module is test-only, not claimed as production handoff.

## Durability order and failure handling

1. Write and sync each immutable record; validate existing bytes on an idempotent write.
2. Write bounded content-addressed segment(s) including identity-to-record-digest links.
3. Atomically publish and sync the retirement head.
4. Atomically replace the active journal using the new checkpoint.

Any write error fences the current journal owner. A restart may recover the old or new
complete head. Published retirements forbid dispatch even when the active journal has
not yet been replaced. Orphan files never authorize replay or manufacture evidence.
The live journal remains bounded; retired index memory and restart scan still grow with
history. A disk index and measured compaction policy remain performance work, not an
unbounded-memory production claim.

## Regression scope

Tests cover preserved unknown receipts across restart; semantic drift after terminal
retirement; no dispatch or reconciliation when returning an archived receipt; missing
and modified archive records; failed record publication and owner fencing; repeated
restart/compaction; old identity-only migration; source candidate mismatch; and path
operations remaining unavailable before/after replacement. Existing view, revocation,
receipt-write-failure and ahead-head tests are retained.

## Validation ledger

Local Python test results are reported in the execution handoff, with retained raw logs.
No local Rust compiler is available in the editing environment. Rust test declarations,
manual static review, and Python validation do not count as native test passes.
The formatter workflow produces an immutable proposal; it must not push to a moving
candidate. The previous live-branch rebind workflow is removed from this continuation.
The six existing qualification subjects remain mandatory: Linux/macOS/Windows, each
at exact head and the fixed main merge. The workflow still fails on missing, skipped,
cancelled, or unsuccessful subjects; formatting, lint and native tests are not relaxed.

Phase A remains pending until those actual candidate receipts pass. Phase B has concrete
implementation and regression additions, but path capability handoff is not implemented
and native execution has not been claimed. Phase C remains unqualified: real installed
macOS/Windows/Linux behavior, signed packages, notarization, update/rollback/key rotation,
IME/DPI/screen-reader acceptance, long-run installed performance, and independent release
approval require real external observations. No signing keys or production policies are
changed. The existing performance plan must be run on identified installed artifacts;
no measurements, signatures, or physical-host results are synthesized by this change.
