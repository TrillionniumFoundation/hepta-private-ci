# `ui.control` protected external-qualification preflight

The external qualification workflow has three process-isolated trust domains:

1. a trusted repository preflight that runs without deployment, Agentd, identity-provider, or release-authority secrets;
2. a separate secretless candidate-build job that may execute candidate-owned `npm` code but cannot enter the protected environment;
3. a fresh protected runner that never executes candidate-owned code and cannot start until the preflight and isolated build both succeed and the `ui-control-production-qualification` environment authorizes entry.

The trusted verifier is checked out from the immutable `github.workflow_sha`. The candidate checkout is an exact subject identity and data source; it is not the authority that interprets external evidence.

## Required invocation

Dispatch `.github/workflows/ui-control-external-qualification.yml` from `refs/heads/main`. Supply:

- the exact lowercase 40-character candidate commit SHA;
- the official successful pull-request qualification run ID for that candidate;
- whether the disposable real-backend scenarios should run;
- whether the independent production-evidence bundle should be validated.

Production-evidence validation requires the real-backend scenarios in the same protected run. A candidate that is not reachable from `origin/main`, an off-main dispatch, a failed or unrelated workflow run, a fork-head run, or a missing/ambiguous receipt fails before the protected environment is entered.

## Secretless repository preflight

The preflight checks out two trees without executing candidate code:

1. the immutable workflow SHA supplies the trusted preflight validator;
2. the exact candidate tree supplies the Git identity being qualified.

The preflight then verifies:

- exact candidate checkout and candidate-tree identity;
- candidate ancestry from `refs/remotes/origin/main`;
- repository, head repository, workflow path, event, status, conclusion, run attempt, candidate SHA, and matching pull request in GitHub Actions run metadata;
- exactly one exact-head receipt and one synthetic-merge receipt from that run;
- exact candidate commit/tree binding, required passed stages, and matching dependency-lock and browser-build identities across both receipts.

The output is `hepta.ui-control.repository-preflight-observation.v1`. It is an observation, not a seven-stage acceptance receipt. On every failure path it keeps `protectedSecretsEligible`, `realBackendSemanticsQualified`, `productionDeploymentApproved`, and `releaseAuthorized` false.

## Isolated candidate build

Only the `candidate-build` job executes candidate-owned package code. It runs on a different, secretless runner after repository preflight succeeds. It installs the exact lock with lifecycle scripts disabled, builds the browser artifact, verifies that the candidate commit and tracked tree did not change, and uploads only the resulting `dist` tree.

The protected job treats that artifact as untrusted data. Before any protected value is mapped, the workflow-SHA verifier requires:

- the build-manifest digest to equal the accepted exact-head qualification receipt;
- a bounded, sorted, traversal-free relative path set;
- regular files only, with no symbolic links;
- an exact match between the manifest file set and the downloaded artifact file set;
- bounded per-file and aggregate sizes;
- exact byte counts and SHA-256 digests for every file;
- the canonical and sole `index.html` CSRF bootstrap substitution declaration.

Candidate-controlled environment writes, PATH changes, workspace mutations, or process state cannot cross into the protected job because it starts on a fresh runner.

## Protected environment boundary

Only the `protected-external-qualification` job names the `ui-control-production-qualification` environment. Configure that environment with required independent reviewers, main-only deployment-branch policy, no administrator bypass, and the deployment/Agentd/manual-acceptance secrets.

The protected runner checks out the immutable workflow-SHA verifier and the exact candidate separately. It repeats candidate identity and main-ancestry checks, downloads the already accepted preflight evidence and isolated build artifact, and completes trusted artifact validation before the first secret expression appears. It does not run `npm`, candidate package scripts, candidate test code, local candidate actions, or candidate qualification modules.

The protected job may then produce:

- an HTTPS/deployment-security receipt;
- a real Agentd/backend receipt, only for a disposable qualification target;
- an external evidence bundle, only when independently retained accessibility, security, operations, and signed production-approval evidence is supplied.

Repository fixtures, hand-edited booleans, the preflight observation, the candidate-build observation, or a green repository-only qualification run cannot set `realBackendPassed`, `productionDeploymentApproved`, or `releaseAuthorized`.

## Failure handling

All three jobs retain bounded evidence. The preflight creates a structured infrastructure-invalid observation when semantic validation cannot run. The protected job retains the candidate-build observation and any deployment, backend, or bundle receipts that were produced. Missing genuine external systems or independent evidence remains a failed or unclaimed stage; it is never converted into a pass.
