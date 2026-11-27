# Maintained paste API adapter

This is repository-owned adapter code, not a vendored copy or renamed release of
the archived paste implementation. It contains only reexports of pastey's three
public procedural macros: paste, item, and expr.

[The paste advisory](https://rustsec.org/advisories/RUSTSEC-2024-0436.html) names
pastey as a maintained drop-in alternative. Keeping the dependency package name
and version satisfies existing Starlark and V8 manifests while directing every
macro invocation to the real pastey 0.2.3 implementation. No old paste expansion
code is present; no advisory ignore, package skip, or feature removal is used.

This local package has its own source identity and is reviewed as first-party
adapter code. The maintained registry dependency remains visible to cargo-deny.
Tests exercise Starlark's cross-crate item reexport, V8-style generated typed-array
names, case conversions, lifetime construction, and all three entry points.

Replace consumers with direct pastey dependencies when those upstream crates
publish that migration. V8's source, generated bindings, native version, compiler
options, and release archive bindings are unchanged.

## Repository formatting provenance

`just fmt` made no Rust source changes in this directory.
The source metadata records both pre-format and final hashes. Targeted tests
were run before the required final fix/format step, in the order specified by
the repository instructions.
