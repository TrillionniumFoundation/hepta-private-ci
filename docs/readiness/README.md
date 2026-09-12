# Hepta implementation-readiness closure

This directory closes the registered pre-coding documentation requirements for the Hepta V8 architecture. It is a canonical subordinate specification layer under `docs/DEVELOPMENT.md`; it does not claim source implementation, runtime activation, longitudinal efficacy, biological equivalence, physical safety, autonomous propagation, acceptance, selection, merge, promotion or release.

## Read order

1. [`READINESS.json`](READINESS.json) — closed-world document, module, lane, integration and assimilation bindings.
2. [`STATUS_MODEL.json`](STATUS_MODEL.json) — canonical `specification_closed`, `implementation_closed` and `external_evidence_closed` vocabulary and projections.
3. [`PROTOCOLS.json`](PROTOCOLS.json) — 31 implementation-level typed protocols.
4. [`GAPS.json`](GAPS.json) — 54 bounded documentation requirements and separately named external gates.
5. [`SOURCE_BASELINE_AND_BRANCH_POLICY.md`](SOURCE_BASELINE_AND_BRANCH_POLICY.md) — exact source, branch purpose, merge identity and base-drift rules.
6. [`OBJECTIVE_COMPILER_EXECUTION.md`](OBJECTIVE_COMPILER_EXECUTION.md) — bounded objective grammar, precedence, canonicalization and fixtures.
7. [`NDU_SYSTEM_EXECUTION.md`](NDU_SYSTEM_EXECUTION.md) — cross-organ utility, Pareto policy, deterministic hierarchy and convergence.
8. [`NEURON_RUNTIME_EXECUTION.md`](NEURON_RUNTIME_EXECUTION.md) — state layout, tick ordering, checkpointing, performance and ablations.
9. [`LEARNING_EVALUATION_EXECUTION.md`](LEARNING_EVALUATION_EXECUTION.md) — preregistration, support, outcomes, OPE, future windows, retention and unlearning.
10. [`SELF_ITERATION_EXECUTION.md`](SELF_ITERATION_EXECUTION.md) — mutation grammar, protected surfaces, sandbox, lineage and rollback.
11. [`EMBODIED_RUNTIME_EXECUTION.md`](EMBODIED_RUNTIME_EXECUTION.md) — timing, calibration, body generation, reflex, actuation and HIL semantics.
12. [`EXTERNAL_SYSTEM_ASSIMILATION.md`](EXTERNAL_SYSTEM_ASSIMILATION.md) — explicitly authorized Debian/POSIX discovery, wrapping, migration, qualification and federation.
13. [`PARALLEL_DEVELOPMENT.md`](PARALLEL_DEVELOPMENT.md) — all-40-module lane plan, execution matrix and integration checkpoints.
14. [`../../qualification/module-execution-dossiers/TECHNICAL.md`](../../qualification/module-execution-dossiers/TECHNICAL.md) — all-module entrypoint, persistence, fault, performance, NDU, evolution, embodiment and assimilation semantics.
15. [`../../qualification/module-execution-dossiers/MODULE_DOSSIERS.json`](../../qualification/module-execution-dossiers/MODULE_DOSSIERS.json) — exact execution dossier for every registered module.
16. [`STATUS.md`](STATUS.md) — generated registered readiness status.
17. [`../../qualification/module-execution-dossiers/STATUS.md`](../../qualification/module-execution-dossiers/STATUS.md) — generated execution-depth projection.
18. [`../../qualification/module-execution-dossiers/README.md`](../../qualification/module-execution-dossiers/README.md) — forty module-specific design index and detailed implementation reading sequence.
19. [`../../qualification/module-execution-dossiers/DETAILS.json`](../../qualification/module-execution-dossiers/DETAILS.json) — exact detail hashes, existing guide/root/package references and primary lanes.
20. [`../../qualification/module-execution-dossiers/EXECUTION_SEMANTICS.md`](../../qualification/module-execution-dossiers/EXECUTION_SEMANTICS.md) — objective conflict complexity, conditional covariance, sequential evaluation, numerical profiles, thresholds and handoff.
21. [`../../qualification/module-execution-dossiers/STATE_HANDOFF.schema.json`](../../qualification/module-execution-dossiers/STATE_HANDOFF.schema.json) — qualification handoff schema; native production admission is separate.
22. [`../../qualification/module-execution-dossiers/DETAIL_GAPS.json`](../../qualification/module-execution-dossiers/DETAIL_GAPS.json) — bounded dispositions and unresolved integration/external gates.
23. [`../../qualification/module-execution-dossiers/IMPLEMENTATION_CONTRACTS.md`](../../qualification/module-execution-dossiers/IMPLEMENTATION_CONTRACTS.md) — concrete coding contracts, true native evidence and final-gate ordering.
24. [`../../qualification/module-execution-dossiers/IMPLEMENTATION_PROFILES.json`](../../qualification/module-execution-dossiers/IMPLEMENTATION_PROFILES.json) — all forty module API, encoding, concurrency/recovery, algorithm and acceptance profiles.
25. [`../../qualification/module-execution-dossiers/IMPLEMENTATION_COMPLETION.json`](../../qualification/module-execution-dossiers/IMPLEMENTATION_COMPLETION.json) — sixteen further implementation-design dispositions, their documents and remaining evidence.

## Validation

`PROTOCOLS.json` uses a closed, recursively validated field-schema grammar. Every
enum declares its complete allowed-value set; every bounded array declares item
schema, count limits and uniqueness semantics; fixed-point vectors bind Q24 or Q32
numeric representation plus a protocol-specific variable-length bound (utility at
most 8 elements, risk, resource and uncertainty at most 32 and neuron features at
most 512), rather than a fixed cardinality. Every bounded object declares its
ordered properties, required-property count and an explicit
`additionalProperties: false` policy. The registry has 46 recursively declared
bounded-object schema nodes; `self-test` uses one separate positive fixture and
two hostile variants for a missing or permissive additional-properties policy.
Nested schemas use the same grammar. Missing or permissive additional-property
policies, unknown schema keys, duplicate names or values, invalid bounds and a
nested byte limit wider than its parent are rejected. Enum choices remain under
the closed `values` key.

These schemas define admission bytes only; they do not activate a caller or grant
runtime, external-effect or release authority.

```bash
python3 scripts/hepta-readiness.py self-test
python3 scripts/hepta-readiness.py generate-status --check
python3 scripts/hepta-readiness.py verify
python3 scripts/hepta-implementation-dossiers.py self-test
python3 scripts/hepta-implementation-dossiers.py generate-status --check
python3 scripts/hepta-implementation-dossiers.py verify
python3 scripts/hepta-technical-closure.py self-test
python3 scripts/hepta-technical-closure.py verify
python3 qualification/module-execution-dossiers/implementation_contracts.py self-test
python3 qualification/module-execution-dossiers/implementation_contracts.py verify-repository
python3 scripts/hepta-docs.py verify
```

The first implementation slice remains deterministic and read-only with respect to user-domain/external effects; necessary authorized learning-ledger writes are explicitly recorded and are not described as zero I/O. Adaptive, structural, physical and external-system changes remain candidates until separate evidence and decisions exist. The nine `RDY-EXT-*` capability and evidence gates remain external and non-self-certifiable.

## Detailed-design interpretation and coding gates

Read the stable module guide, Section 16 readiness overlay, existing detail and matching implementation profile together. Proposed operation names must map to actual native symbols and consumers within an existing work package. The original 160 named acceptance cases are test designs, not pass receipts. Five exact source observations in `NATIVE_BINDINGS.json` are neither forty complete native mappings nor production-call evidence.

General stochastic NDU regression now has one corrected authoritative formula in [`../learning/NDU_FBSDE_SPEC.md`](../learning/NDU_FBSDE_SPEC.md): centered conditional moments solve `Z Sigma = B`. The time-only simplification needs its covariance assumption. This document correction does not reinterpret old artifact bytes; any new coefficient profile/wire field requires versioned native admission.

Distinguish inclusion-minimal objective conflicts from minimum-cardinality optimization. Do not promote single-decision OPE to sequential policy value. Numeric conversion and threshold intersection are explicit; writer validity and business admission differ. The companion's new persistence, organ evolution, C1, longitudinal experiment, concrete simulator and authorized service specifications are indexed in its README and preserve canonical ownership and DAG predecessors.

The original 54-item closed specification surface is bounded to its registered requirements. It is not evidence that later-discovered gaps are closed. Native handoff registration, actual stores/callers/deployments, full current source/merge CI, distinct semantic review and applicable capability gates require real evidence. Coding design, integration readiness and capability/release evidence remain different gates; overall `allGapsClosed=false` is retained.
