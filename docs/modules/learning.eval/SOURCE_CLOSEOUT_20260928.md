# learning.eval source closeout — 2026-09-28 JST

This note records the repository-controlled source observation requested for the `learning.eval` convergence work. It is not an execution receipt, target-host qualification, independent acceptance, activation grant, or release authorization.

## Immutable source observation

- Source commit: `d810e19aebf912013439e05f558943a8d311ec66`
- Source tree: `8038b5ac420ef156d2e3f5aa1436e2c3f0da011e`
- Active delivery route: PR #1011, branch `fix/learning-eval-full-convergence-20260926`
- Historical comparison only: PR #1051; do not independently merge both implementations.

The closeout documentation commit follows the source observation and therefore does not make the observation self-referential. Qualification must prove the observed source and the final documentation-only delta separately.

## Repository source delivered

### Mainline and API consistency

- The default build keeps the V2/V3 decision primitives crate-internal.
- The raw `ProductEvaluationRunnerV1` remains available only through the explicit `trusted-inprocess-eval` compatibility feature.
- The API qualification step now has real positive/negative compile fixtures.
- The lexical caller inventory strips Rust comments and literals and matches complete identifiers, so `RecordedProductEvaluationRunnerV1` is not treated as the raw runner.
- Agentd and governed-plasticity consumers use sealed, deny-all admission paths; evaluated shadow consumes the sealed product qualification receipt.

### Recovery and publication

- Durable attempt intent is written before final-holdout access.
- The attempt journal has an independently retained anchor, validates full histories, rejects old complete prefixes, and paginates recovery without starving later attempts.
- Qualification publication follows `QualificationDecided -> PublicationPending -> Published`.
- A Pending attempt is never blindly retried; authoritative publication state is read and matched first.
- Complete host-sealed temporal receipt, qualification context, signed evidence, and timing evidence are persisted create-only before `QualificationDecided`.
- Stored objects are bounded, content-digested, tied to attempt/plan/holdout/execution, and bound to the selected-host identity.
- Restart recovery requires the host codec to decode and re-run current trust, expiry, revocation, role-separation, timing, and binding checks.

### Outcome semantics and downstream use

- Frozen outcome-channel contracts bind typed outcome identity, measured-input digest, estimator plan, and metric identity.
- Each channel receives its own native estimate; changing only a metric name cannot manufacture a new measured outcome.
- Agentd has an exact request-bound consumer for `ProductOutcomeQualificationReceiptV1`.
- The consumed receipt and the resulting digest remain deny-all and do not authorize selection, promotion, activation, or release.

### Selected-host and sustained profile source

- A create-only persistent publication store binds publication records to the same selected-host identity as the complete qualification artifacts.
- Selected-host facade methods cover first publication, artifact-based restart recovery, and read-only publication reconciliation.
- `long_running_profile.rs` exercises 4,096 attempts and 24,576 lifecycle transitions, closing and reopening the journal with an independent anchor every 128 attempts.
- `.github/workflows/hepta-learning-eval-soak.yml` binds the exact source SHA and retains command output, exit code, environment identity, and SHA-256 manifest.

## Execution boundary at authoring time

For source commit `d810e19aebf912013439e05f558943a8d311ec66`, the following dedicated runs existed but had not started executing when this note was authored:

- convergence run `36352177884`
- exact-tree run `36352177859`
- sustained selected-host profile run `36352177807`

Queued, cancelled, skipped, or infrastructure-invalid jobs are not passing evidence. The PR must remain draft until the final exact head, ordered-parent synthetic merge, owner/consumer regression, fault matrix, coverage, strict lint/format, and sustained profile produce retained successful artifacts.

## Remaining repository-controlled work

- Resolve any compilation, regression, coverage, lint, formatting, or exact-merge failure reported by the final runs.
- Add signed multi-outcome and artifact-based public-resume end-to-end coverage rather than relying only on component tests.
- Rebind the canonical generated status, implementation map, `TECHNICAL.md`, and `NATIVE_MAPPING.md` after the final executable source is fixed; do not change completion fields before those executions.
- Add attempt-journal checkpoint/rotation qualification if the selected topology requires operation closer to the 64 MiB / one-million-event source limits.

## External evidence that the repository cannot self-issue

- authenticated independent anchor authority and selected-host operator approval;
- cross-host filesystem linearizability and fsync semantics where that topology is selected;
- real future-calendar observations and independent outcome provenance;
- retention, change-point, statistical power, subgroup, privacy, and unlearning evidence;
- backup non-resurrection evidence;
- independent semantic/operator acceptance, canary, selection, promotion, activation, and release authority.
