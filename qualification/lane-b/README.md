# Lane B runtime source closure

This directory contains the closed-world, repository-controlled truth for `LANE-B-RUNTIME` at immutable source base `f278a89eea18fccb6d37b876aa5679863a64139d`. Exact candidate identity is always derived from Git HEAD by the verifier.

## Authoritative files

- `LANE_B_IMPLEMENTATION_TRUTH.json` — closed index of eleven modules and 39 design operations.
- `docs/modules/<module>/IMPLEMENTATION_MAP.json` — authoritative module roots, ownership, owner entrypoints, delegated callees, tests, source semantics and external evidence gates.
- `LANE_B_NATIVE_CLOSURE.md` — generated human projection of the eleven module maps.
- `TEST_TRACEABILITY.json` — generated operation-to-test/workflow projection.
- `LANE_B_CANDIDATE_MANIFEST.json` — immutable source base and allowed candidate paths.
- `docs/readiness/LANE_B_RUNTIME_COMPOSITION.md` — composition, identity, failure, shutdown and rollback semantics.

## Validation

```sh
python3 scripts/hepta-lane-b-truth.py self-test
python3 -m unittest scripts/test_hepta_lane_b_truth.py
python3 scripts/hepta-lane-b-truth.py verify
```

`generate` rewrites only the human closure and test traceability projections; CI uses `verify` and rejects drift:

```sh
python3 scripts/hepta-lane-b-truth.py generate
```

The exact-head and deterministic synthetic-merge workflow also runs the focused Rust and Node suites.

## Claim boundary

Repository-controlled documentation, operation inventory, source mapping and bounded source implementation can be closed here. Real model/provider execution, real Servo or Matrix effects, deployed Web/native artifacts, target-host measurements, hardware evidence, owner consent, independent acceptance, selection, promotion and release cannot be self-issued by this repository and remain explicit external gates.
