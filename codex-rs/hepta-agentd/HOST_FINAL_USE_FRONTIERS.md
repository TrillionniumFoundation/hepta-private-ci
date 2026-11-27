# Protected original FinalUse consumer frontiers

`HostConsumerFrontier` adapts each of the two existing consumer frontier stores
for the original `FinalUseAuthority`. It uses the original
`HostAuthorityFrontierStore<FinalUseFrontier>`, not a second nonce or effect
ledger. The trusted launcher fixes two separate storage directories and one backend
object per consumer slot. Each backend owner ID must match the original
FinalUseAuthority signer ID. Under one canonical issuer the two IDs are the
same: the original consumer also checks each grant against that signer ID.
Separate actual directory identities preserve the two independent stores.
Requests cannot choose a directory or owner.

The trusted fresh path calls `initialize_fresh` with the actual initial
revocation head from the same canonical issuer. Existing or partial state is a
conflict. Runtime `open` only opens an existing record; it cannot reset a missing
record to genesis. Both require the original live writer expiry and an authority
clock. These arguments are configuration and do not themselves grant authority.

The original closed 16 KiB request protocol has two operations:

| Request | Behavior |
| --- | --- |
| Load | Read the fixed owner's existing full frontier. |
| CompareAndSet | Compare the complete expected frontier and durably publish the exact next frontier through the original store. |

Each stream accepts positive strictly increasing request IDs. A new frontier
must match the actual canonical issuer epoch/revocation revision observed inside
the original live writer dispatch fence. A successful store CAS includes its
original file/directory synchronization and exact readback; the adapter adds no
second public load window. The original `FinalUseAuthority` still owns the
complete consumed-grant set and opaque state hash. A frontier hash alone cannot
prove or reconstruct that set.

The service must authenticate the actual fixed peer and retained pidfd, enter
the original live writer fence, obtain the same protected issuer's current head,
and call `exchange`. It must also apply its original post-I/O clock and peer
checks before writing a response prefix. This backend does not implement that
socket service or authorize new peers. A post-CAS failure or expiry can mean the
write committed: it returns Unknown without a frontier and permanently closes
this object. Restoring a missing file does not revive it. The caller must fence
on uncertainty and must not retry an uncertain CAS as a fresh operation.

Development changes belong in `authority_host_consumer_frontier.rs`; behavioral
tests are in its sibling `_tests.rs`. Keep the request DTO in the shared contracts
crate and retain fixed-owner wiring. Run the original focused `just test` path
against an explicit root-owned persistent data fixture, followed by scoped
`just fix` and `just fmt`; do not rerun tests after that style phase.

Source `b80704b973d2cd3012a6631b0450330bb33c1ffd` passed five actual Root/data
cases on Rust 1.96.0: independent original stores and reopen/CAS, post-CAS expiry,
file disappearance/restoration, closed parsing/binding/replay refusals, and two
real handles racing. Original nextest execution took 0.699s. Scoped lint/fix and
formatting passed with an empty final source diff. The clock is controlled in
these cases; service wire, production authorization and recovery remain separate
requirements. [Original receipts, logs and complete source snapshots](acceptance/2026-10-23-consumer-frontier/publication.json)
retain the evidence and boundaries.

The initial five backend tests use independent owner namespaces and do not by
themselves prove this original same-issuer consumer composition. Service
qualification must exercise both original FinalUseAuthority instances and their
Root frontier clients using the same canonical signer ID with distinct actual
storage directories. Different slot labels must not become different grant
signer IDs.
