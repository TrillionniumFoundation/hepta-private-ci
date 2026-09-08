# Hepta module technical guides

This directory contains exactly one stable implementation guide for every module registered in `MODULES.json`. Machine-readable coverage and digests are in `MODULE_DOCS.json`; source reality is in `SOURCE_BINDINGS.json`. A guide explains implementation and operations but grants no runtime, acceptance, promotion or release authority.

## Guides

- [`platform.types`](platform.types/TECHNICAL.md) — `existing_bound`, bootstrap `PLATFORM-0-TYPE-BOUNDARY`.
- [`platform.wire`](platform.wire/TECHNICAL.md) — `existing_bound`, bootstrap `P0.7E-DEPENDENCY-INVERSION`.
- [`kernel.authority`](kernel.authority/TECHNICAL.md) — `existing_bound`, bootstrap `P0.7B-B0-VERIFIED-USE`.
- [`kernel.operations`](kernel.operations/TECHNICAL.md) — `existing_bound`, bootstrap `P0.7D-FAULT-MATRIX`.
- [`kernel.evidence`](kernel.evidence/TECHNICAL.md) — `existing_bound`, bootstrap `P0.9-EXTERNAL-GATES`.
- [`runtime.supervisor`](runtime.supervisor/TECHNICAL.md) — `existing_bound`, bootstrap `P0.7A-RUNTIME-BOOTSTRAP`.
- [`runtime.fleet`](runtime.fleet/TECHNICAL.md) — `existing_bound`, bootstrap `FLEET-1-ALLOCATION-CONTRACT`.
- [`runtime.agentd`](runtime.agentd/TECHNICAL.md) — `existing_bound`, bootstrap `P0.8B-READINESS`.
- [`runtime.codex`](runtime.codex/TECHNICAL.md) — `existing_bound`, bootstrap `P0.7B-B1B-MODEL-BOUNDARY`.
- [`auth.authbus`](auth.authbus/TECHNICAL.md) — `existing_bound`, bootstrap `AUTHBUS-P1.3-V12`.
- [`secrets.heptabao`](secrets.heptabao/TECHNICAL.md) — `existing_bound`, bootstrap `HEPTABAO-1-SECRET-BOUNDARY`.
- [`inference.control`](inference.control/TECHNICAL.md) — `existing_bound`, bootstrap `P0.7B-B1A-PROVIDER-BOUNDARY`.
- [`inference.worker`](inference.worker/TECHNICAL.md) — `existing_bound`, bootstrap `INFER-V4-T4`.
- [`objective.compiler`](objective.compiler/TECHNICAL.md) — `existing_bound`, bootstrap `OBJ-0-OBJECTIVE-CONTRACTS`.
- [`utility.ndu`](utility.ndu/TECHNICAL.md) — `existing_bound`, bootstrap `NDU-0-PREFERENCE-UTILITY-CONTRACTS`.
- [`neuron.runtime`](neuron.runtime/TECHNICAL.md) — `existing_bound`, bootstrap `BIO-0-NEURON-INTUITION-CONTRACTS`.
- [`intuition.policy`](intuition.policy/TECHNICAL.md) — `existing_bound`, bootstrap `INT-1-CALIBRATED-INTUITION-POLICY`.
- [`prompt.registry`](prompt.registry/TECHNICAL.md) — `existing_bound`, bootstrap `PIM-0-PROMPT-INTERVENTION-CONTRACTS`.
- [`prompt.optimizer`](prompt.optimizer/TECHNICAL.md) — `existing_bound`, bootstrap `PIM-2-PROMPT-PRICING-PORTFOLIO-SHADOW`.
- [`context.compiler`](context.compiler/TECHNICAL.md) — `existing_bound`, bootstrap `CTX-1-CONTEXT-COMPILER`.
- [`intelligence.control`](intelligence.control/TECHNICAL.md) — `existing_bound`, bootstrap `INTELLIGENCE-A0-Q0.63`.
- [`cognitive.types`](cognitive.types/TECHNICAL.md) — `existing_bound`, bootstrap `MEM-0-TYPES`.
- [`cognitive.store`](cognitive.store/TECHNICAL.md) — `existing_bound`, bootstrap `MEM-1-STORE`.
- [`cognitive.read`](cognitive.read/TECHNICAL.md) — `existing_bound`, bootstrap `MEM-READ-1-SNAPSHOT-PORT`.
- [`memory.retrieval`](memory.retrieval/TECHNICAL.md) — `existing_bound`, bootstrap `MEM-2-RETRIEVAL`.
- [`memory.federation`](memory.federation/TECHNICAL.md) — `existing_bound`, bootstrap `MEM-3-FEDERATION`.
- [`knowledge.graph`](knowledge.graph/TECHNICAL.md) — `existing_bound`, bootstrap `MEM-4-KG`.
- [`compact.engine`](compact.engine/TECHNICAL.md) — `existing_bound`, bootstrap `MEM-5-COMPACT`.
- [`learning.ledger`](learning.ledger/TECHNICAL.md) — `existing_bound`, bootstrap `LRN-0-CAUSAL-LEARNING-CONTRACTS`.
- [`learning.operator`](learning.operator/TECHNICAL.md) — `existing_bound`, bootstrap `HBO-0-BELLMAN-OPERATOR-CONTRACTS`.
- [`learning.eval`](learning.eval/TECHNICAL.md) — `existing_bound`, bootstrap `LRN-2-CAUSAL-EVALUATION`.
- [`learning.artifacts`](learning.artifacts/TECHNICAL.md) — `existing_bound`, bootstrap `ART-1-LEARNING-ARTIFACT-REGISTRY`.
- [`learning.plasticity`](learning.plasticity/TECHNICAL.md) — `existing_bound`, bootstrap `PLS-1-PARAMETER-PLASTICITY`.
- [`automation.taskflow`](automation.taskflow/TECHNICAL.md) — `existing_bound`, bootstrap `TASKFLOW-1-EXECUTION-BOUNDARY`.
- [`channel.matrix`](channel.matrix/TECHNICAL.md) — `existing_bound`, bootstrap `MATRIX-1-CHANNEL-BOUNDARY`.
- [`browser.servo`](browser.servo/TECHNICAL.md) — `existing_bound`, bootstrap `BROWSER-WEB-C1`.
- [`ui.control`](ui.control/TECHNICAL.md) — `existing_bound`, bootstrap `UI-V5`.
- [`ui.native`](ui.native/TECHNICAL.md) — `existing_bound`, bootstrap `UI-NATIVE-1-SHELL`.
- [`control.runtime`](control.runtime/TECHNICAL.md) — `existing_bound`, bootstrap `RCP-1-RUNTIME-CONTROL-PLANE`.
- [`control.engineering`](control.engineering/TECHNICAL.md) — `existing_bound`, bootstrap `ECP-1-ENGINEERING-CONTROL-PLANE`.

## Adaptive algorithm overlay

The module guides above define ownership, boundaries and delivery envelopes. Implementation-level mathematics, algorithms, data lineage and quantitative acceptance gates for the fourteen adaptive modules are closed separately in [`../learning/README.md`](../learning/README.md) and bound by [`../learning/ALGORITHM_SPECS.json`](../learning/ALGORITHM_SPECS.json). This overlay does not change any module source status or capability claim.

## Pre-coding readiness overlay

Every guide now includes Section 16, which binds the module to one primary implementation lane and the exact specifications and typed protocols in [`../readiness/README.md`](../readiness/README.md). The overlay closes implementation ambiguity but does not change source or capability status.

## HeptaBao executable connection

For the implemented host-enrolled read path, continue from the `kernel.authority`, `runtime.supervisor` and `secrets.heptabao` guides to the [final-use and issuer design](../../codex-rs/hepta-contracts/FINAL_USE.md) and [HTTPS consumer integration](../../codex-rs/hepta-bao-adapter/README.md). They specify the actual signatures, persistent state schema, atomic-write and revocation fences, callback trust boundary, APIs, failure outcomes and tests. The earlier metadata-only adapter API remains available with dispatch disabled. These implementation notes add no automatic runtime enrollment or release authority.
