# Hepta-Neuron Multimodal Memory Fabric

This directory is the executable qualification package for the Hepta-Neuron Multimodal Memory Fabric (HNMF). It closes the implementation-design blockers identified in the V8 audit without creating a second execution spine or granting production authority.

Read in this order:

1. [`HNMF.json`](HNMF.json) — machine-readable architecture, bounds, protocols, work packages, module ownership, and claim posture.
2. [`TECHNICAL.md`](TECHNICAL.md) — normative engineering design, fixed-point dynamics, write/recall/consolidation flows, failure semantics, and migration plan.
3. [`GAPS.json`](GAPS.json) — exact blocker-to-evidence closure ledger.
4. [`MIGRATION.md`](MIGRATION.md) — bounded migration from the current text/KG memory implementation.
5. [`../../qualification/hnmf-reference/README.md`](../../qualification/hnmf-reference/README.md) — deterministic, no-network, no-provider, no-production-authority reference runtime.

Verification:

```bash
python3 scripts/hepta-hnmf.py verify
cargo fmt --manifest-path qualification/hnmf-reference/Cargo.toml -- --check
cargo check --manifest-path qualification/hnmf-reference/Cargo.toml --all-targets
cargo test --manifest-path qualification/hnmf-reference/Cargo.toml
```

Passing these checks proves only that the HNMF contracts, algorithms, bounds, negative authority posture, and deterministic reference behavior are internally closed at the exact candidate. It does not prove production activation, longitudinal efficacy, functional biomimicry, operator acceptance, promotion, or release.
