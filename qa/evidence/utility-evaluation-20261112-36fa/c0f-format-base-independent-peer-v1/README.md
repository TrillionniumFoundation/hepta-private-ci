# Independent c0f formatting-base object review

The fixed object increment has no identified static object or snapshot-closure defect. Execution remains on hold until the actual successor loader and exact requests are reviewed. No H call, formatter, Rust test, source gate, native gate, source write or ref change was performed by this review.

## Verified scope

| Object set | Blobs | Trees | Commits | Total |
| --- | ---: | ---: | ---: | ---: |
| Original c0f snapshot | 14,315 | 1,778 | 1 | 16,094 |
| Declared cc57 and 246d snapshot union | 14,615 | 1,832 | 2 | 16,449 |
| Shared exact object identities | 14,243 | 1,768 | 0 | 16,011 |
| Required c0f increment | 72 | 10 | 1 | 83 |

The three-snapshot union is 16,532 objects. It excludes recursive parent history and future source-overlay objects. The original c0f raw commit is unchanged, including its real parent OIDs, timezone and lack of a terminal LF. Its typed commit OID differs from the blob OID used to preserve the raw commit file.

The reviewer independently retrieved 27 complete Git objects: five small source/control originals and 22 encoded pieces. All three reconstructed raw/gzip packages match their complete byte counts, SHA-256 values and Git blob identities. The audit parses original c0f tree bytes and independently constructs the cc57/246d trees; it does not import or execute the native recovery script. Every provided object is checked against the exact set difference and its full raw typed Git hash.

## Original formatter requirements

The fixed formatter uses `rev-parse <base>^{commit}`, a diff against the resolved commit, `show <base>:<path>`, and current tracked/untracked file enumeration. These queries need the complete base snapshot and current repository state; they do not traverse the base's parent history. This review preserves `just fmt --base c0f78493f815780f68b9bf5e390a21314d79311f` and the original 900-second budget.

## Remaining execution conditions

The loader must actually verify the shared objects, import authentic bodies only into the approved fresh destination, verify the resulting closure, and preserve old source/index/refs/object stores. No loader or final typed request is present in this reviewed package, so those implementation properties are not yet verified. The unchanged 1 MiB limit must be checked against each final exact request and its decoded-write contract. The four existing encoded parts total 943,816 bytes; that fact alone does not qualify a complete request.

Historical full inventories and exact byte recovery are not fresh filesystem observations. The shared blob metadata is grounded in those inventories; this review does not claim a new native body read of all shared blobs. The 72 missing blob bodies, 10 tree bodies and original commit body were read and hashed completely.

## Artifacts

`REVIEW.json` is the peer conclusion. `BYTE_REVIEW_v2.json` contains the complete verification results, all 83 per-object rows and the actual full-GET input ledger. `verify_original_objects.py` is the pure offline reproducer. `SOURCE_INPUTS.json` identifies every original and encoded input. `REVIEWER_PREPARATION_NOTES.json` preserves two reviewer-only bookkeeping corrections; the first completed byte report is retained unchanged and superseded by v2. Neither correction was a source package or gate failure.

All large original inputs remain losslessly available through their already archived encoded parts; this placement does not add oversized raw evidence files or request a blob-size exception. This is a new evidence window, independent of the frozen 5128 cutoff.
