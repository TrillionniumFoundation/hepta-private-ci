# Native Compute Cell V6 — research-only CPU kernel evidence

**Owner lineage:** stacked on the fixed-ABI `hepta-compiled-use` V5 shadow/data-only work (PR #2449). This creates neither a new product executor nor permission to invoke operating-system effects.

## Concrete experiment

`src/native_compute.rs` contains an **actually compiled native Rust Q24 16-lane dot-product**. A literal fixed 256-byte `HNC1` frame binds immutable logical task digest, worker generation, sequence, specific built-in kernel identity, bounded Q24 feature/weight values and an integrity checksum. The result uses a fixed 64-byte `HNR1` frame bound to the entire request and computed output. Numeric conversion is signed, nearest/ties-to-even; both request and output reject malformed or replayed identities. All observations are `DENY_ALL`.

`examples/native_compute_paired.rs` runs the **same exact 16-lane original arithmetic, same source request bytes, same verifier and response verification** in two physical execution modes: (1) the caller process and (2) a **separate native CPU process** connected through a private Unix socket. It reverses the order across two repetitions of each arm and separately measures 16 warmups, 64 or 1024 measured calls. It counts child setup separately and records two p50/p95/p99 distributions per mode, always retaining every individual negative/failed mode instead of manufacturing a gain.

This experiment measures the value of avoiding an OS process-hop for one small, deterministic CPU compute call. It **does not** measure MCP, an LLM, a GUI/browser effect, GPU launches, JIT, external code loading, Wasm, full Computer Use or energy. The same workload verification only proves internal consistency; the task digest and socket path are not independent peer/host authentication. No source result is allowed to claim production authorization.

`native_compute_receipt.py` independently reopens both original JSON rows, rejects duplicate keys/nonfinite values/extra fields/wrong controls/symlinks/oversize, recounts all required repetitions, and emits an exact source and architecture bound non-authorizing result. Its Python fixture tests do not execute the real Rust kernel.

## Reproduce on an authorized Rust Unix host

```bash
python3 -m unittest discover -s qualification/native-cell-v1 -p 'test_native_compute_receipt.py' -v
cargo test --locked --manifest-path codex-rs/Cargo.toml -p codex-hepta-compiled-use
cargo test --locked --manifest-path codex-rs/Cargo.toml -p codex-hepta-compiled-use --example native_compute_paired
cargo clippy --locked --manifest-path codex-rs/Cargo.toml -p codex-hepta-compiled-use --all-targets -- -D warnings
cargo fmt --manifest-path codex-rs/hepta-compiled-use/Cargo.toml -- --check
cargo run --locked --manifest-path codex-rs/Cargo.toml -p codex-hepta-compiled-use --example native_compute_paired -- --smoke
cargo run --locked --manifest-path codex-rs/Cargo.toml -p codex-hepta-compiled-use --example native_compute_paired
```

The dedicated source+merge pull-request workflow runs original CPU workloads separately on x64 and ARM64, checks exact HEAD and independently audits source-bound original outputs. It must finish on the **exact new HEAD** before physical numbers can be claimed. One independent publisher/host signer, true OS owner/FinalUse, UI readback, real MCP and native Computer Use matched trials, GPU device workloads, 64–4096 real Cells, actual error/restart/revocation results and full task cost remain **unproven and unwaived**.

**DRAFT / SHADOW_ONLY / DENY_ALL / no production Cell Split, no model promotion, no external effects.**
