# Current physical source admission and original owner qualification

The SQLx/Chrono Cargo changes and the current exec-server tree caused strict historical source admission to reject the real current workspace before the original owner checks could run. This change adds exact inverse relations for the complete known source pairs and tree, and separately captures the actual current dependency graph and physical source identities. Mixed, unknown, replaced or changed inputs remain rejected.

## Source identity

The tested local source is `af2e81fafc6bc1ba0cf733acee260b22c55a5461`, tree `7025bd3a69ff2b5ca7339e2ddb419b54f137a212`. Applying the seven published source files to PR7196 parent `86a51df03f698506b18d1c0fb51d3fa1149c5da6` reproduced that exact tree through GitHub GitData. This publication adds the execution evidence to that source projection. Its new commit must receive its own original workflow result.

The fixed HIA compiler remains `0de5657a80f96b138525ac7ee9ce11712a83a10d`. Original methods, assertions, fixed fixtures and budgets are preserved. The actual current graph is recorded separately from the historical inverse; no claim is made that the current dependency graph equals its predecessor.

## Actual execution

The 22 independent source and tamper controls passed. All seven original owners passed: the 159-case file-update matrix, filesystem effects, standalone patch, patch application, patch summary, the formatter's checked/wrapping policy and eight negative controls, and the complete original formatter public comparison. Source/native terminal readbacks passed. The formatter used an independent Cargo target after the earlier shared-target attempt correctly rejected a missing defining-crate receipt.

The complete physical workspace was materialized and checked: 10,216 tracked files and 121,240,383 bytes, each matching its exact Git blob. Earlier source-admission, sparse-workspace, partial-file and formatter receipt failures remain in the evidence. `independent-review.json` records a read-only source/identity review and makes no execution claim.

## Complete selected execution evidence

The 27 parts form one 26,340,328-byte tar.xz archive with SHA256:

`02002143a97fa44f02e14fd50450f3f3f1afc37a724f1093e99b7367a3dd0261`

It contains the complete selected report and command-output closure: 2,442 logical files, 2,245 distinct payloads, and 467,130,806 uncompressed bytes. Every payload and the full logical-path index were independently read back in one sequential archive pass. `evidence-index.json` inside the archive maps the original paths to content-addressed `sha256/<digest>` members. The original compiled Cargo targets and external immutable toolchains are retained at their recorded physical locations and are not included in this archive.

Reconstruct the archive in an independent output location:

```sh
python3 reconstruct_evidence.py --output /absolute/new/location/execution-evidence.tar.xz
```

The script verifies every part's length, SHA256, Git blob identity, offset and the complete archive identity before reporting success. It refuses to overwrite an existing output. Inspect `evidence-index.json` to locate each original report and full output. The reports, rather than rounded elapsed values in the overview, are the execution authority.

This checkpoint does not qualify the new publication's full CI, the complete HIA stack, a fresh native16 predecessor generation, or retirement of the old implementation.
