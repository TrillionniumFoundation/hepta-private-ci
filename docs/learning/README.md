# Hepta adaptive learning specifications

This directory contains the canonical machine registries and implementation-level specifications for Hepta adaptive and longitudinal intelligence. The global development authority remains [`../DEVELOPMENT.md`](../DEVELOPMENT.md). Documentation closure does not imply source implementation, activation, efficacy, acceptance, promotion or release.

## Read order

1. [`ALGORITHM_SPECS.json`](ALGORITHM_SPECS.json) — closed-world coverage, exact Git blob identities and mandatory closure gates.
2. [`PAPER_TRACEABILITY.json`](PAPER_TRACEABILITY.json) — semantic claim scope, exact locators, non-claims and Hepta-extension boundaries.
3. [`PAPER_EVIDENCE_BINDINGS.json`](PAPER_EVIDENCE_BINDINGS.json) — pinned independent evidence commit, manifest/tree/blob identities and byte-replay policy. This file, not verifier constants, establishes external source-byte identity.
4. [`ALGORITHM_STATUS.md`](ALGORITHM_STATUS.md) — generated coverage and truthful capability posture.
5. [`NDU_FBSDE_SPEC.md`](NDU_FBSDE_SPEC.md) — forward-backward preference/recursive-utility model, deterministic baseline, well-posedness, hierarchy and thresholds.
6. [`HOLDER_BELLMAN_SPEC.md`](HOLDER_BELLMAN_SPEC.md) — Hölder applicability certificate, smooth/jump/hard partition, sensor geometry, anisotropic operator and error budget.
7. [`CAUSAL_LONGITUDINAL_SPEC.md`](CAUSAL_LONGITUDINAL_SPEC.md) — complete candidate sets, propensity, independent outcomes, OPE, future-time retention and unlearning.
8. [`NEURAL_BIOMIMICRY_SPEC.md`](NEURAL_BIOMIMICRY_SPEC.md) — temporal state, sparse competition, inhibition, homeostasis, eligibility, replay, lesion and ablation.
9. [`SELF_ITERATION_SPEC.md`](SELF_ITERATION_SPEC.md) — bounded mutation grammar, sandbox, no-change baseline, independent decisions, pull-request proposal and rollback.
10. [`REFERENCE_CONFORMANCE_SPEC.md`](REFERENCE_CONFORMANCE_SPEC.md) — fixed-point, randomness, golden vectors, fault, performance, exact-source and synthetic-merge conformance.
11. Existing machine sources: [`LEARNING_SYSTEM.json`](LEARNING_SYSTEM.json), [`EXPERIMENTS.json`](EXPERIMENTS.json) and [`ARTIFACTS.json`](ARTIFACTS.json).

## Validation

```bash
python3 scripts/hepta-paper-evidence.py self-test
python3 scripts/hepta-paper-evidence.py verify
python3 scripts/hepta-algorithm-docs.py self-test
python3 scripts/hepta-algorithm-docs.py verify-sources
python3 scripts/hepta-algorithm-docs.py generate-status --check
python3 scripts/hepta-algorithm-docs.py verify
```

The evidence verifier reads the exact pinned orphan evidence commit, checks its branch head, parent, tree and manifest blob, recomputes every source byte length and SHA-256, recomputes every abstract sentence digest and proves every semantic claim resolves exactly once. Discovery downloads and same-file constants cannot substitute for those bytes.

## Implementation execution overlays

The adaptive mathematics above is paired with coding-level state, concurrency, evaluation and self-iteration semantics in [`../readiness/README.md`](../readiness/README.md), especially `NDU_SYSTEM_EXECUTION.md`, `NEURON_RUNTIME_EXECUTION.md`, `LEARNING_EVALUATION_EXECUTION.md` and `SELF_ITERATION_EXECUTION.md`.
