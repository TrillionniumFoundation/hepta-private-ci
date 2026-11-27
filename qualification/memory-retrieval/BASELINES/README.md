# Memory retrieval immutable baselines

This directory stores reviewed baseline manifests, never mutable raw artifacts. Each manifest must bind source commit and tree, target-host identity digest, toolchain, retrieval policy, model/encoder/tokenizer/index identities, workload digest, raw-log digests, parsed metrics, limits revision, reviewer and provenance attestation.

CI may produce candidate receipts but must not write or update this directory. Promotion requires a separate pull request and independent approval. Historical manifests are append-only; supersession adds a new manifest and a relation to the predecessor. No production baseline is present yet.
