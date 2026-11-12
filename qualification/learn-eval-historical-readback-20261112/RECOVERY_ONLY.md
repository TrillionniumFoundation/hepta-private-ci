# Recovery checkpoint only: original Initial Artifact readview postimages

This branch preserves 19 exact original frozen postimages after the execution
environment disconnected. It is not a build candidate, a runtime integration,
or a qualification result. No pull request is intended for this checkpoint.

The base is `d95c8993b5a80d1636aa74f369586e5b75ef420e`, tree
`c497693c3dafef942e62889b38eb7d3a9baca5df`. Every source and test file in
`initial-artifact-readview-recovery.json` matches the full Git blob SHA
recorded before the environment became unavailable. The JSON manifest itself
was recreated from those recorded identities; it is not claimed to be the
original local manifest's byte sequence. Original source and fixture postimages
are preserved in separate commits for review and recovery.

## Incomplete dependency closure

The original readview stage was written on top of an uncommitted Source capture
client stage. Its three cross-cutting files still reference that stage. The
original complete terminal client, publication stream, connection helper and
close-test postimages have not been recovered. The earlier Source history test
addition and its full handoff qualification document also remain unavailable.
Known Git SHAs alone are not proof that those bodies exist remotely.

Therefore the checkpoint intentionally retains the original code without
claiming that this tree compiles or that its caller guards match. It must not be
used as a runtime or merged as a production candidate. A separately identified
candidate must remove the unrecovered Source capture dependencies and retain
the complete readview, FinalUse, CURRENT and writer-only update checks.

## Evidence boundary

The original local `just fmt` completion is recorded for the original working
postimages only. No native test or scoped agentd Clippy run completed for this
readview stage. No source QA or formatter result is transferred to this new
checkpoint tree. Earlier reader component results do not validate these files.
The real ordinary main loader is still absent; A completion, independent B,
C update and whole-system cold recovery are not established.

The retained component test uses the actual UID0/UID60001 harness, real files,
the original session and the original writer lock. Its model and role keys
remain fixture inputs, and the added test has not run.
