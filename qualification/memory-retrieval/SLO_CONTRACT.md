# Memory retrieval end-to-end SLO contract

This contract defines the measurements required before `memory.retrieval` may be promoted. It does not promote the module. `SLO_LIMITS.json` contains conservative GitHub-hosted qualification ceilings; production limits require a separately approved named-host baseline.

## Measured path

One end-to-end sample includes SQLite observation, exact Lane C snapshot binding, candidate adaptation, HNMF settling, optional downstream reranking, final source/revision/content revalidation, text materialization, context planning, and durable learning-assignment append. A benchmark that omits any stage must use a narrower phase name and cannot satisfy the end-to-end gate.

## Required dimensions

Receipts report wall-clock p50, p95, p99 and maximum; user/system CPU; peak RSS; allocation count; logical SQLite read count; candidate, node and synapse counts; cold and warm cache; concurrency 1/8/32; owner-write contention; provider-rotation contention; abstention rate; and stale-context rejection rate. Every count must be directly instrumented or explicitly marked unavailable. Estimated or relabelled values are prohibited.

## Evidence classes

GitHub-hosted results prove only reproducibility and regression ceilings. A production SLO requires a named target host, exact binary/source/tree identity, configuration/model/index identity, raw logs, receipt digest, independent reviewer approval and an immutable provenance attestation. Baseline promotion is a reviewed repository change; CI never overwrites a baseline automatically.

## Failure rule

Missing phases, missing numeric metrics, threshold violations, source/tree mismatch, stale limits, skipped commands or unsigned production receipts fail closed. Performance success cannot override semantic, security, review, activation or release gates.
