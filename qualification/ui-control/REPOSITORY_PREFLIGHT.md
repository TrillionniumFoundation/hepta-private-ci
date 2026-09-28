# `ui.control` protected external-qualification preflight

The external qualification workflow has two trust domains. The repository preflight runs without deployment, Agentd, identity-provider, or release-authority secrets. The protected external job cannot start until that preflight succeeds and the `ui-control-production-qualification` environment authorizes entry.

## Required invocation

Dispatch `.github/workflows/ui-control-external-qualification.yml` from `refs/heads/main`. Supply:

- the exact lowercase 40-character candidate commit SHA;
- the official successful pull-request qualification run ID for that candidate;
- whether the disposable real-backend scenarios should run;
- whether the independent production-evidence bundle should be validated.

Production-evidence validation requires the real-backend scenarios in the same protected run. A candidate that is not reachable from `origin/main`, an off-main dispatch, a failed or unrelated workflow run, a fork-head run, or a missing/ambiguous receipt fails before the protected environment is entered.

## Secretless preflight

The workflow checks out two trees:

1. the current `main` tree supplies the trusted preflight validator;
2. the exact candidate tree supplies the Git identity being qualified.

The preflight then verifies:

- exact candidate checkout and candidate-tree identity;
- candidate ancestry from `refs/remotes/origin/main`;
- repository, head repository, workflow path, event, status, conclusion, run attempt, candidate SHA, and matching pull request in GitHub Actions run metadata;
- exactly one exact-head receipt and one synthetic-merge receipt from that run;
- exact candidate commit/tree binding, required passed stages, and matching dependency-lock and browser-build identities across both receipts.

The output is `hepta.ui-control.repository-preflight-observation.v1`. It is an observation, not a seven-stage acceptance receipt. On every failure path it keeps `protectedSecretsEligible`, `realBackendSemanticsQualified`, `productionDeploymentApproved`, and `releaseAuthorized` false.

## Protected environment boundary

Only the `protected-external-qualification` job names the `ui-control-production-qualification` environment. Configure that environment with required independent reviewers, main-only deployment-branch policy, no administrator bypass, and the deployment/Agentd/manual-acceptance secrets. Candidate lint, unit/contract tests, deterministic build, and a repeated main-ancestry check run before any protected value is mapped into a process environment.

The protected job may then produce:

- an HTTPS/deployment-security receipt;
- a real Agentd/backend receipt, only for a disposable qualification target;
- an external evidence bundle, only when independently retained accessibility, security, operations, and signed production-approval evidence is supplied.

Repository fixtures, hand-edited booleans, the preflight observation, or a green repository-only qualification run cannot set `realBackendPassed`, `productionDeploymentApproved`, or `releaseAuthorized`.

## Failure handling

Both jobs upload evidence even on failure. The preflight creates a structured infrastructure-invalid observation when semantic validation cannot run. The protected job retains any deployment, backend, or bundle receipts that were produced. Missing genuine external systems or independent evidence remains a failed or unclaimed stage; it is never converted into a pass.
