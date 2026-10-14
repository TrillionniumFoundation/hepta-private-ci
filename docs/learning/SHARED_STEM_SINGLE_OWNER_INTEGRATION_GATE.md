# One-owner shared Stem data plane: release integration gate

**Status: implementation-only research; NOT an operator acceptance or production authority.**

## Ownership decision

Reuse the existing `StemFeatureRefV1` / `StemAccessContextV1` from
`hepta-infer-core/src/stem_feature_binding.rs` as the canonical typed
feature identity. That contract explicitly carries Principal, Scope, Stem
generation, authority epoch, lease expiration, revocation claim, input digest,
model/tokenizer/preprocessor/projection digests and selected Head requirements.

The `SharedStemQ24BufferV1` on this branch is only an immutable
`Arc<[i64]>` *storage vehicle*. It does not install a cache service,
authorize a request, register a new final-use owner or supersede the
existing signed authority pipeline. Its constructor checks bounded Q24
content against the source descriptor; the descriptor itself remains
unverified until authenticated independently.

Do **not** deploy the simplified independent Snapshot authority tuple in
#1918 as a second source of access permissions. The borrow/view storage
optimization must eventually converge into this single, richer contract.

## Hot path and exact efficiency hypothesis

1. Independently authenticated Encoder owner resolves source and weights.
2. Q24 vector (1–512 dimensions) is checked exactly once against the source
   feature digest when constructing the immutable buffer. The safe Rust API
   does not expose mutable access to the Arc allocation.
3. Multiple compatible Cell Heads call `borrow_for_head`, each with freshly
   resolved owner claims. Principal, Scope, epoch, generation, lease expiry,
   revocation and selected Head compatibility remain checked on *each call*.
4. Only the immutable-buffer path may skip rehashing Q24 contents, because
   its complete content was verified at construction. The ordinary
   `borrow_stem_feature_request_v1` path for potentially mutable borrowed
   slices **always** hashes the actual vector on each use.
5. The immutable buffer's `materialize_owned_for_head` revalidates the
   supplied current Principal/Scope/Epoch/Lease/Revocation/Head claims and
   then allocates the **one Vec required** by existing V1 serialization,
   without rehashing its immutable bytes. For an arbitrary caller-held
   borrowed view, `materialize_owned_after_refresh` independently rehashes
   before producing owned V1. Both retain identical V1 request/digest bytes.
   No end-to-end zero-copy or latency claim follows.
6. A separate independently signed Final-use / Worker / runtime dispatch
   receipt is required at the actual execution boundary. An Arc, feature
   digest, or caller-supplied `StemAccessContextV1` is not evidence of
   issuer custody, revocation freshness or permission to execute.

For `C` Cell Heads seeing one identical `D`-dimensional frozen feature,
when each Head uses the immutable-buffer borrow or owned-materialization
path, the expected input-content hashing work changes from approximately
`O(C * D)` in repeated direct slice validation to `O(D)` for the single
immutable-buffer construction. **This is an algorithmic cost claim only**:
the implementation still performs `O(C)` authorization-claim/Head checks,
digest construction, selected Head work and downstream execution. Actual
p95/p99 throughput and RSS savings have NOT been measured.

## Explicit integration and acceptance sequence

| Gate | Required receipt | Current status |
| --- | --- | --- |
| C0 | Same SHA rustfmt, Cargo check/test, strict Clippy for core and reverse consumers | OPEN |
| C1 | Compile and compare owned V1 replay/digest against borrowed view for bounded 1/384/512D features and all terminal statuses | OPEN |
| C2 | Independent trust owner attests Principal/Scope/Epoch/Lease/Generation/Revocation and signed final-use on dispatch | OPEN |
| C3 | Reconcile #1918 buffer into the single Stem API; **do not combine two authorizers** | OPEN |
| C4 | Rebase isolated #1958 Worker Vec-move onto the more mature Worker Bridge/Artifact CAS implementation, retaining all other security checks | OPEN |
| C5 | Count actual Encoder forward calls/rows, feature hashing passes, Vec allocations, Q24 checkpoint/WAL costs and backend microbatch execution | OPEN |
| C6 | Target-host 64/256/1024/4096 Cell p50/p95/p99, CPU/GPU/RSS and restart/lease/revoke/CAS/CNS fault-recovery | OPEN |
| C7 | Real frozen 421M/No-change vs mmBERT-small/Granite/ModernBERT on identical approved tasks, training compute and future NDU | OPEN |

Suggested Rust gate commands, run at the **exact candidate source commit**
with the repository's locked toolchain and verified dependencies:

```sh
cargo test --locked --manifest-path codex-rs/Cargo.toml -p codex-hepta-infer-core
cargo test --locked --manifest-path codex-rs/Cargo.toml -p codex-hepta-infer-worker-host
cargo clippy --locked --manifest-path codex-rs/Cargo.toml \
  -p codex-hepta-infer-core -p codex-hepta-infer-worker-host \
  --all-targets -- -D warnings
cargo fmt --manifest-path codex-rs/Cargo.toml --all -- --check
```

CI success for another branch/commit cannot be carried over to this
commit. No synthetic fixture or self-reported digest upgrades these gates.

## External evidence boundary

The completed public mmBERT-small GitHub study from run
`38546717991` (source `4133d6ac5bd3f8d4200c56fffb09e6aba004a084`)
is useful for confirming that an actual pretrained Encoder and multiple
trainable Heads have been run on public AG News records. Its 32-case local
parent_no_change control scored 26/32, versus the gated Head's 22/32.
These remain public **research** measurements, not a deployed no-change
or matched-compute causal experiment and not a production admission.
