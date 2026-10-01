# intuition.policy operational runbook

<!-- intuition-source-state:begin -->
## Canonical source-state projection

Source: `docs/modules/intuition.policy/CURRENT_STATE.json`; content SHA-256: `67a6ddb0dd58e6e6a1fcbb2ce184f3e35d0a7d725df586c28dce12d9005995ce`.

These are inspected source facts, not compilation, runtime, independent acceptance or release receipts.
All four production completion predicates remain false. Current execution identity belongs only to immutable command artifacts.

| Requirement | Source state | Scope |
| --- | --- | --- |
| `native_policy` | `source_present` | Explicit native profile risk routing and 1..128 candidate preflight before commitment hashing; historical encoding preserves prior receipt digests. |
| `authenticated_roles` | `source_present` | Generator, evaluator and observer signatures; pairwise verified controller separation. |
| `host_commit` | `source_present` | At most 127 product candidates plus abstain; complete pins, fresh owner clock and retained three-party/root-signed trust-lease revalidation under sole LedgerWriter lock. |
| `admission_receipt` | `source_partial` | Canonical final use rechecks seven owners, RunStart authentication and deadlines; selected runs retain evaluation proofs; launch and lifecycle generations remain distinct; Compiled retries require reconciliation, while stored compiler ExplicitAbstain can replay without provider/policy/run/context; outward V1 is unchanged. |
| `authority_read` | `source_present` | Owner files use bounded checked-handle reads; full fences and evaluator-session construction bind one immutable authenticated seven-owner manifest to the request snapshot; live stages still reread current input. |
| `startup_profile` | `source_present` | Strict typed profile resolved at AgentdState startup, included in configuration identity and enforced before compatibility returns. |
| `telemetry` | `source_partial` | Existing Codex metrics and tracing with bounded static reason codes; no deployed audit/exporter acceptance. |
| `source_qualification` | `source_present` | Read-only qualification workflows; source/merge/independent lanes validate source-state and all plans retain final-use and trust-distribution tests. |
| `source_projection` | `source_present` | Canonical source state generates document blocks, implementation-map projection and contract/requirement traceability. |

Remaining closure requirements:

- **durable_handoff**: For Compiled canonical requests, persist exact authenticated request, policy/evaluation material and prepare/commit/run/context/delivery progress through Agentd; idempotent replay must reconcile original intent and known receipts without rebuilding provider inputs or automatic redispatch. Stored compiler-terminal ExplicitAbstain has no policy handoff. Tracing and in-process receipts are not a durable journal.
- **transport_receipt**: Introduce and migrate a versioned outward admission/acknowledgement contract that binds the policy receipt; do not silently redefine ObjectiveRunAdmission V1.
- **generation_recovery**: Implement and execute restart reconciliation, current-authority revalidation, monotonic generation fences and process-kill/concurrent/disk/corruption cases.
- **typed_domains**: Complete distinct sequence, wall-clock, assignment-counter and generation types at all owner boundaries without changing historical wire meanings.
- **legacy_consumers**: Migrate and qualify remaining V1/V2 advisory consumers; native V4 routing does not itself retire them.
- **exact_execution**: Obtain complete real source-head, deterministic merge, independent and ledger passes and current artifact agreement; a source-authoring or portability run is insufficient.
- **operator_acceptance**: Exercise real identity/entitlement, audit/exporter delivery, combined request p50/p95/p99/capacity/witness lag and backup/restore/rotation/rollout/rollback; obtain external evaluator and operator approval.

Version and requirement-to-test/artifact mappings: `docs/modules/intuition.policy/CONTRACTS.md`.
<!-- intuition-source-state:end -->


This runbook accompanies `TECHNICAL.md`, `IMPLEMENTATION_MAP.json` and the module execution dossier. It is an operator procedure and a record of remaining release gates, not an operator acceptance receipt. No deployment, canary or release is authorized merely by its presence.

## 1. Production configuration and compatibility migration

AgentdState resolves `HEPTA_INTUITION_PROFILE` at startup and binds the immutable typed profile into configuration identity. Accepted values are exactly `production`, `development`, and, in a test build only, `test`. Missing configuration defaults to Production. Empty, misspelled, whitespace-padded and non-Unicode values fail closed. Requests do not re-read the environment or a global cache; restart into a new configured process generation to change the profile.

Production requires a registered, product-ready V3 host even when an invocation is absent. A legacy-only host is insufficient. An invocation without a host and a configured host without authenticated invocation material both fail closed. The historical no-host/no-invocation bypass exists only after explicit non-production configuration.

Compatibility migration: an intentionally unconfigured local development process must now explicitly set `HEPTA_INTUITION_PROFILE=development`. Do not add that setting to production images or production qualification as a way to make a failing gate pass. `test` is rejected by the product binary.

The product host consumes complete immutable policy pins and the existing root-authenticated `LedgerWriter`. That writer owns a durable or segmented backend plus a separate durable witness. Do not replace it with an in-memory writer, diagnostic JSONL, or a second policy-owned authoritative store. The current typed canonical invocation replaces neither the identity authority nor the generator/evaluator/observer roles.

Agentd product preparation admits at most 127 real candidates; the reserved abstain entry occupies the ledger's 128th slot. The pure kernel remains bounded at 128. An oversized product request returns `agentd.intuition.product_candidate_limit` before expensive commitment work and cannot be repaired by silently truncating the complete legal set.

The product commit entry point is `commit_v4`. Its sink acquires the sole writer lock, samples the owner clock, checks the root-signed distribution lease and current trust digest/generation/distribution, and reauthenticates the retained generator/evaluator/observer qualification before append. The deprecated `commit_v3` name preserves its historical signature while ignoring its time argument and forwards to this entry point. A trust rotation invalidates prepared values from its predecessor generation; restart with a newly admitted host/verifier before preparing under the successor. An injected clock is an explicit host dependency for qualification; the system default detects backward wall time only within the current process.

Canonical Agentd admission supplies a reject-only final-use check that re-reads the signed seven-owner snapshot and current RunStart authority for every disposition after the writer wait. Selected runs also validate their evaluation trust lease. The callback receives a read-only clock interface; the sink resamples time and reauthenticates policy qualification after callback I/O. The callback checks RunStart signature expiry for every disposition after selected evaluation verification using its last fresh policy-clock sample. These checks repeat before final run/context admission; after owner/evaluation validation work, a fresh admission sample checks authentication and source/canonical deadlines immediately before start_run. The run coordinator uses nonblocking lock acquisition and returns typed overload with the acknowledged policy receipt on contention, then checks expiry again after acquiring the lock. Standalone policy commits have no seven-owner run to validate; product composition must use the canonical checked path. These checks do not replace durable handoff or restart reconciliation.

The signed owner-file reader checks the same open handle's type, permissions and size, reads at most 64 KiB plus one byte, and rejects excess actual bytes before JSON or cryptography. Unix also rejects symlinks and verifies path/handle identity. A valid metadata length cannot authorize an unbounded later read.

Selected prepared runs retain the original signed evaluation session, generator/evaluator/use proofs and exact evaluation input. Final-use and run-admission checks repeat evaluation under current time, bind the result to the existing context/snapshot/candidate/receipt and reject any shorter proof expiry or effective signer revocation even while the root lease remains valid. This retained state is private and in memory; process restart still requires the unimplemented durable handoff/reconciliation path.

Every canonical disposition must also meet the original RunStart deadline; selected runs must meet their canonical run deadline. Recheck both after the writer wait and before policy append, and recheck source expiry after acquiring the run lock. These deadline checks use current owner/wall time and the existing coordinator's rejection semantics.

A full owner fence verifies one signed manifest and checks all seven owners against that immutable view. Evaluator-session construction validates that same request snapshot and derives learning.eval from the same verified bytes; an independently current older signer/key epoch cannot satisfy a newer snapshot. Each new final-use boundary constructs a new view; the live stage oracle still reads current signed input separately. This eliminates six repeated file/crypto operations per full fence and prevents combining owner rows from different manifests. It is an operation-count change, not a claimed combined request-latency measurement.

Keep body/launch and Fleet lifecycle generations distinct. Body generation binds identity.spawn_generation; RunStart carries current lifecycle generation and the launch/current objective fence. Validate current RunStart before rebuilding owner inputs. A transition from Starting to Running must not force body identity to adopt the later lifecycle counter.

For configured canonical/policy products, an exact publication retry of a stored Compiled RunStart fails closed with agentd.intuition.service.durable_handoff_reconciliation_required before rebuilding the provider or committing policy, including after a canonical_abstained policy result. An already admitted in-process run also requires reconciliation. Stored compiler-terminal ExplicitAbstain instead replays its complete immutable publication after current authentication checks, without provider/policy/run/context work. Preserve the existing publication and any known policy receipt; do not regenerate provider material, mint a different Decision identity or automatically redispatch. Recovery of the original authenticated policy handoff and outward policy receipt remains unimplemented.

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

The full plan includes read-only source-state projection validation, golden vectors, format checking, all-target compilation, strict Clippy, kernel and qualification tests, Agentd product and commit-boundary tests, ledger production and trust-distribution tests, fast gates, and release-binary compilation with binary digests. The independent plan also validates source-state projection and executes the same commit-boundary target; final-use tests are part of that existing target. Both plans execute the canonical `intelligence_product` profile/evaluation/signature regressions, including distribution-lease revalidation. A compiled binary is not evidence that it was deployed or that its real process entry point completed an authenticated request.

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

The resulting bundle includes selected-only host tests, the historical product test, V3 product/replay/reopen tests, commit-boundary tests, ledger production and trust-distribution tests, and the existing durable-ledger benchmark. Every command has its actual outcome and a hash-bound log. Failed compilations remain failures even when a later command succeeds. Artifacts are retained by CI under the exact source SHA and run attempt, including failures.

The benchmark is explicitly durable-ledger-only. Do not label its throughput or latency as combined Agentd request latency. A production baseline must additionally measure the real authenticated request path, signature verification, selected Decision persistence, witness advancement, final admission, concurrency and tail latency on the identified deployment host. No measured p50/p95/p99 or production capacity is asserted by this runbook.

## 5. Recovery, backup and restore

Before any operator recovery, stop new admissions for the affected generation and preserve the request identity, prepared digest, deterministic Decision record ID, expected predecessor, any returned commit receipt, current ledger frontier and independent witness frontier. An `IndeterminateAfterLedgerCommit` outcome is not proof that nothing was written. Do not issue an unrelated fresh Decision ID to escape an ambiguous result.

An idempotent replay of a stored Compiled RunStart must reconcile the original authenticated request and policy/evaluation material, including when the later policy result was canonical_abstained, selected or slow-path. Rebuilding provider inputs or automatically redispatching merely because the same run ID reappears cannot stand in for that reconciliation. Exact persistent handoff material and real crash/replay fixtures remain required; the current in-process retained receipts do not establish this behavior after restart.

Compiler-terminal ExplicitAbstain is a separate stored RunStart disposition. Its exact replay returns the immutable terminal publication after current authentication checks, with explicit_abstain and idempotent true, without entering provider, policy, run or context work. Do not treat a Compiled request's canonical_abstained policy result as this terminal exception. Concurrent and clean-reopen source fixtures for the exception do not establish process-kill recovery or policy-handoff reconciliation.

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
