# cognitive.types wire fuzzing

This harness feeds arbitrary bytes to every registered HNMF V1 wire decoder in
`codex-hepta-cognitive-types`. A fuzz input is never treated as an admitted
contract merely because deserialization succeeds: `decode_wire_v1` also
requires the exact schema/version/contract identity, canonical JSON bytes,
per-contract encoded-size limits and contract validation.

Build the harness with:

```sh
cargo check --manifest-path codex-rs/hepta-cognitive-types/fuzz/Cargo.toml --all-targets
```

Run bounded local fuzz campaigns with cargo-fuzz, for example:

```sh
cargo fuzz run --manifest-path codex-rs/hepta-cognitive-types/fuzz/Cargo.toml decode_contracts -- -runs=100000
```

The CI qualification compiles this harness and runs deterministic contract,
property and cross-language golden-vector tests. It does not claim that a
finite fuzz campaign proves the absence of parser defects.
