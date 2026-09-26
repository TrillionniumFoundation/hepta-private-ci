# platform.types Deep Qualification V1

## Status and claim boundary

This document defines repository-controlled qualification for the authority-free
`platform.types` contract surface. It does not grant runtime authority,
production activation, external acceptance, promotion, or release. Committed
module documents describe content and policy; exact candidate identity is added
only by CI-generated candidate bundles and receipts.

The deep qualification lane treats a pull-request source head and its
deterministic synthetic merge as different candidates. Their receipts are not
interchangeable. A diagnostic record may be retained for a failed candidate,
but only a run in which every required check succeeds may emit an authoritative
qualification receipt.

## Generated public implementation map

The committed public API inventory is generated from every exact `pub use`
export in `codex-rs/hepta-types/src/lib.rs`. Each qualification run generates an
exact-candidate implementation-map artifact from that inventory and assigns
every public export to exactly one public implementation operation and source
path. The artifact is candidate-bound rather than copied forward with a stale
commit identifier.

Run:

```bash
python3 scripts/platform_types_public_api.py --write
python3 scripts/platform_types_implementation_map.py \
  --output .hepta-evidence/platform-types-generated-map.json
```

Normal CI verifies the inventory without `--write`, validates the detailed map,
and writes the generated projection only into exact-candidate evidence. The
detailed `IMPLEMENTATION_MAP.json` remains the richer
source/test/consumer/non-claim record; the generated artifact is the
closed-world public-surface projection used to prove that a new export cannot
silently bypass operation ownership.

## JSON transport and HPTC semantic commitment

The three owned manifest protocols use two deliberately separate layers:

1. **Strict JSON transport** validates the closed field set, canonical decimal
   representation for 64-bit integers, enum domains, bounds, and rejection
   policy. JSON object order has no semantic meaning.
2. **HPTC V1 semantic commitment** projects validated values into a typed,
   domain-separated field map and hashes that canonical encoding. Transport
   bytes are not themselves the semantic digest.

`MANIFEST_V1_CONFORMANCE.json` carries accepted and rejected JSON vectors plus
expected HPTC digests. Independent Python and JavaScript oracles must agree with
Rust consumer tests. Unknown fields, missing semantic fields, invalid ranges,
invalid timestamps, unsupported discriminators, and precision-unsafe integers
are rejected.

## Deterministic property and bounded-fuzz checks

`scripts/platform_types_property_checks.py` performs replayable checks over the
manifest protocol surface:

- every golden vector retains its committed HPTC digest;
- reversing JSON object order leaves the digest unchanged;
- removing every semantic leaf is rejected;
- changing every semantic leaf to another valid value changes the digest;
- unknown fields and unsupported discriminators are rejected;
- every committed invalid vector is rejected; and
- a fixed-seed bounded mutation campaign exercises hundreds of additional valid
  semantic mutations and requires digest separation.

This lane is deterministic mutation fuzzing, not a claim of exhaustive
coverage-guided fuzzing. New protocol families must add equivalent mutation
coverage before entering the public inventory.

## Toolchain gates

The crate declares Rust **1.95** as its minimum supported Rust version. Deep
qualification checks the exact candidate with:

- `cargo +1.95.0 check --locked --package codex-hepta-types --all-targets`;
- `cargo +1.95.0 test --locked --package codex-hepta-types`; and
- `cargo +nightly-2026-09-20 miri test --locked --package codex-hepta-types --lib`.

The Miri nightly is pinned so that a receipt identifies a reproducible
interpreter/toolchain pair. Updating it requires a reviewed source change; CI
does not float to an unrecorded nightly.

## Exact-candidate document bundle

`scripts/platform_types_candidate_bundle.py render` produces a CI artifact in
which every platform.types technical document is wrapped with:

- candidate kind;
- exact candidate commit and tree;
- originating source commit and, for synthetic merges, base commit and PR;
- source SHA-256 and byte length; and
- an explicit non-authoritative/non-activation claim boundary.

The bundle manifest also hashes source, protocol, verifier, workflow, and
qualification anchors. This keeps committed documentation content-derived while
still making the executed evidence exact-SHA and byte-addressed.

## Receipts and failure evidence

For both source-head and synthetic-merge candidates, CI retains diagnostics and
command logs even when a required check fails. Diagnostics are explicitly
non-authoritative. A deep qualification receipt is emitted only after all of
these outcomes are successful:

1. generated inventory/map and protocol property verification;
2. declared MSRV check;
3. native test suite;
4. pinned Miri suite; and
5. exact-candidate document-bundle rendering.

The receipt hashes the property report, bundle manifest, and command logs. It
preserves the module's non-claims: no product execution, activation, external
acceptance, promotion, or release follows from a green source qualification.
