# P11: SHA-pinned rules_rs zlib mirror convergence (research stack only)

**DRAFT / SHADOW_ONLY / DENY_ALL / HOLD_NO_GO**.

Parent: P10 [#3001](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/3001)
at exact `d74578b147c36257b67254b0319b062a68c21a49`. This stacks on P9 #2999 and P8 #2995.

The preexisting `rules_rs` toolchain patch used an Ubuntu snapshot URL
for zlib packages and repeatedly encountered HTTP 503 in Linux CI.
This commit transplants **exactly** the existing PR #2991 reviewed file blob
`d659e88e1815b5eceea7286b7e71c9f49ae22448`; it keeps the original immutable Ubuntu snapshot as the
first URL, official Ubuntu archive/ports as the second URL, and **both
original package SHA256 digests unchanged**. It adds no integrity waiver,
no alternate package bytes and no CI skip.

Only `patches/rules_rs_build_script_deps_annotation.patch` changes executable configuration.
This document triggers the existing shared-Stem shadow workflow against the
exact P11 SHA, so a prior P10 pass cannot be reused. Required further gates:
Bazel patch application, lockfile identity and repeatability, Linux/macOS/
Windows Bazel Clippy/test/release, exact-head blocking-ci, architecture, V8,
independent RustSec cleanup and actual teacher/held-out/GPU qualification.

The planned models and Cell boundary remain untouched: 421M frozen cognition
control, EmbeddingGemma 2 perception/Memory teacher, T5Gemma 2 Encoder
competitor, Hepta 150M/300M untrained student blueprints; each Cell only
Gate, lightweight Adapter, Task/Action/Value Head, bounded Local State and
external Memory references. Nothing is promoted or merged to main.
