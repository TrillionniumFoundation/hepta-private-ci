# CTRL dependency proposal: exact bindgen/Syn resolution (2026-11-10)

This draft is stacked **only** on [#5655](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5655), original head `d60218f6866ea282e961af525306bdb89ffd6c80`. It changes the disposable qualification workflow and its source allowlist, not product Cargo/Bazel locks, production dependencies, security exemptions or runtime authority.

## Original terminal evidence

The original Actions [run 42776841937, job 129697224552](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42776841937/job/129697224552) **completed failure**, not queued. Its [immutable 496941-byte artifact](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42776841937/artifacts/13747333102) contains the actual generated Cargo.lock, Bazel lock, stage logs and result JSON.

In that result, PREPARE/RESOLVE/BAZEL/POLICY/DENY succeeded; CONSUMERS failed while compiling bindgen 0.73.2 with `E0277`, `syn::file::File: syn::parse_quote::ParseQuote`. The original generated Cargo.lock SHA-256 is:

`c3d1fec8c1291a9689d91c6fda6b7f593e95d1416730b00decf43e9dd31166a0`

It includes bindgen 0.73.2's one `syn 3.0.9` dependency while prettyplease 0.2.37 resolves `syn 2.0.119`. The reviewed [#5771](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5771) and [#5755](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5755) joint-graph work independently identified the **identical preimage**, not merely the same error string.

## Bounded proposal, not adoption

Reuse the reviewed one-edge substitution in the disposable generated Cargo.lock only: bindgen's `syn 3.0.9` edge becomes `syn 2.0.119`; Syn 3 remains available to unrelated macros. The helper accepts only that exact full 421003-byte lock SHA-256, verifies exactly one expected bindgen stanza and edge, and requires the exact reviewed postimage SHA-256:

`98b3767c6e74bf6eeb5894db760259dbc400cbfd0685af8ad915c92d25408d69`

Parsed TOML comparisons require every other package, checksum and dependency to remain unchanged. The updated workflow requires fresh `cargo metadata --locked --all-features`, resolves actual bindgen and prettyplease edges by package ID, and keeps mandatory Bazel lock regeneration, scoped consumer tests, no-suppression cargo-deny, external artifacts and failed-stage receipts. No original job is replayed or relabelled.

## Qualification boundary

This is **a new candidate for validation**, not evidence that its new GitHub Actions run passed. Do not transfer the successful original lock/Bazel/deny stages to the modified source without fresh logs. SQLCipher migration, legacy-init and custom rmcp OAuth/DNS/HTTP limits still require distinct owner and adversarial tests. No producer, stored label or independent policy benefit is established. Full task-specific costs remain unknown; the 37 reserved CTRL future sources remain sealed. Status: **HOLD_NO_GO / NoUpdate / no production activation**.

## Inherited repository spelling gate

The original source-head blocking CI also fails on two pre-existing codespell false positives in `METHOD.zh-CN.md` (the actual `people.bu.edu` domain and BAGEL `MoT` acronym). Reuse the **exact two-line postimage** from CTRL #5642 (`90dd73c9125a8170e3dcc240bf20ebba40fce29d`), which is derived from the precise original base blob `9b49597ff6057670b7af603c23e293ee8e649c5d`. No URL, analysis or other text changes. This shared spelling-only integration is distinct from dependency resolution, and cannot qualify the full blocking CI by itself.
