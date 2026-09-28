# intuition.policy operational runbook

This runbook accompanies `TECHNICAL.md`, `IMPLEMENTATION_MAP.json` and the module execution dossier. It is an operator procedure and a record of remaining release gates, not an operator acceptance receipt. No deployment, canary or release is authorized merely by its presence.

## 1. Production configuration and compatibility migration

The canonical Agentd gate reads `HEPTA_INTUITION_PROFILE` once per process. Accepted values are exactly `production`, `development`, and, in a test build only, `test`. Missing configuration defaults to Production. Empty, misspelled, whitespace-padded and non-Unicode values fail closed. The profile cannot be changed through environment mutation after first use; restart into a new configured process generation instead.

Production requires a registered, product-ready V3 host even when an invocation is absent. A legacy-only host is insufficient. An invocation without a host and a configured host without authenticated invocation material both fail closed. The historical no-host/no-invocation bypass exists only after explicit non-production configuration.

Compatibility migration: an intentionally unconfigured local development process must now explicitly set `HEPTA_INTUITION_PROFILE=development`. Do not add that setting to production images or production qualification as a way to make a failing gate pass. `test` is rejected by the product binary.

The product host consumes complete immutable policy pins and the existing root-authenticated `LedgerWriter`. That writer owns a durable or segmented backend plus a separate durable witness. Do not replace it with an in-memory writer, diagnostic JSONL, or a second policy-owned authoritative store. The current typed canonical invocation replaces neither the identity authority nor the generator/evaluator/observer roles.

The canonical serving gate now emits bounded OpenTelemetry metrics and a tracing span through the process-global Codex telemetry clients. That source integration does not by itself establish deployed entitlement integration, a configured exporter endpoint, dashboard delivery, alert routing, diagnostic audit delivery or operator acceptance. Those remain separate release gates.

## 2. Exact-source qualification

Use a clean checkout of the immutable candidate, with the repository-pinned Rust toolchain and dependencies. Evidence and Cargo target output must be outside that checkout. The supported source-head entry point is:

```bash
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1
export CARGO_TARGET_DIR="$(mktemp -d)"
python3 scripts/intuition_qualify_exact.py \
  --source-commit "$(git rev-parse HEAD)"
```

For an explicitly selected empty artifact directory:

```bash
python3 scripts/intuition_qualify_exact.py \
  --source-commit "$(git rev-parse HEAD)" \
  --evidence /absolute/path/outside/checkout/qualification
```

The recorder rejects a dirty checkout, a mismatched source SHA, an output directory inside the checkout, and a nonempty output directory. It records commands before starting them, retains logs and actual exit codes on failure, kills timed-out subprocess groups, rejects zero-test Cargo results, hashes output files, and checks that HEAD/tree/worktree remain unchanged after execution.

The full plan includes golden vectors, format checking, all-target compilation, strict Clippy, kernel and qualification tests, Agentd product and commit-boundary tests, ledger tests, fast gates, and release-binary compilation with binary digests. A compiled binary is not evidence that it was deployed or that its real process entry point completed an authenticated request.

Synthetic-merge qualification additionally binds the actual two parents, source/base commits and resulting tree. A source-head pass is not a merge-tree pass. A new code, dependency, test, workflow or merge change invalidates an earlier exact-tree claim.

## 3. Independent execution and evidence acceptance

The workflow runs independent mode in a different job with a clean checkout and separate build directory:

```bash
python3 scripts/intuition_qualify_exact.py \
  --source-commit "$(git rev-parse HEAD)" \
  --independent \
  --evidence /absolute/path/outside/checkout/independent
```

Only the workflow's same-run artifact downloads may be fed into `scripts/intuition_accept_exact.py`. That verifier checks the exact source/tree, repository, run ID, attempt, distinct job IDs, Cargo.lock identity, the complete ordered command sets, log digests and actual nonzero test output. It rejects substituted commands, stale attempts, failed runs, dirty trees, missing files and changed logs. Do not fabricate `GITHUB_*` variables to give a local artifact CI provenance.

Hash agreement is integrity evidence, not an independent signer's authorization. The aggregate may establish independent execution of prescribed suites; it does not mint an independent semantic evaluator signature, a target-host operator receipt, or a release approval. The four production completion predicates remain false until their separate required evidence is admitted.

The tracked implementation map's `sourceBase` is explicitly a frozen source mapping baseline. The generated artifact map uses the executed commit/tree and embeds its command record. Neither a historical baseline nor a tracked document self-reference may substitute for `command-record.json.testedSha` and `testedTree`.

## 4. Selected-only writer qualification and measurements

All selected-only product suites are mandatory. Missing V3 or commit-boundary test targets are failures, never optional skips:

```bash
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1
export CARGO_TARGET_DIR="$(mktemp -d)"
HEPTA_TARGET_HOST_ID=operator-selected-host \
HEPTA_LEDGER_RECORDS=512 \
HEPTA_LEDGER_SEGMENT_RECORDS=64 \
python3 scripts/intuition_ledger_exact.py \
  --source-commit "$(git rev-parse HEAD)" \
  --evidence /absolute/path/outside/checkout/ledger
```

The resulting bundle includes selected-only host tests, the historical product test, V3 product/replay/reopen tests, commit-boundary tests, ledger production tests, and the existing durable-ledger benchmark. Every command has its actual outcome and a hash-bound log. Failed compilations remain failures even when a later command succeeds. Artifacts are retained by CI under the exact source SHA and run attempt, including failures.

The benchmark is explicitly durable-ledger-only. Do not label its throughput or latency as combined Agentd request latency. A production baseline must additionally measure the real authenticated request path, signature verification, selected Decision persistence, witness advancement, final admission, concurrency and tail latency on the identified deployment host. No measured p50/p95/p99 or production capacity is asserted by this runbook.

## 5. Recovery, backup and restore

Before any operator recovery, stop new admissions for the affected generation and preserve the request identity, prepared digest, deterministic Decision record ID, expected predecessor, any returned commit receipt, current ledger frontier and independent witness frontier. An `IndeterminateAfterLedgerCommit` outcome is not proof that nothing was written. Do not issue an unrelated fresh Decision ID to escape an ambiguous result.

Back up the ledger or complete segment set, checkpoint metadata, independent witness, admitted trust-distribution metadata, and required public verification material at a consistent quiesced frontier. Preserve file ownership, permissions and directory durability. Keep private signing keys out of diagnostic artifacts. Store the witness independently; copying only the ledger is not a complete restore set.

Restore to an isolated location first. Use the ledger owner's recovery and witness-validation APIs, verify identity/binding, chain integrity and the acknowledged frontier, then perform only the exact idempotent replay or reconciliation permitted by that owner. A mismatch, unsupported schema, unexpected generation or unreconciled frontier must remain quarantined. Do not repair it by truncating bytes, discarding the witness, inventing an acknowledgement, resetting generation, or editing a hash.

Promotion of a restored instance requires an operator-observed replay/reopen test and evidence that old-generation requests cannot commit. A clean drop/reopen test does not replace process-kill testing between append, witness advancement and acknowledgement. Crash-before-append, append-before-witness, witness-before-response, concurrent duplicate attempts, disk-full, permissions loss and corrupted-tail tests remain required product-level cases wherever not established by current execution artifacts.

## 6. Trust rotation, rollout and rollback

Use the registered authority to issue a root-signed successor trust distribution with monotonic generation and validity bounds. `LedgerWriter::rotate_trust` validates a successor before replacing admitted trust; a failed signature/root/monotonicity check must leave the current trust unchanged. The Agentd host and writer must continue to use matching admitted trust and policy identities. This API's presence is not proof of a deployed rotation controller.

A rollout record must bind exact source and merge-tree artifacts, binary digest, profile configuration, policy pins, trust root/distribution, host identity, revocation state, audit/metrics configuration, and the independent evaluator/operator approvals. Start with a separately authorized canary. Any missing authority, mismatched result, unresolved commit, missing audit evidence or violated agreed latency/error budget stops further expansion.

Rollback selects a still-qualified predecessor under a newly admitted configuration/generation. It must not reset monotonic state or revive expired/revoked evidence. Preserve outstanding Decision identities and reconcile them before reopening admissions. Rehearse backup/restore, rotation, canary stop and rollback on a non-production host and attach actual command/receipt artifacts before claiming operator acceptance.

## 7. Observability and remaining release gates

The canonical gate emits the following metrics through the installed Codex `MetricsClient`:

- `codex.hepta.intuition.policy.request` by bounded process profile;
- `codex.hepta.intuition.policy.outcome` by status, disposition and durable-append presence;
- `codex.hepta.intuition.policy.failure` by bounded error class;
- `codex.hepta.intuition.policy.duration` for end-to-end gate latency;
- `codex.hepta.intuition.policy.ledger_append` for acknowledged durable selected Decisions.

It also emits the internal span `hepta.intuition_policy.authenticate` and terminal success/rejection events. Labels never include request IDs, candidate IDs, episode IDs, evidence bytes, key material or arbitrary error text. Metrics and tracing are observational: exporter absence or emission failure cannot change policy admission, denial, parity checking or ledger commit semantics.

Production dashboards and alerts must distinguish selected/admit, abstain, slow-path, authority rejection, profile mismatch, expiry, generation fence, ledger failure, indeterminate commit, successful reconciliation and replay. The current bounded error classes intentionally aggregate request-specific details; operators correlate an alert with the separately governed audit and ledger receipts rather than adding high-cardinality identifiers to telemetry.

Required operational measurements include pending age, witness lag, commit/reconciliation latency, full authenticated request latency and audit-delivery failures. The owner must record the measured target-host baseline, approved error/latency/capacity budgets, alert routing and operator response. Source instrumentation is now present, but no live Prometheus/OpenTelemetry exporter, dashboard deployment, SLO result, target-host scrape or production audit delivery is certified by this change.

Keep the PR draft until the exact required checks pass. Independent execution, semantic acceptance, operator target-host acceptance and release approval remain distinct. A queued job, a workflow definition, a local recorder unit test, a template receipt or an unsigned approval JSON must never turn production completion into true.
