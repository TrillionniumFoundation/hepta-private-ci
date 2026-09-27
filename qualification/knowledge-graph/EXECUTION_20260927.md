# knowledge.graph A/B/C execution candidate — 2026-09-27

## Fixed integration scope

This isolated candidate starts at materialized source commit
`629c6ed7a7178b9ebe4747d3a9a551a3b1089002`, not an assembly script.
The fixed main comparison is `a126987b84737dbc2ee2592442a314117bddb4a2`.
Source-head and deterministic base-merge results must identify their actual
commit and tree. Existing reports or skipped jobs are not evidence for this head.

## Implemented source retained

The native KG generation validator rejects repeated support identity and
noncanonical node/edge order. Atomic endpoint/final-support revocation is valid.
`VerifiedKnowledgeGenerationV2` owns an immutable, validated generation and an
incident-edge index. It preserves canonical edge order, support visibility,
request/result digests and exact omission counts against the full-scan reference.
Cognitive retrieval holds one generation view and compact support index per
scope/generation inside an owner read transaction; it does not cache authorization
or currentness across requests. Time visibility is evaluated on each query.

The durable writer still computes a bounded complete generation. G14
`revision_facts_v1` persistence stores immutable revision facts and generation
receipts, not a new full physical node/edge copy on every generation. The runtime
incremental writer is deliberately not selected without equivalence and measured
benefit. Existing history correction/forget/reopen and concurrent reader/writer
probes remain explicit native qualification tests, not claimed passing receipts.

## Measurement fixes in this candidate

The budget evaluator now compares every requested fixture dimension with the
actual native receipt: writes, query samples, reopen samples, concurrent readers
and contention rounds. A large outer declaration cannot relabel a smaller run.
Both measurement and budget JSON reject duplicate nested keys, nonfinite or
overflowed numbers, and non-object roots.

The measurement harness builds the release memory test executable using Cargo's
machine-readable artifact stream, records its SHA-256 and size, then executes
that exact path and exact ignored test. It rejects a zero-test/skipped outcome
and executable changes. This identifies a native Rust test harness, NOT a
production Agentd binary or an independently attested deployment.

The actual temporary filesystem used by the fixture is observed and bound in
`host.storageIdentity`; on Linux the record includes findmnt source, filesystem,
UUID and mount target. Select the fixture filesystem with TMPDIR before starting
the harness. CPU/toolchain identity, raw output SHA-256 and before/after clean
source commit/tree are retained. These checks are local observations, not a
signature or substitute for independent host acceptance.

## Reproducible tool checks

```
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s scripts -p 'test_hepta_kg_measurement.py' -v
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s scripts -p 'test_hepta_knowledge_graph_budget.py' -v
python3 scripts/hepta-knowledge-graph-target-measure.py --self-test
```

The 12 Python tests were executed successfully on the authoring environment
before commit. They use explicitly synthetic parser/harness fixtures and must
never be reported as Rust product execution or target-host measurements.

## Required completion evidence

A: exact-head and pinned-base merge formatting, strict lint, KG/prompt stack,
SQLite owner, explicit crash test, default Agentd product profile and witness
profile. Preserve each result, including failures, missing/skipped and cancellation.

B: same current source must pass indexed/reference equivalence, invalid support,
revocation, temporal cuts, scope/generation mismatch, and work-bound regressions.

C: a named target CPU/storage profile with preselected latency, memory and storage
budgets must pass real release measurement and history/concurrency runs. No target
host is selected by this document. Hosted CI observations cannot be relabeled as
a production-host qualification. Module production, execution-proved, independent
acceptance, activation and release states remain unchanged until actual evidence
supports each separate gate.
