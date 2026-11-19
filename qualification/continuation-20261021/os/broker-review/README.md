# Broker session-budget source finding

Read [FINDING.md](FINDING.md) for the exact-owner finding, caller limits and impact. This folder contains pinned source and small review evidence. It does not change the broker implementation.

**The diagnostic [session_admission_repro.rs](session_admission_repro.rs) is UNEXECUTED and UNCOMPILED in this audit.** Its expected behavior is a source-derived reproduction recipe, not a recorded test pass. It is not installed in a product test suite.

[Source identity and retrievals](source-index.json) bind the broker at #210 and #218 to the same exact blob. [Current owner metadata](OWNER_METADATA.json) and [the seven changed #210 paths](PR210_CHANGED_FILES.json) retain the relevant compact API evidence. Full PR bodies and redundant API responses are omitted; their original response hashes are retained without implying that those hashes reconstruct the omitted content.

The [pinned broker](broker-original.rs), [existing identity tests](session-identity.rs), [original boundary document](ORGAN_BROKER.md) and copied Cargo manifests support the limited source review. No server/application exploit, native execution, device effect or complete OS semantic review is claimed.

`MANIFEST.json` hashes all other files in this folder. Recompute it after any formatting or content changes.
