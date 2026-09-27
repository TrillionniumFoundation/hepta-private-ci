# ui.native verified-closure candidate

Date: 2026-09-27. Canonical candidate: `work/ui-native-verified-closure-20260927`.
Source parent: `bcc7233ac50c1d37001843392d32f7150a658bc2` (#1100).
The exact executed source/metadata commit and tree come from the workflow receipt;
this document never treats its author's workspace as a successful native build.
The qualification base for this candidate is pinned in the workflow rather than
being silently advanced when `main` changes.

## Current protocols and persistence order

The request binding remains `hepta.ui.native.platform-request.v2`. It binds the
subject, endpoint ID and signed-manifest digest, session identity/generation,
operation ID, action, displayed revision, authenticated view generation/digest,
resource identity and payload digest. Refresh invalidates the actionable view
before fallible I/O and retains generation/revision high-water marks. The kernel
still verifies revocation at actual effect entry; this candidate adds no issuer.

Journal v6 retains v5 `observation_closed`: the result is UNKNOWN, no terminal
status or outcome is invented, and this operation can never be replayed. V2–V5
journals remain readable. The first journal mutation writes v6; first compaction
migrates the legacy retirement array to the segmented store. Rollback to an
application that cannot read v6 is NOT an admitted rollback strategy.

Each journal has a sibling `<journal>.retirement/` private directory, protected
by the existing journal owner lock, not a second daemon or authority. Segments
contain at most 1,024 sorted unique operation-identity digests. Their names are
SHA-256 hashes of their bytes and each commits to the previous head and count.
The small `head.json` is atomically published only after complete segments have
been flushed. The journal then records that checkpoint and removes closed
records. There is no fixed 32,768 lifetime-identity limit; disk and memory remain
finite and capacity errors must still fail closed. Reopen builds a hash-set index
in memory, so initial recovery time and memory grow with retired history. This
is not an unbounded-resource or constant-memory claim.

The durable order is:

1. Write/sync immutable retirement segments.
2. Atomically publish/sync the retirement head.
3. Atomically publish the journal with the checkpoint and compacted records.

A crash before (2) leaves harmless unreachable segments, not removed active
records. A head ahead of the journal after (2) conservatively retires only
already-terminal/observation-closed records on reopen. A live record overlapping
that head fails closed as rollback/conflict; it is never silently reissued.
A missing referenced store, malformed chain, digest mismatch, duplicate identity,
or head older than the journal checkpoint is rejected. Every publication error
latches the existing journal health fence until reopen/reconciliation. A missing
primary alongside retirement evidence is never interpreted as an empty history.

This cross-file checkpoint detects partial rollback, not an attacker restoring
all journal/retirement/authority files together. Independent rollback resistance
still belongs to the existing authority owner. Orphan segment garbage collection
is deliberately not automatic: deleting retained replay protection is not a
capacity remedy.

## Resource confirmation

Resource snapshots now verify that the original path still resolves to the same
canonical name and that reopening that canonical name returns the same object
identity. Tests substitute a same-byte file after open and redirect a parent
symlink to a hard-linked alias. These checks close the snapshot construction
window, NOT the final path-only `open`/`explorer`/`xdg-open` handoff race. An actual
descriptor-consuming platform integration is still needed for that claim; no
capability or release flag is set to conceal this limitation.

## Validation and evidence

Added native tests exercise segmented history past 32,768 identities, legacy
migration at the old limit, missing/corrupt segments, head regression, orphan
segments, retirement-ahead/journal-behind recovery, live-backup rejection and
resource substitution during snapshot construction. Existing suites cover refresh
invalidation, complete grant binding, revocation, terminal write loss, no replay
of closed unknown outcomes, kernel admission and update fault recovery.

The scoped materialization workflow records the exact formatted commit and
metadata commit, runs native tests/strict Clippy and retains logs. The normal
qualification workflow must separately execute head and pinned-main merge for
Linux, macOS and Windows, including unsigned packaged binary checks and actual
Linux GUI/keyring/gateway observations. Pending, skipped or failed jobs are not
passes. Python infrastructure tests are not Rust build evidence.

## Remaining acceptance boundaries

Actual checks and their exit status must be read from the workflow artifacts;
there are no pre-filled pass percentages here. Physical screen-reader/IME/DPI,
macOS/Windows ordinary installed lifecycle, signed/notarized distribution,
independent key custody/rotation/revocation and release authorization remain
separate observations. Source ownership, code signing and a test fixture cannot
stand in for those observations. Existing installed Linux measurements bind to
the packaged binary; they do not measure input-to-paint latency or prove a soak
budget. Segmented history requires measurement with representative large states.
