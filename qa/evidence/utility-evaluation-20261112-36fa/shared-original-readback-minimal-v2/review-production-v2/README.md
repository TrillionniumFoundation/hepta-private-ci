# Shared original T/E readback: production candidate v2

This is a new isolated 15-file candidate based on exact cc57c7198db6293ccca562253c42fffbe2a04633 / b7b357c07b5539769a068c6b9b009629f5612d1e. It is prepared in V8 and saved as immutable Git blobs. It has not been formatted, compiled, executed, or applied to any native source. No source commit or reference is changed.

## Provenance

The earlier local review-production-v1 package had only computed identities: manifest 6bca6aff018236da98f8f8de569c868a9dcde640, packet ea49b61858aa6a8369730ae9a30486672a74290e, patch 1fb5aad7ca27ff43afb4972cf5a06b149d42f32a. Those objects were not uploaded before the cloud environment became unavailable; subsequent Git reads returned 404. The preceding design document 5976d8b49c2fea805e45ba881a637e6f735e3409 also had no verified remote copy. This v2 is not claimed to recover those bytes. Its full after-images and new packet are individually created and read back from Git.

## Concrete behavior

The Version host may export one sealed OriginalCircuitPublishedEvidenceReadbackV1 only for its evaluated NoUpdate profile, after actual FinalUse Published and the original complete current read. Recovered hosts must first perform the original recovery double read and reader admission; an initial Published enum is insufficient. Each subsequent export repeats the original current validation. A missing publication or reader, non-installed phase, changed original predecessor, expiry, or failed publication rejects export.

The same retained T and E clients are consumed, checked against the complete opaque original responses and signatures, checked for a live original peer/channel, and permanently marked execution-requested before Arc construction. The bundle has private clients and context. Its public surface is Clone and actual predecessor readback; there is no public client, descriptor, reconnect or Execute access. The internal borrow used by the original S/C remote-source implementation remains subject to the spent execution flag.

The existing Version state retains this same bundle. New explicit S/C constructors check its complete evaluated context both at construction and on every observation. They call the original remote-source/owner operations, preserving T/E then S ordering. The original by-value entry points and original branches remain. Removing the 19 declared changes exactly restores every modified cc57 file. For T and E command modules the only changes are private module mounts; their complete original clients, exchange functions and contracts are byte identical.

There is no new queue or serialization protocol. The original shared slot.take / slot=None behavior governs competition and cancellation. Independent ordinary C startup and external reads may compete; failure remains Unavailable/Unknown. The code does not promise every schedule succeeds. No request counter, nonce, 128 aggregate limit, absolute deadline, transport timeout, 4-connection cap, peer identity or session lifetime is reset or increased.

## Validation still required

The static byte review checks full pre/post identities and inverse transformations, not Rust type checking. Original formatter, compiler, full collector, source closure, native behavioral gates and final exact-source admission remain pending. Test-only shared transport cases and Version export refusal cases are separate increments; none is included or claimed run in this production package.

The intended public capacity is four T connections (Root T, Root Candidate, one B readonly stream shared by the two members, and one Version T shared with local S/C) and three E connections. This is a design calculation, not a measured public-provider result. Full ten-owner normal NoUpdate, recovery, public permits and total request budget remain to be exercised. Actual application A, independent B data, useful C and a trustworthy production provider feeding main remain separate missing deployment facts. No owner or authority is fabricated.

## Integration

This packet is against cc57, not the already drafted provider overlays. Merge only its explicit hunks with the immutable provider V1/lib mount and later test-only candidates; do not overwrite unrelated provider changes. No CALLERS, QA, workflow or allowlist update is hidden here. Final source registration and exact protected literals follow actual formatting and the original full-source collector.
