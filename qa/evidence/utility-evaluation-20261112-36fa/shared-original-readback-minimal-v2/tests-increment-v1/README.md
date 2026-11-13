# Shared original readback: test source increment v1

This is a prepared, unformatted and uncompiled test increment. No new test or qualification gate has run.

## Fixed source dependencies

Apply the 15-file production packet `92a1567ac32c886d9d7386fb80915071475528bf`, the separate Linux cfg correction `812b8308dbec3ee818bcbb7eae41fb60da10e086`, and the original Trainer completion-observer increment `85d28ef8d6dd6f4fd48f5380b68b4e389a7427c1` before these exact changes. The command-support preimage is the observer after-image, not the older cc57 file. The two independently prepared transport test files are byte-identical to packet `bf5e43e47661e0209b22402580a5d6a0e3c6dc4b`.

## Changes and preservation

The packet contains ten paths: five new and five modified. Four modified files only append cfg(test) module mounts. The fifth is the existing UID-0 FinalUse test: three added calls assert that shared export is rejected while Awaiting, after actual Prepare, and after actual late B withdrawal has left an Installed reader with an Uncertain FinalUse result. Removing exactly these additions restores the entire original file. Its old assertions remain, but its AST is intentionally changed; it is not an unchanged-test claim.

Six new export tests use the existing completed PublicationFixture and real original publication, Material/Trainer/Evaluation readback peers. They test successful cold admission and repeated same-client export, withdrawn B before admission, changed Artifact CURRENT, B withdrawal after export, and full expected T/E signature mismatches. Only untrusted recovery metadata is corrupted for the latter two negatives. This fixture has completed upstream mechanism work and is explicitly not the new Fresh ten-owner Root path.

Four independent transport tests cover real alias competition, cancellation of the winning T exchange future, the unchanged original aggregate request limit, and the original absolute expiry. Budget and expiry use the original service implementation; they do not test a copied limit. A read-only cfg(test) counter observation determines actual requests already used by export. No counter, nonce, deadline or original frame is rewritten.

The three bundle test hooks expose only an actual original T readback, pointer equality, and the next-request-id observation. They return no client, descriptor or new execution authority. The readback hook advances the original client normally; it is not a state-free observation.

## Limits that remain

There is no formatting, compilation, runtime, full-source collector or qualification result for this increment. It does not establish public four-slot capacity or a real independent B result. The complete Fresh ten-owner provider and true C daemon normal path remain separate engineering work.

Cancellation of `read_original_predecessors` during its original exchange is the tested slot-fencing case. Cancellation of Version's `share_original_evaluated_readbacks` after its spawn_blocking work begins is a different delivery-Unknown case: that blocking operation may finish with sealed readonly state or fail without restoring Fresh. These test sources do not equate those events.

No old 4/128/300 limit, timeout, stack setting, retry policy or original production exchange has changed. Source/caller/protected registration and final literals must follow actual final formatting and the original full collector. The existing UID-0 method remains in the original Root inventory; the ten new default methods must be discovered through their real module mounts.
