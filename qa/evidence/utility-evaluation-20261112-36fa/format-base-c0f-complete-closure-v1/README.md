# Exact c0f format-base object preparation

This package supplies the original format base `c0f78493f815780f68b9bf5e390a21314d79311f`, tree `313ee34febc8ccc54c611ab56286e289518c63cb`, without changing the formatter baseline or running a native task.

## Result and scope

The complete c0f snapshot has 14,851 leaves and 16,094 distinct Git objects: 1 original commit, 1,778 trees and 14,315 blobs. Every derived tree body was compared byte for byte with the previously retained TREE_AND_ANCHOR original. The 1,293-byte original commit body has SHA256 `8aefa9dd70ba73ec646dbca656270509dfa3c1afed23b08e10330540a587d4d3` and hashes as a commit to the exact c0f OID.

The declared isolated pack contains complete cc57 and 246d snapshots: 16,449 objects, comprising 2 commits, 1,832 trees and 14,615 blobs. Recomputing both roots from the preserved full cc57 inventory and the original five parent substitutions reproduced that scope exactly.

The c0f increment against this declared pack is **83 objects: 1 commit, 10 trees and 72 blobs**. All 72 blob bodies, totaling 2,216,414 bytes, were fetched by their fixed original Git identity and checked against the complete c0f inventory's length, SHA256 and Git blob hash. No blob is missing from the prepared increment. The remaining **16,011 shared objects** are 1,768 trees and 14,243 blobs. They are required inputs to a future approved materializer and must be fully reread and verified there. The expected union is 16,532 objects before adding any future source overlay.

This is a complete snapshot dependency calculation, not a full ancestry claim or current native availability observation. The c0f commit retains its real parents in their original order; this task did not traverse or fetch parent history. It did not change an old repository, source file, index, ref, runtime dependency, test filter, stack or budget.

## Files to consume

- `FINAL_REVIEW_v2.json` is the final static review. Its actual Git blob is `18773795962884bc4f9d5bda249866cfffa69a1c`.
- `TRANSPORT_INPUT_MANIFEST.json` (`828e7ee48826247d19068b706978689bebf630af`) identifies the compact input containing all 83 complete raw objects. Its four base64 pieces have been created and fully read back in Git. Decode each piece separately, concatenate decoded gzip bytes, then decompress.
- Compact input identity: 3,095,381 bytes, SHA256 `465d36f5dc99c651e59870806e8613cf2b3b5a1cecfabdce2363716c339711da`; gzip 707,857 bytes, SHA256 `4d76a6bd6afc7cfbd0b11f7d2283c3db520ad215c9b21a23f7e7df1ce460c7ae`.
- `ENCODING_MANIFEST.json` (`dd99fd9ccca77fab1765e8fae4f7172a8da666ac`) binds the full 6,239,044-byte proof packet, complete 4,651,179-byte closure metadata, and 90 original Git GET SDKs. Their 10, 8 and 26 pieces respectively have each been created and fully read back.
- `FULL_READBACK_VERIFICATION.json` verifies reconstructed raw/gzip identities from all actual returned Git piece bodies and equality with every original local byte sequence. Raw and gzip Git identities in the encoding manifests are reconstruction identities: the raw large JSON and binary gzip blobs are not claimed as separately created or directly GET-readable Git blobs.
- `C0F_COMMIT.raw` is directly retained as blob `81369bfd8e7bc48a9aea6ae8d2e60e10a6fbdc6b`. This storage blob is distinct from the typed commit OID c0f. The v2 review explicitly clarifies the earlier generic helper field that labeled a typed commit hash `git_blob`; no underlying bytes or calculation changed.
- `recover_closure.py`, `build_base_packet.py`, `make_transport_input.py` and `verify_archived_packets.py` are pure byte/JSON/hash scripts. No Git command, native process, formatter, gate or test is invoked.

## Original format contract

The retained formatter is `d4eabe70b68605933240e9129245f7f4cccbde5d`. Its changed-path logic first resolves the exact base as a commit and diffs it directly against the worktree; configuration comparison can read `base:path`. It does not replace the base with a merge base. The original `just fmt --base c0f78493f815780f68b9bf5e390a21314d79311f` and its 900-second command budget remain unchanged.

The old two-snapshot materializer is `972ec74449b113a95b4ec098e562a565f23aa82f`, with input packet `06503652a2895120daf8b66e42b3a01cefeaf4fb`. Its declared imported scope lacks this c0f increment. A future reviewed successor must include the exact objects, verify the complete resulting base tree, and bind the separate final source map and actual new-repository proofs. This preparation is not that successor and is not approval to execute it.

## Preserved observation boundaries

The historical inventories are exact recovered original bytes, not new physical reads. A first local shell call failed because its default working directory no longer existed; one explicitly scoped read with workdir `/`, shell `bash`, and login disabled succeeded. No H call was used for that recovery. During archive upload, one local read of four pieces exceeded the exec output capture and produced an explicit truncation annotation. Its original SDK and the parse failure are retained. Subsequent reads used at most three pieces and required complete original identities before upload. No truncated content was accepted as a complete artifact.

All of this remains prepared evidence. No new H call, source mutation, native qualification, source gate, formatter or Rust test occurred. Earlier cc57 gate results do not establish qualification for the future overlay.
