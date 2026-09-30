# learning.eval trusted control-plane bootstrap audit index

This is the scoped audit index for the independently reviewable trusted-control-plane
bootstrap. It inventories only files actually present on this branch. Nothing here grants
module source qualification, target-host qualification, independent acceptance,
activation, promotion, or release authority.

## Human control-plane path

1. [`LOCAL_DETERMINISTIC_VERIFICATION.md`](LOCAL_DETERMINISTIC_VERIFICATION.md) — the
   authority-free offline control-plane contract and evidence semantics.
2. [`TECHNICAL.md`](TECHNICAL.md) — the pre-existing stable module guide retained from the
   fixed `main` base. Its presence is not a claim that the bootstrap carries the module
   implementation.

## Machine-readable bootstrap projections

- [`QUALIFICATION_MATRIX.json`](QUALIFICATION_MATRIX.json) — bootstrap-scoped source facts,
  false external claims, `DENY_ALL`, and `NO_GO`.
- [`IMPLEMENTATION_MAP.json`](IMPLEMENTATION_MAP.json) — the pre-existing historical map
  retained from the fixed base. It is not regenerated or upgraded by this bootstrap.

## Trusted source inventory

The reviewed bootstrap additionally contains:

- every `.github/workflows/hepta-learning-eval-*.yml` producer/reporter workflow;
- the `scripts/hepta-learning-eval-*` evidence and reporting control plane;
- exact-test discovery and Rust-identifier helpers;
- the isolated `codex-rs/hepta-intelligence-eval/fixtures/trusted-inprocess` fixture.

The default-branch reporter performs closed-world workflow discovery and byte identity for
the registered auxiliary control-plane files before updating a current Draft PR marker.
Downloaded candidate artifacts and candidate file responses remain untrusted data.

## Deliberately absent from bootstrap scope

This branch does not carry the current `learning.eval` Rust product implementation,
Agentd/intelligence consumer changes, target-host evidence, current implementation map,
module closeout dossier, real provider/publication adapters, or external acceptance.
Those belong to the separately restacked module candidate after this bootstrap is reviewed
and merged through a verified protected path.

## Generated evidence

The dedicated bootstrap workflow retains immutable source identity, deterministic
regression logs, Markdown verifier regressions, target-host-verifier self-test output, and
a scoped `hepta.learning-eval.control-plane-bootstrap.v1` record. Every such record remains
`DENY_ALL` and `NO_GO`; queued, skipped, cancelled, neutral, stale, timed-out, startup
failure, or infrastructure-invalid work is not PASS.
