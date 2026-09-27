# cognitive.types runbook

## Local qualification

From the repository root:

```bash
cargo fmt --manifest-path codex-rs/Cargo.toml \
  --package codex-hepta-cognitive-types -- --check

cargo check --manifest-path codex-rs/Cargo.toml --locked \
  -p codex-hepta-cognitive-types --all-targets

cargo clippy --manifest-path codex-rs/Cargo.toml --locked \
  -p codex-hepta-cognitive-types --all-targets -- -D warnings

cargo test --manifest-path codex-rs/Cargo.toml --locked \
  -p codex-hepta-cognitive-types

python3 qualification/cognitive-types-v1/verify_vectors.py
python3 qualification/cognitive-types-v1/verify_domain_vectors.py
node qualification/cognitive-types-v1/verify_domain_vectors.mjs
```

Then run the five consumer compile-contract tests and the `cognitive.store` adapter tests.

## CI lanes

Required module lanes are `hnmf-qualification`, `cognitive-types-exact-qualification`, `cognitive-types-fuzz`, `cognitive-types-mutation`, repository integrity and architecture convergence.

The exact qualification workflow records both the pull-request head and the synthetic merge candidate. An artifact is valid only for its recorded commit and tree.

## Failure triage

### Schema/version rejection

1. Record schema/version/contract IDs and error code.
2. Verify that the producer uses a registered pair.
3. Do not add a permissive fallback.
4. Add a versioned adapter or revert the producer change.

### Digest mismatch

1. Capture only digests and canonical byte lengths.
2. Compare canonicalization, Unicode and digest profile IDs.
3. Run Rust, Python and Node vectors.
4. Quarantine the candidate rather than rewriting the expected digest.

### Comparison mismatch

1. Stop the call-site switch.
2. Classify semantic, ordering, normalization, omitted-field or stale-snapshot cause.
3. Reproduce on the same immutable snapshot.
4. Fix the adapter or contract.
5. Restart the observation window.

### Selector unresolved

1. Verify asset-manifest and selector-index digests.
2. Rebuild the index from the authoritative asset.
3. Do not fall back to string-only acceptance.

### Fuzz crash or mutation survivor

1. Preserve the corpus or mutation artifact.
2. Add a minimal regression test.
3. Fix the validator or codec.
4. Rerun exact-head and synthetic-merge qualification.

## Call-site switch

The switch requires zero unexplained comparison mismatch, the consumer-specific acceptance check, exact-head and merge-candidate receipts, a rehearsed fallback and no unknown schema/version observations.

## Fallback

Disable the canonical call site, retain evidence and resume the registered compatibility path. Do not delete canonical receipts or rewrite durable history. Record the exact failing SHA and qualification artifact digest.

## Release statement

Do not describe the module as production-ready solely because source tests pass. Application composition, exact evidence, acceptance and external release states remain separate.
