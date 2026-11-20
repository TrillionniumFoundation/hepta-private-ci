# Original blob-size gate: exact five-stage candidate

The unchanged repository gate passed against the complete new codec stack: base `63f494553a735bd55a3fef7cfe2e76604cd6db7d` through candidate `0a57d319ee479c820c36618d6c713881829c04cc`, **53 changed paths**, original **512,000-byte** ceiling. This was an actual execution of `check_blob_size.py`, not a manual comparison of reported sizes. The command exited 0 in 0.520945 seconds in the managed cloud workspace; its entire owner, including exact object import, took 1.683414 seconds. HEAD, refs, index and config were unchanged during the gate. These costs are nested and must not be added.

The original gate source is pinned to Git blob `18bc6175c274abaeabe3ef0c32d82627d498bbe7` and SHA256 `eb7a9eab936b7c7948ed13fbd6d6aca09aa38997c20685a8ee12d72e388d52c3`. The unmodified allowlist is Git blob `7d46f41aa8fa354ce459471ba590804259548a33` and SHA256 `56a9a1cd05a0d81bba73a43c19e1451b213443f631dabacfa5b4e8d145e43d1c`. No new path or exception was added. Every new blob is at most 393,216 bytes.

## Exact Git reconstruction

The desktop already held the actual commits and trees from a bounded standard Git fetch. A read-only metadata export retained twelve exact raw Git objects: two commits and ten required directory trees. The resulting 19,679-byte archive has SHA256 `166ad35c8ee01d436eea78c03ee551955496dc6f8f979dcdd450c2e18b1f5ea3`. It was transferred with a fixed file-version token and independently rehashed.

The cloud workspace already held the complete original bytes of all 53 new blobs, including the 45 prospective-freeze files and 8 measurement additions that had been independently read back from GitHub. A fresh isolated Git object database imported the twelve metadata objects and those 53 blobs. Every raw object's type/length/header Git SHA and SHA256 were recomputed, and every imported object was read back with `git cat-file`. The exact Git diff produced the same complete 53-path set. The gate then executed its own normal diff, size, binary-change and allowlist logic using those actual commit identities. No repository contents, source-unit code, input freeze or original gate logic were synthesized or substituted.

The reusable export and reconstruction controllers, exact object manifest, original argv, complete stdout/stderr and before/after state records are in the verification archive. The cloud object database is an isolated local validation cache; it is not a replacement source ref or a merged change.

## Retained preparation failures

The first desktop preparation fetched the candidate commits/trees in 3.313544 seconds but its object check failed with missing blobs while lazy fetching was disabled. That preparation was not a gate run. The standard filtered fetch added promisor metadata to this newly created clone's own Git config; HEAD, refs and index stayed unchanged, and the separate metrics worktree was not touched. The exact before/after config hashes and stderr remain retained.

A proposed 10,580,934-byte exact-blob transport package was then prepared. The first transfer attempt was rejected because an oversized local tool response inserted ellipses into base64 text. No three first-attempt destination files existed on readback. A corrected attempt read bounded base64 pieces and verified their alphabet/length before transmission: parts 000 and 002 were actually stored and independently rehashed at 786,432 bytes each; part 001's call timed out and a later exact-path read reported it missing. No unknown write was replayed. The package manifest and all observed transfer outcomes remain retained; its duplicate source-object payloads are not copied again into this verification archive.

A separate bounded native Git fetch of the 53 exact blob IDs timed out after 45 seconds (owner 45.062202 seconds), again before the gate started. Its source/config/ref/index state stayed unchanged. The final metadata-only export and cloud execution avoided another large upload. All failures are preserved and none is relabeled as a successful gate.

The original formatter and 24 synthetic controls ran earlier on desktop. The successful blob gate described here ran in the cloud workspace. Neither is a new upstream native task replay, model call or training update. The final publication head will be checked separately with this same original gate after adding these verification receipts; that exact final-head receipt belongs to the subsequent checkpoint rather than recursively changing the head it tests.
