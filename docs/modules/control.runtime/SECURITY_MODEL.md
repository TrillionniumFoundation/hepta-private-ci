# control.runtime security model

## Security invariants

1. Planning output is advisory and carries deny-all authority.
2. A decision becomes product state only after durable append.
3. Producer evidence is authenticated and bound to owner, generation, policy, operation, and payload.
4. Trusted time is sampled by the owner, not accepted from the caller, at every irreversible boundary.
5. Authorization is rebound to current snapshot, revocation frontier, final payload, and expiry immediately before dispatch.
6. Durable execution records form one exact-attempt state machine.
7. `Indeterminate` is never success and never authorizes automatic resend.
8. Module promotion evidence binds the complete transition tuple and is revalidated at final use.
9. Unsupported runtime scheduling profiles fail closed.
10. Generation advancement requires an external predecessor anchor; local self-consistency alone is not anti-rollback proof.

## Threats addressed

- forged or replayed producer payloads;
- evidence expiring while verification runs;
- snapshot, revocation, or final-payload drift;
- semantic journal bypass with a byte-valid hash chain;
- restart loss of request, authorization, dispatch, or terminal phase;
- stale module-promotion witness reuse;
- invalid graph indexing, handler panic, partial fan-out ambiguity, and output amplification;
- local generation rewind or skipped-generation startup.

## Residual risks and external controls

An in-process Rust handler cannot be forcibly preempted safely. The production host detects deadline violation after return and poisons the host, but hard timeout requires a process, WASM, or equivalent killable isolation boundary.

The store provides fsync, atomic replacement, single-writer locking, semantic replay, backup, and checkpoints. Resistance to rollback of the entire local state depends on a trusted external anchor.

Source tests do not establish HIL or physical-device safety, independent security acceptance, activation approval, or release approval. Those remain explicit external evidence gates.
