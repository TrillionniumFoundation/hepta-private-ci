# Controlled archived-GRU recovery on the original async invocation

This gate composes the archived `B4_gru-seed-700.npz` with the durable async
owner from the preceding joint gate. Model proposals do not create effect
authority. The model digest, exact source, boot, task, deadline, observation
budget and invocation are bound before use. A nonzero post-inference hidden
state, the `ensure` action, its public feature vector and the exact pending
invocation are committed in the same SQLite owner before the only release.

Eight exact-source tests pass. In the central case, the original controller
commits h1 and the pending invocation, the original worker is stopped through
its pidfd, the controller sends the sole release and exits with code 18, and a
different controller restores h1 while the effect is still UNKNOWN. The
restored controller cannot rerun h1 or resend release. Only after the same
worker continues and its exact original payload is confirmed does the model
advance to h2. Hidden bytes, features, sequence and `ensure, stop` actions then
match an uninterrupted reference exactly.

The remaining cases cover:

- controller death before release, preserving h1 and UNKNOWN without an effect;
- actual death after h2 inference but before commit, followed by deterministic
  recomputation from the retained h1 checkpoint;
- an opaque physical effect that remains UNKNOWN and cannot advance hidden;
- an effect disappearing after initial confirmation, which remains PENDING;
- a different real archived checkpoint, semantic checkpoint tampering with a
  recomputed checksum, and a failed h1 commit, all rejected before authority is
  used.

Independent review reproduced a pre-publication freshness defect: the first
version ignored a second UNKNOWN read, advanced hidden and cleared pending.
The repaired source requires both exact invocation knowledge and the public
complete view to remain confirmed before h2 inference. Red and green source,
scripts and results are retained separately.

`gru-async-final-originals.tar.xz` contains every final SQLite database, intent,
payload, event timeline, inputs, source postimage and the raw test log.
`freshness-red-green-originals.tar.xz` contains the reproduced defect and repair
validation. `INDEPENDENT_AUDIT.json` checks source/model bindings, database
integrity, original payload hashes, process chronology, h1/h2 identity and every
negative case. `SHA256SUMS.json` in the qualification root binds these files.

This is a Linux, same-UID, same-boot, cooperative immutable-owner fixture for
one original invocation and two deterministic public feature states. It does
not qualify a general multi-step policy, hostile writers, copied-state or power
loss, production Root/AuthBus/FinalUse, learning benefit, full cost, promotion
or adoption.
