# learning.eval audit index

This index separates the short human development path from generated and machine-audited
material. No document, source workflow, or repository receipt in this directory grants
runtime, acceptance, activation, promotion, or release authority.

## Human development path

1. [`DEVELOPER_GUIDE.md`](DEVELOPER_GUIDE.md) — mission, authority, product path,
   state machine, recovery, statistical contract, failure taxonomy, deployment,
   qualification trust boundaries, and known gaps.
2. [`TECHNICAL.md`](TECHNICAL.md) — full technical development guide and detailed design
   lineage.
3. [`TARGET_HOST_QUALIFICATION.md`](TARGET_HOST_QUALIFICATION.md) — external host and
   topology evidence requirements.
4. [`RECOVERY_EVIDENCE_ADDENDUM.md`](RECOVERY_EVIDENCE_ADDENDUM.md) — persistence and
   recovery evidence details.

## Machine-readable source and status projections

- [`CURRENT_STATUS.json`](CURRENT_STATUS.json) — conservative current claims and external
  gates. Runtime-generated `CURRENT_STATUS.run.json` is an artifact, not a committed
  replacement.
- [`IMPLEMENTATION_MAP.json`](IMPLEMENTATION_MAP.json) — exact source observation,
  operations, callers, and test mapping.
- [`QUALIFICATION_MATRIX.json`](QUALIFICATION_MATRIX.json) — scoped source facts and
  unbound deployment capabilities; it contains no bare `verified` claim.

## Closeout and historical audit material

- [`SOURCE_CLOSEOUT_CURRENT.md`](SOURCE_CLOSEOUT_CURRENT.md)
- [`SOURCE_CLOSEOUT_CURRENT_AUDIT.md`](SOURCE_CLOSEOUT_CURRENT_AUDIT.md)
- [`EXECUTION_CLOSEOUT.md`](EXECUTION_CLOSEOUT.md)

These records explain prior observations. Current immutable workflow artifacts and the
machine-owned PR markers identify whether a particular SHA actually ran; prose is not a
substitute for the commit-addressed evidence.

## Generated execution evidence

The read-only source workflow retains:

- `qualification-summary.json`;
- `CURRENT_STATUS.run.json`;
- per-filter nextest discovery evidence;
- compatibility-fixture evidence;
- logs, coverage, and job conclusions.

The read-only exact-tree workflow retains one `convergence.json` per head/merge row plus
`exact-summary.json`. Every summary has a canonical SHA-256, `authority: DENY_ALL`, and
`releasePosture: NO_GO`. Target-host, independent-acceptance, activation, and release facts
must come from separately administered evidence and are never upgraded by repository CI.

## Trusted reporting boundary

Candidate workflows have only `contents: read`; they do not receive `pull-requests: write`,
`id-token: write`, or attestation authority while executing candidate code. They upload
summaries but do not mutate the PR.

`.github/workflows/hepta-learning-eval-trusted-report.yml` is a default-branch
`workflow_run` reporter. It checks out only the trusted default branch and downloads a
producer artifact as **untrusted data**. Before a PR marker can be changed, the reporter
requires the expected artifact/file name, a single bounded regular file, a valid schema and
canonical evidence hash, matching repository/run/attempt identity, a current same-repo PR,
and an exact current head-SHA match. Symlinks, stale runs, substituted identities, malformed
claims, or externally self-issued authority fail closed.

Successful provenance attestation is isolated to `push` runs on `main`. The attestation job
downloads the already-produced summary and does not execute the candidate checkout under
OIDC authority.
