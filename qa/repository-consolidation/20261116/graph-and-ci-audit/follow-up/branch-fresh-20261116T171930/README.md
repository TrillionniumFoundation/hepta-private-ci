# Fresh branch protection and original pidfd guard review

The remote snapshot was observed at 2026-11-16 17:19:30 UTC. It contains 7,318 branch heads and 87 protected HIA heads. Main remains at its original commit; the integration ref remains at the previously published 7e04259b commit.

Since the preceding 14:54 snapshot, three Cell experiment branches appeared. All three descend from a protected HIA marker. One HIA union head advanced, and the integration ref reflects the already reported publication from 285e971b to 7e04259b. No branch disappeared and no new unprotected branch appeared. The full original names and before/after SHAs are recorded in the manifest and immutable snapshot.

The protected vector combines prior protected names, both HIA marker ancestries, and conservative protection for newly created HIA-named heads. The candidate examined in this snapshot contains neither protected marker and none of the 87 protected heads. Future HIA advances remain protected; this dated observation does not freeze their work.

## Graph provenance

The preserved parent walk includes the observed remote roots and the stated unpublished source candidate used for protection checks. The manifest separately reports the remote-only graph, the augmented graph, and the exact candidate-only commit rows. Candidate objects are not counted as published branches. The parent walk is stored as ordered lossless gzip parts, each within the unchanged original file-size limit.

## The two original pidfd guards

The incoming tip 00aef9bd81a9f01b26523e6600d7d797f0810067 has one unique commit relative to the candidate. Its complete change adds the original OwnedFd parameter to two function-order requirements in CALLERS.toml. Both complete incoming function-order entries already match the current decoded manifest exactly.

The current manifest retains 1,645 boundaries and 819 protected-file rows. Its unrelated newer selection requirements remain intact. Historical raw TOML was parsed offline with the same standard TOML parser after exact byte verification; the production loader and its size bound were not changed. The initial production-loader rejection of the historical oversized document is recorded.

An ordinary merge preview at 15287f0562e251250f5553d603b66c9a8f81ecde has exactly one conflict, the physical CALLERS.toml file. Resolving that file to its unchanged current bounded representation preserves both incoming guards, every current row, the gzip payload, and every other source and audit path. The resulting whole tree is byte-identical to the baseline. The proposal preserves the original incoming tip as the second parent and would retain two additional original branch heads.

Root must recheck the relevant manifest and source identities when replaying this proposal after later reviewed commits. This audit agent changed no remote refs. The local proposal and its exact resolution evidence do not assert that the proposal is already published.

## Reading the evidence

The manifest records compressed and original byte lengths and both SHA256 and Git blob identities. Verify those identities before and after decompression. The parent graph uses the listed part order and byte offsets. Restore evidence into new isolated files and inspect it without executing archived code.
