# A/Material to Trainer split: independent peer

The exact two-file proposal a72dc791ed6026ae49b0500a52dc295f9b3622ad has no specific static blocker in this review. Both source afterimages and the exact preimage were independently fetched in full.

The old constructor still builds actual A/Decision/Outcome/Material once, then constructs the same Trainer with the same four old internal test transports. The Material-only return occurs before any Trainer custody file, Trainer, or test transport is created.

Independent byte checks preserve the 1,970-byte original A prelude, the 3,204-byte actual A-through-Material body and the 2,299-byte old original_bytes/finish suffix. The old parent is recovered exactly by removing the one child mount and reversing the one constructor replacement. The Trainer subrange is unchanged after explicit reference-spelling adjustments.

The new module's visibility, inherited trait imports and concrete Copy optimizer were inspected. This is not a compiler result. The original Result error cleanup and explicit finish paths remain; cancellation and future public transport lifecycle have not been executed.

Production Root CURRENT remains a separate unresolved custody/interface requirement. The extracted VersionFixture still uses its explicit test store. No H, Rust build, formatter, test, QA gate, source mutation, or ref change occurred.

See REVIEW.json for exact scope, BYTE_REVIEW.json plus review_static.py for reproducible pure text comparisons, and INPUT_READBACKS.original.json for original Git retrieval responses.
