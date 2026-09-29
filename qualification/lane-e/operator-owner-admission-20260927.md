# Owner-bound operator admission: implementation checkpoint

Base source: `e5174734bdc0c3b4e3d0b5b391ab39b5dff92ca5`.
Base tree from Git objects: `177a5c6e4d13e248338cc86aadc4d476348948fe`.
This is a code-change record, not a qualification receipt.

V3 admission now borrows the actual root-authenticated `LedgerWriter`. It requires the evaluator's dataset-freeze signature and an independently controlled observer's complete row signature. The owner recomputes the entire frozen receipt from its current durable ledger; public snapshots, rehashed receipts and caller-selected verifier instances no longer construct a V3 input. A proof cannot be cloned. Fitting consumes it and repeats admission using the host's current time, rejecting expiry and clock regression.

The version-2 signing preimage binds all rows, duplicate identities/evidence, the complete canonical sensor/action grid, minimum cell support, artifact/producer/generation/profile, dataset identity, current trust-distribution digest/generation and signer-registry epoch. Signatures cover a domain-separated commitment to the bounded preimage, not a truncated row list. Signed materialization is explicitly capped at 4096 rows, matching the owner reader. Legacy numerical V1/V2 utilities remain compatibility surfaces and are not production admission.

The immutable V2 payload and validated artifact types previously present in a private module are now exported. Rustdoc testing is enabled. Added tests exercise an actual durable writer, root-signed trust, independently signed freeze and row attestations, real fitting, altered configuration/targets/signatures/epochs, duplicates, ordering, bounds, proof expiry and clock regression.

Required before qualification: exact-source and ordered-parent synthetic-merge compile/test/lint/coverage, evaluated-shadow E2E and signed evidence. None has been marked successful by this checkpoint. Existing CI evidence with a tree or commit-message mismatch must not be reused.

Compatibility: the unreleased V3 verify functions now take the owner and freeze/row signatures; V3 fit functions also take host time. Reissue detached V1 row signatures under the new owner-bound version-2 signing payload. There is no silent trust upgrade of old inputs.
