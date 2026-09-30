# learning.eval audit index

This index separates the short human development path from generated and machine-audited
material. No document in this directory grants runtime, acceptance, activation, promotion,
or release authority.

## Human development path

1. [`DEVELOPER_GUIDE.md`](DEVELOPER_GUIDE.md) — mission, authority, product path,
   state machine, recovery, statistical contract, failure taxonomy, deployment and gaps.
2. [`LOCAL_DETERMINISTIC_VERIFICATION.md`](LOCAL_DETERMINISTIC_VERIFICATION.md) —
   canonical offline control-plane command, strict artifact/marker rules, the 60-case
   trusted-reporter regression inventory, control-plane byte identity, and the
   authority-free evidence schema.
3. [`TECHNICAL.md`](TECHNICAL.md) — full technical development guide and detailed design
   lineage.
4. [`TARGET_HOST_QUALIFICATION.md`](TARGET_HOST_QUALIFICATION.md) — external host and
   topology evidence requirements.
5. [`RECOVERY_AMENDMENT_20260928.md`](RECOVERY_AMENDMENT_20260928.md) — persistence,
   active-trust, lifecycle-capacity and recovery evidence amendments.

## Machine-readable source and status projections

- [`CURRENT_STATUS.json`](CURRENT_STATUS.json) — conservative current claims and external
  gates. Runtime-generated `CURRENT_STATUS.run.json` is an artifact, not a committed
  replacement.
- [`IMPLEMENTATION_MAP.json`](IMPLEMENTATION_MAP.json) — exact source observation,
  operations, callers and test mapping.
- [`QUALIFICATION_MATRIX.json`](QUALIFICATION_MATRIX.json) — scoped source facts and
  unbound deployment capabilities; it contains no bare `verified` claim.

## Closeout and historical audit material

- [ADVERSARIAL_AUDIT_20260930.md](ADVERSARIAL_AUDIT_20260930.md) — 本轮中文对抗审计、修复、分层完成度、本地验证和仍未闭合的最终候选/外部证据。
- [`SOURCE_CLOSEOUT_20260928.md`](SOURCE_CLOSEOUT_20260928.md)
- [`SOURCE_CLOSEOUT_20260928.json`](SOURCE_CLOSEOUT_20260928.json)
- [`EXECUTION_CLOSEOUT.md`](EXECUTION_CLOSEOUT.md)

These records explain prior observations. The current immutable workflow artifacts and
PR machine markers are the source of truth for whether a particular SHA actually ran.

## Generated execution evidence

The source workflow retains:

- `qualification-summary.json`;
- `CURRENT_STATUS.run.json`;
- per-filter nextest discovery evidence;
- compatibility-fixture evidence;
- separate default-production and compatibility coverage reports;
- logs and normalized job conclusions.

The exact-tree workflow retains one `convergence.json` per head/merge row plus
`exact-summary.json`. The local deterministic entrypoint retains one
`local-deterministic-summary.json` plus command logs and generated fixture evidence.
Every summary has a canonical SHA-256, `authority: DENY_ALL`, and
`releasePosture: NO_GO`. Target-host, independent-acceptance, activation and release facts
must come from separately administered evidence and are never upgraded by repository CI
or by a local deterministic run.

The trusted default-branch `workflow_run` reporter treats downloaded summaries as
**untrusted data**. Before updating a machine-owned PR marker, it verifies the bounded
artifact inventory, canonical digest, producer run and attempt, exact commit/tree,
current PR head/base and qualification-control-plane byte identity. Candidate source
workflows remain read-only; the reporter never executes the candidate checkout.
