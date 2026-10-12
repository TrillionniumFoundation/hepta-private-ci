# Starlark BLAKE3 compatibility patch

Source: crates.io `starlark 0.14.2`; all Rust source remains unchanged.
Only the normalized manifest's exact BLAKE3 dependency changes from `=1.8.2`
to `=1.8.7`. The upstream original manifest inherits this from its workspace,
so it is retained as published for provenance.

Matrix SDK 0.19.1 store encryption requires BLAKE3 >=1.8.7, which cannot
resolve against Starlark's exact 1.8.2 requirement. Updating this patch-level
hash implementation retains Matrix's upstream security dependency graph.
Starlark's usage is its Blake3StrongHasher wrapper around the stable Hasher,
update and finalize APIs; no interpreter or authorization logic is changed.

The upgrade qualification must include codex-execpolicy tests and known-answer
hash behavior. This is not authorization to change any policy semantics.
