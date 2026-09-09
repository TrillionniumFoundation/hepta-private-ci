# Lane B runtime implementation closure

This directory is the repository-controlled implementation-truth companion for `LANE-B-RUNTIME`.

## Authoritative files

- `LANE_B_IMPLEMENTATION_TRUTH.json` — exact eleven-module closed set, maturity, operation-to-source mappings, nonclaims and residual gaps.
- `LANE_B_NATIVE_CLOSURE.md` — human-readable module-by-module implementation review and closure criteria.
- `../../docs/readiness/LANE_B_RUNTIME_COMPOSITION.md` — process topology, identity tuple, startup, execution, cancellation, fault, recovery and rollback semantics.

## Validation

Run:

```sh
python3 scripts/hepta-lane-b-truth.py self-test
python3 -m unittest scripts/test_hepta_lane_b_truth.py
python3 scripts/hepta-lane-b-truth.py verify
python3 scripts/hepta-lane-b-docs.py verify
```

`.github/workflows/hepta-lane-b-truth.yml` executes these checks on the exact source head and on a deterministic synthetic merge candidate.

## Claim boundary

Repository-controlled truth and documentation can prove source identity, declared mappings and explicit gaps. They cannot self-issue production execution, external effects, deployment, independent acceptance, hardware safety, future-window efficacy, promotion or release evidence.
