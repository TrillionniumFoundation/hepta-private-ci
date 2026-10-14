# Physically Verified Stem Artifact CAS — Shadow Qualification

**No production promotion, no downloaded Jina weights, no signed model-load
receipt, no allocator or accelerator-load attestation.** This is the next
additive qualification layer on top of [signed Final-use PR #1517](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/1517).

## Why

The original `StemFeatureRefV1` contains model weights, tokenizer,
preprocessor and projection digests. Even an independent Ed25519 Final-use
signature over a digest declaration does **not** establish that the claimed
bytes exist on disk or are readable, safe and unchanged.

`codex-hepta-infer-worker-host/src/stem_artifact_cas.rs` adds a real,
bounded, **read-only** local CAS byte-integrity verifier. The public signed
Stem dispatch structure now requires a private
`VerifiedStemCasArtifactsV1` value from this verifier. A caller cannot
construct this value by copying request digests into a Rust struct.

## Host-owned CAS format and file contract

- The independently protected host chooses the trusted absolute CAS root.
  On Unix it must be a **real private directory**: group/other permissions
  cannot be present, and the root cannot itself be a symlink. The host
  remains responsible for protected parent directories, ownership, trusted
  mount policy, mutation protection and revocation.
- Four Stem roles each have one **content-addressed regular file** under the
  root named exactly by its lowercase 64-hex SHA-256. Only four fixed,
  complete filenames derived from `Digest32` are opened. User-provided
  relative paths, recursive traversal, globbing and URL fetch are forbidden.
- Each blob must be nonempty, single-link, non-symlink, non-world/group-write,
  and within an explicit nonzero host byte ceiling (hard maximum 1 TiB per
  blob). Unix opens use `O_NOFOLLOW | O_CLOEXEC`. Read occurs in bounded
  64 KiB chunks. Device/inode/length/mtime/ctime are compared before/after,
  and the calculated SHA-256 must match the claimed selected role digest.
- A model with several safetensors shards must be assembled into a **complete
  canonical artifact pack**, or gain a separately qualified shard-aware
  package owner. A digest of an index file alone is **insufficient**.
  This verifier does not parse/sandbox Hugging Face remote code or the
  safetensors format.
- On other platforms it fails closed with `UnsupportedPlatform`, rather than
  claiming Windows parity without an audited, no-follow, host-ACL adapter.
- A verified read produces private, non-cloneable
  `VerifiedStemCasArtifactsV1` binding Stem identity, Generation,
  Authority Epoch, exact four-role digests and measured role byte counts.
  The output explicitly has `DENY_ALL` authority.

## Signed Worker integration

`VerifiedStemFeatureDispatchV1` includes
`verified_artifacts: &VerifiedStemCasArtifactsV1`.
The public `run_verified_stem_feature_receipt_v1` refuses to enter the
final-use effect unless the proof binds the exact selected Stem model,
Generation, authority epoch and four-role artifact digests. Even when it
matches, the **independent FinalUseAuthority** must still verify the existing
non-cloneable signed token and exact request tuple, while holding its
revocation effect fence. Neither receipt is replaced by a bare hash.

The proof **does not** demonstrate that `ModelDriver` actually decoded or
executed those particular tensors, that it used an official Jina adapter, or
that bytes have remained unchanged after verification. The real loader must
consume the exact, immutable, already-verified pack(s) under the same owned
lifecycle; a trusted model-load observer/signature and generation-aware
revocation are mandatory for production.

## Unit and workflow coverage

```sh
cd codex-rs
cargo +1.95.0 fmt --all -- --check
cargo +1.95.0 test --locked -p codex-hepta-infer-worker-host --lib 'stem_artifact_cas::tests::'
cargo +1.95.0 test --locked -p codex-hepta-infer-worker-host --lib 'model_worker::tests::'
cargo +1.95.0 clippy --locked -p codex-hepta-infer-worker-host --all-targets -- -D warnings
```

Physical test fixtures write **real bytes**, not mock metadata. Tests cover
valid owned role files, observed byte sizes, different generation/epoch,
missing blobs, wrong content digest, symlinks, insecure root permissions,
oversize blobs, group/world writable blobs, hardlinks and invalid selected
digests. Signed Worker tests exercise the positive path using actual CAS
files, and reject a signed request when the provided proof belongs to a
different Stem generation. Both tests are independent of external weights
and explicitly **do not report production inference speed or accuracy**.

Before any promotion: pinned Jina revision/licensing approval; true weight
and tokenizer acquisition; executable/loader identity; signed ArtifactLoad
receipt; immutable byte-to-tensor provenance; secure source ownership;
protected final-use issuer + trusted clock/frontier; checkpoint CAS/WAL and
unclean crash reconciliation; real future NDU effects and target-host
64/256/1024/4096 Cell CPU/RSS/throughput/p95/p99.
