# Strict Source wire rejection: observed failure and repair

The restored Linux executor compiled and ran the actual Agentd library tests.
On local `f2bd9e335e08a24252e5dd2972fb8f58d29875f0`, tree
`bd4880b83701fd41635429d0903a971204a8bec8`, **three tests executed: two passed,
one failed, zero retries**. The strict wire test failed at its first command
field rejection, not at an IO deadline or a Source history operation.

The current internally tagged Serde enum's unit variants accepted extra command
fields despite enum-level `deny_unknown_fields`. The decoder ignored the
peer-chosen material; this result does not show that the material acquired
authority. It does violate the intended strict zero-payload protocol.

## Repair and actual rerun

`CaptureSource {}` and `CaptureAck {}` are now empty struct variants. Their
serialized wire shape remains the original kind-only object. Both variants'
match arms and exact guards were updated; the native unknown-field assertions
remain intact and now identify the offending field on failure. The mutation
test still rejects adding a payload field. No timeout, retry, Root check or
ordinary protocol policy was relaxed.

On local `202190c3e67c8d27fd1290b3f736cdc495ac37bd`, tree
`df78d019a1efae10199bf58d527e5ab5af89f2e9`, the same scoped native selection
executed **three tests: three passed, zero failed, zero retries**. It completed
at 2026-11-12 04:27:03 UTC. These are the strict wire test and two Source pin
tests checking original read-only descriptor custody and recomputation of the
published task. The 1,095 non-selected tests are not passes.

The exact source also passed 21 Root Source closure tests and the quick audit of
all 504 declared boundary markers plus 369 protected rows. The latter does not
scan the complete product call-site inventory. The complete inventory scan on
the earlier `723a2d7` remains a separate attempt.

## Evidence and qualification boundary

Both native runs retain their complete original log, run metadata and JUnit.
The before-fix JUnit is 2,820 bytes, SHA256
`6ee3c0d07740758b494e87766edaf3b05fe1a76c124731903293510dd746fb84`.
The after-fix JUnit is 1,161 bytes, SHA256
`f5a4036872f2442c49ac4862c4bc0e7477c04d3fc9ea6542c4611ca0a67ad4f1`.
Every XZ archive was decompressed and compared byte for byte. `manifest.json`
records both original and archive identities.

The GitHub commit API produced published counterpart `81e88a1b…` with the exact
same after-fix tree. `local-source-objects.json` preserves original local Git
commit objects and their verified object IDs, plus the publication mapping.
This mapping does not assert a second native run or a CI PASS on the new commit.

The native runs used actual UID 1000. The cases requiring actual UID0 and Root
directory custody remain unexecuted locally. This Root-only stage does not
contain the later daemon companion or ordinary Initial loader. Full ordinary
**Adopt / NoUpdate / daemon plus Root cold restart remains 0 / 0 / 0**.
