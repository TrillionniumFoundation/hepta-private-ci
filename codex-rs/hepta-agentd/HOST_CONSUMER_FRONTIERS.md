# Original consumer frontier service lanes

The trusted root launcher supplies `consumers.device` and `consumers.notes`, each
with `state_dir` and `owner_id`, plus `sockets.device_frontier` and
`sockets.notes_frontier`. Both lanes must be present together. They use the
original `HostConsumerFrontierRequestV1`/`ResponseV1` closed 16KiB protocol; no
request selects an owner, state directory, initialization or epoch reset.

Both `owner_id` values must equal the actual canonical issuer's signer ID.
Original `FinalUseAuthority` requires that identity when verifying a grant and
addressing its external frontier. Independence comes from two root-protected
directories with different actual device/inode pairs. Different path strings
alone are insufficient. Each directory must already hold its original frontier;
runtime opening never creates a missing registration. No signing key or root
directory descriptor is transferred to the consumer.

Each request uses the fixed captured UID/PID and retained pidfd. The exact
original writer lease dispatch fence covers retained-proof validation, the
canonical issuer head read, original backend load/CAS and the post-I/O clock,
expiry and unchanged-head check. The backend's original CAS includes durable
replacement and exact readback. An uncertain result or transport closure must
permanently fence the original client; a local nonce claim is never refunded.
The server does not reconstruct a nonce set from an opaque frontier hash.

Fresh trusted bootstrap derives both initial frontiers from the canonical
issuer's actual revocation head. It separately creates the genuinely fresh
original CognitiveStore, captures its coherent anchor and awaits close before
registering the initial checkpoint. It derives the complete writer binding from
the verified original root proof. These operations are absent from ordinary peer
wire, and an existing or partial state cannot be replaced by a new genesis.
The current fresh-bootstrap implementation is the explicit Root qualification
fixture. The production launcher must perform the same original-owner sequence
and deliver the public bundle through the agreed sealed descriptor; runtime
opening remains strictly open-only.

The explicit UID 60001 qualification uses two actual original
`FinalUseAuthority` owners with the same canonical signer ID, separate local
journals and original `RootFinalUseFrontierClient` instances. The root parent
transfers its already held pidfd and exact writer registration through a fixed
bootstrap channel. The original `AgentdRootAuthoritySession` supplies the actual
500ms observation feed and BOOTTIME clock. Two distinct canonical grants for
the existing exact no-effect qualification binding are claimed, entered and
rejected on replay; their complete frontiers must read back from the independent
protected stores. The local journals use a private `/run` qualification directory,
while the external protected frontiers use the selected persistent root bind.
This is a service composition qualification, not physical power-loss evidence or
an actual Notes/HOS2 operation. Real operation payloads still require exact
original trusted-compiler admission; a static effect lease cannot authorize
arbitrary later payloads. Full writer publication/recovery and production service
deployment remain separately qualified stages.
