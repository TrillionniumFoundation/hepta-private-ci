# `learning.operator` compatibility, resource, and shadow policy

## Schema and backward compatibility

- V1 payload bytes remain decodable only while their schema is explicitly pinned.
- V1 pins and V2 dataset wrappers are read-only compatibility inputs; neither independently authorizes promotion.
- V2 payload pins bind artifact and producer identity, artifact/payload schemas, runtime profile, trust snapshot, authority epoch, and registry head in addition to the V1 numerical digests.
- Every new schema version uses a new domain separator and an explicit decoder. Unknown versions fail closed. There is no best-effort field defaulting.
- Migration is: decode old → fully validate old → encode new → compare the complete semantic projection → persist create-only → independently re-evaluate. In-place mutation of an accepted artifact is forbidden.
- Downgrade is accepted only by reopening the original immutable predecessor and original pin. Re-encoding a predecessor is a new artifact and requires evaluation.

## Resource budgets

Hard input ceilings remain:

- at most 1,000,000 training rows;
- at most 262,144 tabular cells;
- at most 4,096 sensors;
- at most 128 actions;
- at most 64 MiB persisted payload.

Qualification must also publish peak resident memory, wall time, and prediction p50/p95/p99 for the largest admitted profile. A structural ceiling without a measured budget is not acceptance evidence. Inputs that cannot satisfy `cell_count × minimum_samples_per_cell ≤ row_limit` must fail during preflight before allocation or sorting.

## Longitudinal shadow acceptance

Thresholds are preregistered and stored with the evaluator receipt before final outcomes. Promotion requires all of the following over the declared window:

- zero identity, ledger, registry, trust, signature, revocation, and authority violations;
- zero unauthorized writes;
- successful fresh-process load and immutable predecessor rollback;
- stable calibration and subgroup coverage with declared confidence bounds;
- bounded abstention and OOD rates;
- no regression in independently measured task utility;
- no resource-budget breach;
- no material result change under restart, input permutation, or concurrent read pressure.

A single hard-bound violation rejects the candidate. Passing shadow acceptance authorizes only the separately declared next admission stage; it does not grant the model authority to activate itself.

## Required robustness suites

The module gate must include decoder fuzzing, property tests for determinism and ordering, semantic-row mutation tests, trust rotation and revocation races, registry movement during reads, restart/crash recovery, immutable rollback, maximum-profile benchmarks, and mutation testing of fail-closed branches. Any skipped suite is reported as missing evidence rather than success.
