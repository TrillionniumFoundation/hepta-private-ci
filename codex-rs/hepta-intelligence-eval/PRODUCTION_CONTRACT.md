# learning.eval production qualification contract

Status: **normative for new production integrations**.

This document is the single production-facing contract for `learning.eval`.
`TECHNICAL.md`, `EVIDENCE_ADMISSION.md`, `NATIVE_MAPPING.md`, readiness documents,
qualification dossiers, and Lane E matrices provide design, mapping, and evidence,
but they must not weaken the requirements below. If those documents conflict with
this contract, production callers fail closed and this contract wins until the
conflict is resolved in the same change.

## 1. Authority boundary

`learning.eval` produces qualification evidence only. It never grants selection,
promotion, deployment, release, merge, or external-effect authority. Every
qualification decision exposed by this module retains `AuthorityPosture::DENY_ALL`.
A separate authority boundary must consume admissible evidence before any promotion
or release action.

## 2. API status matrix

| Surface | Status | Production use |
| --- | --- | --- |
| `evaluate_legacy_inprocess` | Deprecated / crate-internal | **Forbidden** for production admission. Scalar compatibility tests only. |
| `decide_independently` | Trusted-only compatibility | Allowed only inside a trusted process or tests. It is not external identity proof. |
| `decide_independently_v2` | Trusted-only composition | Allowed only inside a trusted process or tests. It adds preregistered metric roles but is not external identity proof. |
| `decide_with_signed_evidence_v1` | Signed compatibility | Existing compatibility only; new production integrations must use V2 unless a frozen compatibility contract explicitly requires V1. |
| `decide_with_signed_evidence_v2` | **Production-required** | Required external qualification ingress for non-longitudinal qualification claims. |
| `decide_with_signed_longitudinal_evidence_v3` | **Production-required** | Required external ingress for `SystemLongitudinal` claims and observed future-window evidence. |

No adapter may turn a trusted-only result into production-admissible evidence merely
by wrapping, serializing, relabeling, or signing it after the decision.

## 3. External evaluator identity

Production external ingress must verify signed evaluator evidence against the
configured trust policy before evaluating eligibility. The verified identity must
bind at least:

- evaluator principal and role;
- key identity and allowed role;
- authentication method / trust policy digest;
- candidate and baseline identity;
- frozen evaluation-plan digest;
- evaluated artifact and applicable runtime receipt digests.

The proposer and evaluator must fail closed on role collision, principal collision,
or non-empty separation-domain collision. An unsigned `AuthenticatedPrincipalV1`
or direct `IndependentEvaluationBundleV1` is a trusted-process assertion, not a
portable proof of independence.

## 4. Frozen evaluation semantics

New production qualification uses the preregistered V2 metric-role path. Metric
roles, directions, margins, family-wise comparison policy, support requirements,
safety bounds, retention/unlearning obligations, and final-holdout identity are
frozen before confirmatory evidence is admitted. Changing one of those values
requires a new plan digest and a new qualification attempt.

Post-hoc metric selection, role changes, threshold relaxation, or replacement of a
final holdout under the same plan identity is forbidden.

## 5. Final-holdout ownership

The pure semantic journal uses an expected-head compare-and-swap contract and an
append-only predecessor-bound record chain. Deployment must preserve those
semantics durably.

### Single-host profile

`DurableFinalHoldoutJournalV1` may be used only when one trusted host owns the file,
its directory durability, access control, and independently retained anchor.
Filesystem locking serializes cooperating handles; it does not establish a
multi-host fencing boundary or protect against hostile writers, cloned handles,
snapshot rollback, or broken ACLs.

### Multi-host profile

Multi-host production use must implement `FencedFinalHoldoutStoreV1` and obtain a
`FencedFinalHoldoutOwnerV1`. The backend must provide, atomically and durably:

1. a monotonically newer fencing token for every new owner;
2. a generation check;
3. an expected journal-head check;
4. compare-and-swap replacement of the exact journal snapshot;
5. rejection of stale fencing tokens after another owner takes over;
6. durable commit before reporting success;
7. anti-rollback / independently retained currentness sufficient to detect restored
   or truncated state.

A transactional database, consensus-backed KV store, or dedicated holdout service
may satisfy this contract. A shared filesystem lock alone does not.

## 6. Runtime evidence and end-to-end qualification

Production qualification must prove the full chain rather than only evaluator unit
tests:

`producer -> runtime receipt -> frozen plan -> signed independent evaluator -> final holdout -> signed qualification evidence -> deny-all eligibility receipt`

The maintained end-to-end qualification suite must exercise success and fail-closed
cases including at least tampered evidence, wrong signer/key role, proposer/evaluator
identity collision, plan or artifact mismatch, stale/replayed final-holdout state,
metric-role drift, and runtime receipt mismatch.

## 7. CI and provenance

A production qualification artifact is acceptable only when CI binds it to the
exact source candidate. The retained evidence manifest must include:

- source commit SHA and source tree SHA;
- workflow name, workflow run id, and run attempt;
- Rust/Cargo build identity used for qualification;
- SHA-256 digests of the production contract, evaluator sources, runtime mapping
  source, Lane E matrix, qualification record, and maintained E2E tests;
- digests of generated test / coverage / stress outputs when those outputs are
  produced;
- UTC generation timestamp;
- signer / trust identity for cryptographically signed evaluation evidence.

CI metadata is provenance, not evaluator identity. It does not replace signed
external evidence.

## 8. Closure gate

`learning.eval` may move from `source_implemented_ci_pending` to `closed` only after
an exact-head Lane E run proves all maintained closure requirements and retains a
commit-addressed evidence artifact. The gate must include source verification,
all-target compilation, strict lint, maintained runtime/E2E qualification tests,
coverage/stress thresholds declared by the Lane E matrix, and synthetic-merge
qualification where required by repository policy.

Repository branch protection / rulesets must require the Lane E qualification
checks before `main` can be updated. Repository policy configuration is an
administrative control and is intentionally separate from this crate's authority.

## 9. Version changes

A change that weakens any requirement above, changes the production ingress API,
changes signed payload semantics, or changes final-holdout ownership semantics must
version this contract and update the Lane E evidence and compatibility documents in
the same candidate.
