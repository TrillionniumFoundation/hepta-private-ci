
# `learning.operator` compatibility, resource, and shadow policy

## Schema and backward compatibility

- V1 payload bytes remain decodable only while their schema is pinned.
- V1 pins and V2 dataset wrappers are structural compatibility inputs;
  neither independently authorizes promotion.
- V3 owner-bound inputs establish exact frozen-source and signed-row
  admission and are revalidated immediately before fit.
- V2 payload pins bind artifact and producer identity, artifact/payload
  schemas, runtime profile, trust snapshot, authority epoch, and
  registry head in addition to numerical digests.
- Every schema version uses a new domain separator and explicit
  decoder. Unknown versions fail closed.
- Migration is decode old → validate old → encode new → compare full
  semantics → persist create-only → independently re-evaluate.
- Downgrade reopens the original immutable predecessor and original pin.

## Resource budgets

Compatibility/storage ceilings:

- at most 1,000,000 represented training samples;
- at most 262,144 tabular cells;
- at most 4,096 sensors;
- at most 128 actions;
- at most 64 MiB persisted payload.

Owner-authenticated V3 admission is narrower:

- at most 4,096 signed rows and frozen source records;
- `sensors × actions × minimum_samples_per_cell ≤ rows ≤ 4096`.

Impossible profiles fail during allocation-free preflight. The larger
compatibility ceiling must never be presented as the V3 admission
capacity.

Qualification publishes peak resident memory, total wall time, and
stage timings for freeze, canonicalization, owner admission, fit-time
revalidation, encoding, create-only persistence, reload, and first
prediction. Structural ceilings alone are not acceptance evidence.

## Longitudinal shadow acceptance

Thresholds are preregistered before final outcomes. Promotion requires
zero identity/trust/authority violations, zero unauthorized writes,
fresh-process load and immutable rollback, stable calibration and
subgroup coverage, bounded abstention/OOD, no independently measured
utility regression, no budget breach, and restart/permutation/read
concurrency stability.

A hard-bound violation rejects the candidate. Passing shadow
acceptance authorizes only the separately declared next stage.

## Required robustness suites

The gate includes decoder fuzzing, determinism/order properties,
semantic-row mutation, trust rotation/revocation races, registry
movement, restart recovery, immutable rollback, maximum-profile
measurements, and fail-closed mutation tests. Missing or skipped
execution is reported as missing evidence, never success.
