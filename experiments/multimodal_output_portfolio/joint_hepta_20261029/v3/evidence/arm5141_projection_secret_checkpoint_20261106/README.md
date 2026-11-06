# ARM diagnostic view and secret writer checkpoint

This packet preserves the complete two diagnostic ZIP archives from the failed
native ARM run at `f26473cbd6d7d707c5c8e6ddd317a5d472b08c45`, together with the
original job log, official API responses, owner and independent root audits,
and the later two-file capability writer repair.

The actual build stage completed both nextest list commands with the external
store configuration. Its original receipt says `built_not_executed`, with the
source and dependency seed unchanged. The new diagnostic view exported all
1,416 selected files (68,193,916 bytes) and an 84,200-entry source catalogue.
Both original ZIPs, all four ZIP members, and every selected payload were checked
for their declared byte identity and CRC. Original collector limits remain
5,000 files, 1,024 path bytes, and eight parts of 128 MiB.

The business case really ran and failed: one test executed, zero passed, one
failed, zero ignored and eight other cases filtered. Its first error was
`secret capability omitted its final newline`; `just` exited 100 after 94.195
seconds. Build/store success and diagnostic export success do not make that
business result pass.

CI35 appends one LF only at the nonce and password capability writers. The
original Rust reader still checks regular-file identity, exact 0600 mode,
one link, one line, length and read-once removal. The original completion nonce
comparison and password registration values are preserved. Two previously
unused imports were removed after the unchanged baseline and initial candidate
both produced the same Ruff errors. That initial candidate and those errors
remain in this packet. Twenty actual local checks ran the original Rust reader
against the old and new writer expressions; these are component checks on Linux,
not a successful ARM business run. Root published this repair as PR 5160.

## Retention boundary

The original complete 1.63 GB ARM artifact is identified by its official API
digest, but it was not downloaded, independently hashed or reconstructed.
The selected diagnostic view coexists with that artifact. Excluded entries have
native catalogue metadata only. All selected payloads and the three metadata
members can be recovered from the two original ZIPs retained here. They are not
duplicated as separately expanded outer packet inputs.

The workflow merge and the prepared native worktree have distinct commits and
the same exact source tree. Their identities are recorded separately. Earlier
PR 5132 evidence is preserved with its narrower outer-failure visibility; this
packet does not invent the unavailable inner error from that older run.

## Restore

Run `python restore.py /absolute/new/destination`. The fixed reader verifies all
parts, the INDEX, the complete archive and every listed file before writing
inert regular files with mode 0644. Original modes are recorded in the INDEX.
It never executes archived code. Audit and probe implementations are retained
for review; any deliberate replay should use a separate copy so the preserved
original receipts remain unchanged. Tool installers, the local probe executable
and temporary synthetic input files are excluded explicitly.

The original business failure remains a failure. A complete ARM qualification
on the repaired source is still required.
