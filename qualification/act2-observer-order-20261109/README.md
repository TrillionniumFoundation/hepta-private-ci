# ACT-2 attached Notes observer order

**Native qualification: PENDING. Full ACT-2 promotion: HOLD.**

Candidate PR: https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5591

Candidate source: `111d5773145dbe4add99a28b2d1111916a3dbd3b`; tree:
`cd6ea40d7bad36bc1149cdca4137e85f9798f5fc`. Parent:
`4674a34528d0097949cc7d604f60de94585d0ba0`.

Run: https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42744390844

## Behavior

A nonce binds a response to a fresh request. The attached observer now also
remembers one accepted document revision and content digest, shared across its
clones. A lower revision or changed text at the same revision is refused without
lowering the remembered state. Receipt retirement remains valid. The shared lock
spans the existing read-only exchange; another clone fails immediately while
that exchange is in flight, without adding requests or effects.

The existing product status path maps a refused document read to missing current
readback and UNKNOWN while preserving the original historical receipt. The
observer lives in the Notes literal adapter and is cloned for prepare/status/UI
work; it is not reconstructed on each status call. The separate previous receipt
query does not read current document state or bypass the document check.

## Added coverage

Two integration tests use the existing private socketpair lane. They check
revision 8, receipt retirement at 8, revision 9, rejection of 8, rejection of
different content at 9, continued valid reads at 9 and 10, and rejection of a
concurrent read while the first reply is withheld. Both verify no effect-channel
writes; the concurrent test also verifies no extra datagram was queued.

The workflow retains the automation package, selected Notes original-owner and
projection tests, pinned real Session/App, scoped lint and official formatter.
Its only change is the new branch's push trigger. Results must come from this
candidate's artifacts; the parent's pass is not transferred to the new source.

## Source review

The two Rust files and workflow were read back from the exact candidate and
matched submitted bytes and Git blob identities. An independent static review
found no blocking issue. Existing BUILD globs cover the same files; no new
product caller, caller inventory, dependency or authority was introduced. Static
review does not establish compilation or a passing full caller scan.

## Boundaries

This is an in-memory constraint on accepted reads within one attachment. It does
not order asynchronous status report delivery or persist across daemon restart
or reattachment. An actual App checkpoint rollback has not been qualified; the
added order tests use a controlled peer. Destination tombstones, cancel/commit
races and late-commit exclusion require an application protocol change. Real
long-running/network-wait adapters, full model-facing handler qualification,
production authority, native kernel/pixels, complete repository CI and independent
learned hierarchy benefit remain open. Full ACT-2 promotion remains HOLD.

The parent extension's original successful evidence is retained separately in
https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5589 . It concerns
one correlated App lifecycle, not independent scientific trials.
