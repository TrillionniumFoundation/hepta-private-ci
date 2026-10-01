# intuition.policy: implementation and execution dossier

<!-- intuition-source-state:begin -->
## Canonical source-state projection

Source: `docs/modules/intuition.policy/CURRENT_STATE.json`; content SHA-256: `74e036b3d34ac73f36fd163d9b8fca476543b038e89059630910400f2f299ae6`.

These are inspected source facts, not compilation, runtime, independent acceptance or release receipts.
All four production completion predicates remain false. Current execution identity belongs only to immutable command artifacts.

| Requirement | Source state | Scope |
| --- | --- | --- |
| `native_policy` | `source_present` | Explicit native profile risk routing and 1..128 candidate preflight before commitment hashing; historical encoding preserves prior receipt digests. |
| `authenticated_roles` | `source_present` | Generator, evaluator and observer signatures; pairwise verified controller separation. |
| `host_commit` | `source_present` | At most 127 product candidates plus abstain; complete pins, fresh owner clock and retained three-party/root-signed trust-lease revalidation under sole LedgerWriter lock. |
| `admission_receipt` | `source_partial` | Canonical final use rechecks seven owners, RunStart authentication and deadlines; selected runs retain evaluation proofs; launch and lifecycle generations remain distinct; exact retries require reconciliation; outward V1 is unchanged. |
| `authority_read` | `source_present` | Owner files use bounded checked-handle reads; full fences and evaluator-session construction bind one immutable authenticated seven-owner manifest to the request snapshot; live stages still reread current input. |
| `startup_profile` | `source_present` | Strict typed profile resolved at AgentdState startup, included in configuration identity and enforced before compatibility returns. |
| `telemetry` | `source_partial` | Existing Codex metrics and tracing with bounded static reason codes; no deployed audit/exporter acceptance. |
| `source_qualification` | `source_present` | Read-only qualification workflows; source/merge/independent lanes validate source-state and all plans retain final-use and trust-distribution tests. |
| `source_projection` | `source_present` | Canonical source state generates document blocks, implementation-map projection and contract/requirement traceability. |

Remaining closure requirements:

- **durable_handoff**: Persist exact authenticated request, policy/evaluation material and prepare/commit/run/context/delivery progress through Agentd; idempotent replay must reconcile original intent and known receipts without rebuilding provider inputs or automatic redispatch. Tracing and in-process receipts are not a durable journal.
- **transport_receipt**: Introduce and migrate a versioned outward admission/acknowledgement contract that binds the policy receipt; do not silently redefine ObjectiveRunAdmission V1.
- **generation_recovery**: Implement and execute restart reconciliation, current-authority revalidation, monotonic generation fences and process-kill/concurrent/disk/corruption cases.
- **typed_domains**: Complete distinct sequence, wall-clock, assignment-counter and generation types at all owner boundaries without changing historical wire meanings.
- **legacy_consumers**: Migrate and qualify remaining V1/V2 advisory consumers; native V4 routing does not itself retire them.
- **exact_execution**: Obtain complete real source-head, deterministic merge, independent and ledger passes and current artifact agreement; a source-authoring or portability run is insufficient.
- **operator_acceptance**: Exercise real identity/entitlement, audit/exporter delivery, combined request p50/p95/p99/capacity/witness lag and backup/restore/rotation/rollout/rollback; obtain external evaluator and operator approval.

Version and requirement-to-test/artifact mappings: `docs/modules/intuition.policy/CONTRACTS.md`.
<!-- intuition-source-state:end -->


Parent: `docs/modules/intuition.policy/TECHNICAL.md`. Lane: `LANE-F-ADAPTIVE-POLICY`. Operator procedures: `docs/modules/intuition.policy/OPERATIONS.md`.

Status: **implemented source under qualification; product closure not yet established**. The calibrated kernel, bounded product contract, split runtime commitments, three-party admission, complete Agentd pins and host-owned learning-ledger path have source implementations. The presence of `intuition_policy_serving.rs` does not prove its invocation from the canonical module tree. The actual hook and in-process receipt binding are directly committed source. Exact-head and synthetic-merge execution, real process E2E and independent acceptance remain separate facts. Pending composition scripts and workflow definitions cannot establish them.

Common execution rules: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged. This dossier preserves the target design and labels the remaining evidence rather than reducing module scope.

## 1. Source and work envelope

Primary roots:

- `codex-rs/hepta-intuition`: pure bounded policy contract and canonical digests;
- `codex-rs/hepta-intelligence`: independent evidence verification and authenticated admission;
- `codex-rs/hepta-agentd`: exact-generation host, serving composition and product-writer adapter;
- `codex-rs/hepta-learning-ledger`: durable authenticated Decision storage and independent witness.

Packages: `INT-1-CALIBRATED-INTUITION-POLICY`, `codex-hepta-intelligence`, and the bounded `codex-hepta-agentd` consumer surface. No new execution authority, model owner, random-number owner, evaluator, or ledger implementation is introduced. Changes remain on the intuition closure branch; they do not activate a policy or merge another module's work.

The tracked implementation map's `sourceBase` is a frozen inspected source mapping baseline, not an execution receipt or the self-referential commit containing that document. Current execution identity is taken only from the generated `command-record.json` fields `sourceSha`, `testedSha` and `testedTree`, together with run/attempt/job identity. Generated implementation maps and execution dossiers are artifact-local projections of that same command record; the recorder never modifies the tested checkout.

## 2. Public operations and contract details

Current source operations are:

- `decide_calibrated_v4(request, profile) -> ProductionIntuitionReceiptV1`;
- `canonical_candidate_identity_digest_v2` for generator-owned identity, legality, hard-veto, support, and order;
- `canonical_scored_outputs_digest_v2` and `canonical_scoring_commitment_digest_v2` for scorer outputs and scorer identity;
- `canonical_assignment_distribution_digest_v2` and `canonical_assignment_commitment_digest_v2` for assignment mass, stream, counter, draw, and RNG owner;
- `canonical_runtime_commitment_payload_v2` for the exact anti-substitution envelope;
- `decide_authenticated_intuition_v3` for generator/evaluator/observer authenticated admission;
- `AgentdIntuitionPolicyHostV1::{prepare_v3,commit_v4}` for retained qualification, identity/generation/profile/trust binding and final-use durable Decision append; the deprecated `commit_v3` name preserves its historical call signature while ignoring its time argument.

`AgentdState::start_canonical_intelligence` is the intended ObjectiveStart composition point. Its authenticated hook must be inspected in committed source and exercised through the actual process; a separate unreferenced module or pending finalizer is insufficient.

Historical `decide_calibrated` and `decide_calibrated_v2` remain compatibility surfaces. Feature-gating a crate-root re-export does not by itself retire direct internal consumers. The source composition must disable the default legacy root surface and migrate those consumers without silently replacing product admission by an advisory result. Qualified V3 remains a compatibility substrate; current product semantics require V4 plus authenticated V3 evidence and complete host pins.

The policy output is advisory and carries `AuthorityPosture::DENY_ALL`. Neither a prepared value nor a durable Decision receipt grants tool/model dispatch, memory mutation, or effect authority.

## 3. State records and transaction design

The policy kernel is pure. Authoritative mutable state stays with its registered owners:

1. the generator signs exact complete-candidate evidence;
2. the evaluator signs exact profile/calibration/OOD qualification;
3. the observer signs exact scoring and assignment commitments;
4. Agentd pins profile, policy, generation, objective class, model, scorer contract, calibration artifact, OOD artifact, risk rule, and optional RNG owner;
5. a selected result becomes one deterministic `ProductionDecisionV2` through the sole `LedgerWriter` held by `IntuitionPolicyLearningSink`;
6. abstain and slow-path append no selected Decision and cannot become an execution instruction.

The selected Decision must be durably committed and witnessed before product success is returned. Identity/generation/trust are checked during preparation and commit. Commit additionally recomputes the full host binding: hosts with the same Agent ID, generation and trust but different profile pins cannot consume each other's prepared values.

Preparation retains the original request, profile, scorer and assignment commitments and all three signed qualification envelopes. It captures the preparation time, earliest qualification expiration and writer-owned admitted trust generation/distribution. These bounds are included in the `hepta.agentd.prepared-intuition.v3` digest.

Final-use `commit_v4` acquires the sole writer lock before sampling `IntuitionPolicyClock`. It checks the admitted root-signed distribution lease, expiry and scheduled root revocation, then current trust digest/generation/distribution, reauthenticates generator/evaluator/observer signatures and controller separation, recomputes the exact decision and complete host pins, and rejects lifetime or clock drift before append. Writer trust rotation shares this lock and samples the same owner clock. A waiting request cannot reuse its pre-lock time or a retired trust snapshot. The `hepta.agentd.committed-intuition.v2` service digest binds final-use time and trust; existing durable Decision encodings are unchanged. The system clock detects backwards wall time within its process; this does not establish durable monotonic state or cross-process rollback protection.

Canonical product composition additionally invokes a reject-only owner fence under that writer lock. `AgentdIntelligenceProductRunnerV1::require_current_snapshot` re-reads the signed seven-owner snapshot for every disposition; `AgentdState::require_current_run_start` rechecks current run authority. Selected runs also invoke `require_current_evaluation`. The callback checks each disposition's RunStart signature expiry at its last fresh clock sample, after selected evaluation verification. The sink resamples its clock and reauthenticates policy qualification after the callback, then currentness repeats before final run/context admission; authentication and source deadlines are checked with another sample after evaluation work. The callback receives only a read-only clock interface and does not create a durable atomic transaction across the seven owners, run registry and learning ledger.

`PreparedEvaluationUseV1` retains the original signed evaluation session, exact port input, selected candidate and resulting receipt. `PreparedAgentdIntelligenceRunV1::revalidate_evaluation` repeats all evaluation proofs and compares the unchanged envelope's run, context, snapshot, objective, candidate and receipt bindings. Individual signed expiry and scheduled signer revocation remain effective independently of a longer root distribution lease. Evaluator-session construction validates all request-snapshot owner pins and derives learning.eval from the same authenticated manifest, preventing a separate earlier owner/key lookup from populating the retained session. This is in-process final-use state, not a persistent recovery journal.

Each full currentness fence uses `ManifestFreshnessOracleV1` over one verified signed manifest for all seven owner rows. The manifest view is scoped to that fence; it is never retained across a writer wait or reused by later live-stage checks. Source and selected canonical run deadlines are checked at final use with existing coordinator semantics; `run_start_deadline_ms` uses checked ceiling conversion from source microseconds.

The service retains a committed receipt if the final admission check returns either `false` or an error. That result is indeterminate for downstream admission, not evidence that the ledger append never occurred. The canonical run/context boundary now retains the complete policy receipt and typed downstream cause in process. Durable restart reconciliation and outward transport of that receipt remain separate unclosed requirements.

Idempotent replay uses the deterministic record identity, exact signed evidence and original predecessor. The current host implements one bounded exact replay for a ledger-committed/witness-not-advanced error. Ordinary rejection is not retried. A later reconciliation failure must not erase an already-known durable commit; interruption tests must cover both the first append and the retry boundary. Reopen-after-clean-drop is not a substitute for killing a process after append but before witness/acknowledgement.

## 4. Deterministic algorithm and scheduling

Hard legality and hard veto are applied before selection. Calibration, OOD, candidate completeness, policy generation, and validity windows are fail-closed. Candidate order is semantic and committed. Product entry validation applies `Ppm` bounds `[0,1_000_000]` and nonzero `PolicyGeneration`; these wrappers do not by themselves enforce monotonic cross-process updates.

The product receipt preserves original request risk and distinguishes request-high-risk, profile-risk-rule, OOD, low-confidence, and unsupported reasons. V4 invokes the shared deterministic kernel with explicit risk routing and the unchanged original request. A read-only historical encoding view preserves existing V1/V2/V3 digest fields without using a rewritten risk value to choose an action. Legacy entry points remain for compatibility callers.

Randomized assignment requires a separately owned RNG identity, stream, exact counter, exact draw, and complete distribution commitment. Deterministic assignment has no ambient draw. Assignment probabilities are excluded from scorer outputs. The scorer and assignment commitments deliberately share a generator identity digest while keeping their owned payload fields separate.

Historical generator completeness evidence V1 still signs a candidate-set digest containing utility, confidence, OOD and assignment probability. V2 scorer/distribution separation does not remove that V1 signing coupling. A future uncoupled generator payload needs a versioned producer/consumer migration; changing existing signed V1 bytes in place would invalidate historical verification.

## 5. Capacity and performance profile

The kernel admits at most 128 ordered candidates. Digests and scalar encodings are fixed-width or length-prefixed and deterministic. The policy crate introduces no network RPC or hidden mutable scoring state.

The Agentd product host separately limits preparation to 127 real candidates plus the reserved abstain option within the existing 128-entry learning-ledger limit. It rejects 128 real candidates before hashing, cloning or cryptographic verification and never truncates the complete set. `intuition_policy_product_v3.rs` exercises the 127-real-candidate durable round trip and early 128-candidate rejection.

Candidate-set commitment entry points enforce the shared 1..128 bound before allocating or hashing candidate contents. This rejects oversized authenticated completeness/scorer/assignment inputs before the expensive digest boundary while preserving every admitted historical encoding. Wire decoding and selected-host request/queue capacity remain separate resource boundaries requiring their own evidence.

Qualification definitions:

- kernel fast gate: `codex-rs/hepta-intuition/examples/fast_gate.rs`;
- authenticated gate: `codex-rs/hepta-intelligence/examples/intuition_authenticated_fast_gate.rs`;
- exact command recorder: `scripts/intuition_qualify_exact.py`;
- independent artifact verifier: `scripts/intuition_accept_exact.py`;
- selected-only writer and durable-ledger recorder: `scripts/intuition_ledger_exact.py`;
- source/merge and separate independent-execution workflow: `.github/workflows/hepta-intuition-qualification.yml`;
- mandatory selected-only/recovery workflow: `.github/workflows/hepta-intuition-ledger-qualification.yml`.

The recorder captures actual exit codes, timestamps, durations, log hashes, checked-out SHA/tree, source/base identities, host/toolchain and Cargo.lock digest. Evidence is written outside the checkout, retained on failure, and accompanied by a final unchanged-tree check. It does not format, migrate, commit, push or sign acceptance. The source-head CLI accepts `--source-commit "$(git rev-parse HEAD)"`. Stale output directories and zero-test passes are rejected; command timeouts terminate the compiler subprocess group and preserve a failure record.

Separate clean-runner independent execution must agree on the exact source/tree and Cargo.lock. The aggregate validates same-run repository/run/attempt identity, distinct job identity, complete ordered commands and hash-bound actual logs. It does not transform independent execution into semantic evaluator acceptance or production approval.

Measured p50/p95/p99 values must come from execution artifacts bound to a named source and host. Kernel latency and authentication-only latency are not a measurement of the combined Agentd request, signature checks, ledger persistence, witness and final admission path. The ledger recorder also labels its benchmark as durable-ledger-only. Combined measurement remains a required production deliverable; no percentile is asserted in this dossier.

The canonical body is pinned to the process launch (identity.spawn_generation), while RunStart records the current Fleet lifecycle generation. Starting → Running advances the latter. Current RunStart authority and the launch/current objective fence are checked before provider construction; the two generation domains are not equated. This correction does not complete durable restart reconciliation or the remaining typed-domain migration.

Exact RunStart IdempotentReplay with a configured canonical/policy composition is quarantined before the provider or policy is rerun; the existing-run admission guard also precedes provider construction. Both return stable typed reconciliation-required errors. This is retry isolation, not durable reconciliation, original-receipt restoration or resumed dispatch.

## 6. Concrete verification cases

Existing test sources specify hard veto, legality, complete-set/count/order binding, OOD, calibration, validity windows, deterministic/randomized assignment, profile/risk semantics, stable errors, bounded values and commitment mutation checks. Their presence is not a passing result.

Additional committed test sources include:

- `intuition_policy_product_v3.rs`: real signed qualification fixtures, durable writer append, exact idempotent replay and clean reopen;
- `intuition_policy_commit_boundary.rs`: ten changed complete-host pins under the same identity/generation/trust, qualification expiry despite a later-valid Decision signature, clock rollback, trust-rotation rejection, scheduled signer revocation and root-signed distribution expiry, and a lock-owned fresh-clock race proving waiting expired attempts did not write;
- `intelligence_product_final_use_tests.rs`: four functions and fifteen attack cases covering signed owner/RunStart/deadline changes during writer wait, RunStart signature expiry after callback work for all dispositions, and evaluation-distribution/proof/revocation rejection before prepared-product reuse;
- the same final-use test source retains each of three independently re-signed short evaluation proofs and exercises scheduled signer revocation while the root distribution still remains valid;
- `intelligence_authority_read_tests.rs`: bounded unauthenticated input, file growth after metadata, and Unix symlink/writable-file rejection before owner snapshot parsing;
- `intelligence_authority_snapshot_tests.rs`: a full fence cannot combine rows from two signed manifests; the next fence and live stage checks reread current input;
- `intelligence_evaluation_owner_pin_tests.rs`: typed pre-worker stale-owner rejection and actual product evaluation rejection after a signed manifest B-to-A replacement; all owner identity/generation/implementation/key/key-epoch/authority/frontier pins remain snapshot-bound;
- `intelligence_candidate_bound_tests.rs`: raw legal/intuition count preflight before signed input or worker use, with separate product 127 and compatibility 128 maxima; reaching Busy checks capacity only, not full product authentication;
- `intelligence_objective_replay_tests.rs`: three signed product fixtures with actual Fleet Starting→Running and ObjectiveRuntimeHost publication; current lifecycle 2/body 1 admits, stale lifecycle/fence/body cannot append, and exact journal replay with changed policy material leaves provider count and complete ledger/witness bytes unchanged; reopened ledger contains one original record. These fixtures have not yet been executed on the new candidate;
- `intelligence_objective_host_replay_tests.rs`: one actual signed ObjectiveRuntimeHost fixture for concurrent exact retries and reopened durable owner, retaining provider count 1 and complete ledger/witness bytes. It proves only the specified retry-isolation behavior if executed, not original-receipt restoration or process-kill recovery;
- `trust_distribution_tests.rs`: admitted distribution expiry and scheduled root revocation remain checked at use;
- `intelligence_product_tests.rs`, `intelligence_product_signed_tests.rs` and `intelligence_evaluation_tests.rs`: canonical default-production profile routing, signed product and evaluation distribution-lifetime regressions;
- host unit tests: eleven pin-binding mutations and prepared-time edge cases;
- service unit tests: preserve the exact committed token after final-gate false/error, and retain it on success;
- serving-profile tests: missing configuration defaults to Production, missing/legacy-only product hosts fail, non-production compatibility is explicit, invalid values reject, and a product build cannot select the test profile;
- `scripts/intuition_golden_vectors.py`: independent Python reconstruction of five deterministic V2 digest encodings from the shared JSON fixture and 512 seeded scorer/assignment separation mutations;
- `scripts/tests/test_intuition_exact.py` and `test_intuition_ledger_exact.py`: stale/mismatched evidence, log and command substitution, zero-test success, timeout/missing command, source mutation, distinct-job identity, and retained compiler failures;
- the retained `cargo-fuzz` target and Rust golden tests.

The Python encoder was exercised locally during the 2026-09-27 change with five matching digests and 512 passing owner-separation mutations. The later recorder hardening ran 26 Python unit tests successfully in the local working environment. These are narrow tool-level results; the recorder tests use explicitly labelled subprocess fixtures where applicable. They do not establish a Rust build, final-SHA workflow success, randomized golden coverage, a real process E2E, or external acceptance.

Required remaining cases include actual process/request E2E, crash-at-boundary recovery, deployed signed revocation and rollback across generation changes, remaining late qualifier/principal expiration scenarios, concurrent append/retry failures, and combined target-host latency. Source tests for trust rotation and writer-wait expiry do not certify a live authority controller or restart recovery. Every claimed execution must identify its tested commit/tree and actual command outcome. V3 product and commit-boundary test targets are mandatory in source, independent and ledger qualification; missing files cause a failure.

## 7. Integration, rollback and capability ceiling

Required serving sequence:

```text
signed ObjectiveStart / durable RunStart
  -> host-owned canonical invocation provider
  -> seven-owner advisory pipeline
  -> Production profile and product-host requirement
  -> authenticated V3 completeness/profile/runtime verification
  -> V4 product disposition and complete Agentd pin validation
  -> canonical/authenticated parity or explicit fail-closed routing
  -> complete prepared binding and qualification-lifetime checks
  -> selected-only durable Decision through the sole LedgerWriter
  -> current-run/generation revalidation
  -> run/context admission under its own authority
```

AgentdState resolves `HEPTA_INTUITION_PROFILE` at startup and binds its typed value into configuration identity. Missing configuration defaults to `production`; Production requires a product-ready V3 host and authenticated invocation material. A legacy-only host does not satisfy that requirement. The no-host/no-invocation historical advisory bypass now requires explicit `development` or a test-build-only `test` profile. Unknown, empty or malformed values reject. Exactly one of host/invocation being configured still fails closed in every profile. This is a source implementation contract, not proof of real-process execution or operator acceptance.

Rollback must select a separately configured, still-qualified predecessor under a new admitted configuration/generation. A trusted evaluator signature alone cannot switch host-pinned semantics. Revocation, stop and old-generation fences must remain effective across frozen snapshots and prepared values. Their process-level tests and operator rehearsal remain required; immutable pins alone do not establish a live revocation controller.

The operational runbook preserves ledger/witness/identity evidence during indeterminate recovery, requires isolated restore and qualified replay, and separates trust rotation, canary authorization and rollback. Its procedures are not evidence that an operator rehearsal or deployed audit/metrics integration has occurred.

No generator self-acceptance, self-merge, self-promotion, or self-release is permitted. `ACCEPTANCE_TEMPLATE.json` contains no valid independent approval merely by existing in the repository.

## 8. Current native implementation and claim boundary

Source surfaces include the calibrated/qualified/runtime/production policy files, authenticated V3 intelligence admission, Agentd host/service/gate/ingress, the implementation map, technical guide and operational runbook, independent golden encoder, adversarial tests and read-only qualification workflow.

Separate current states are:

| Fact | State |
| --- | --- |
| Product policy/commitment/authentication/host source exists | implemented source |
| Complete prepared profile and evidence-lifetime fences | implemented source; current Rust execution artifacts required |
| Fresh final-use clock, current trust and three-party signature revalidation under sole writer lock | implemented source; current Rust execution artifacts required |
| Sole host-held writer and direct durable fixture | implemented source; Rust execution unverified |
| Default Production profile and no missing-host bypass | implemented source; Rust execution unverified |
| Canonical ObjectiveStart hook and bound receipt | directly committed source; compile and real-process evidence still required |
| Actual Agentd process/request E2E | not established |
| Exact source and synthetic-merge command outcomes | require current execution artifacts |
| Separate independent execution | workflow and verifier implemented; current completion requires artifacts |
| Independent evaluator acceptance | not established |
| Operator target-host acceptance/canary | not established |
| Deployed audit/exporter/dashboard/SLO and recovery rehearsal | not established |
| Activation, promotion and release | not authorized by this branch |

An aggregate workflow check named `Intuition required` exists in source. Whether branch protection requires it is a separate repository administration fact; this document does not claim that configuration was changed. The four production completion predicates remain false in the tracked map and in single-run projections; a separate independent execution is not allowed to silently promote them.

`score_legal_set` and `calibrate` remain upstream responsibilities. Generator/scorer owners produce bounded candidate/scoring facts and evaluators qualify calibration/OOD artifacts. The policy authenticates those facts and selects or abstains. Future in-crate scoring/calibration is a distinct ownership change requiring contract review, not an omitted implementation hidden by a completion flag.
