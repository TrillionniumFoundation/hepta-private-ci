# Owner checkpoint v9 review

This directory preserves the immutable v7 ledger used for comparison, the exact published V14 source-gate audit, peer and root review receipts, and the reviewed v7-to-v9 change. It contains no new actor outcome or original-owner authority grant.

From a checkout of this evidence branch, run `python qualification/memory-cell-mem8-owner/run-001/v9/verify_candidate.py`. The verifier compares the sibling `BLOCKERS.json` against the included immutable inputs. A later ledger must be supplied explicitly if it is intended for comparison; the verifier pins this reviewed v9 byte identity.

The root review found and corrected an unpublished draft reference that paired a later local audit timestamp/hash with the original published V14 path. `SOURCE_AUDIT_REFERENCE_CORRECTION.patch` records that correction. The published source-run audit and its historical remaining list remain byte-identical.

`ROOT_PREPUBLICATION_AUDIT.json` is a review receipt from before the owner ref update. It does not itself prove the update occurred. The branch/PR readback and separate root publication receipt establish publication after the expected-head compare-and-swap. All ten adoption gates remain open; only the new source and module-lock subgates are closed in this ledger.
