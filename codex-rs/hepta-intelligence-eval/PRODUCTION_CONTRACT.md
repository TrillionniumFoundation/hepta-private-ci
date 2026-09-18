# learning.eval production contract

This document is the normative source of truth for production-facing candidate
evaluation and qualification. It narrows, rather than expands, authority.
Eligibility remains evidence for an independent selector; it is never promotion,
release, deployment, or model-mutation authority.

## API status matrix

| Surface | Status | Allowed use |
|---|---|---|
| `evaluate_legacy_inprocess_v1` | **Trusted-only / legacy** | Compatibility tests or explicitly trusted in-process callers only. It is absent from the default production API and is exposed only by the `legacy-inprocess-eval` Cargo feature. |
| feature alias `evaluate` | **Deprecated / trusted-only** | Available only when `legacy-inprocess-eval` is explicitly enabled. New code must not use it. |
| `decide_independently` | **Trusted-only structural evaluator** | Qualification fixtures and already-authenticated in-process composition. It does not authenticate an external evaluator. |
| `decide_independently_v2` | **Trusted-only structural evaluator** | Same boundary as above, with preregistered metric roles. It is not an external production ingress. |
| `decide_with_signed_evidence_v1` | **Signed compatibility** | Historical non-longitudinal signed evidence only. New production integrations should use V2. |
| `decide_with_signed_evidence_v2` | **Production-required** | External/non-longitudinal candidate qualification. The host supplies a current `LearningEvidenceVerifierV1` from trusted state. |
| `decide_with_signed_longitudinal_evidence_v3` | **Production-required for SystemLongitudinal** | System-longitudinal claims with signed observed-time evidence. V1/V2 must reject this claim class. |
| `run_evaluated_shadow_v1` | **Current composed production-boundary candidate** | Signed V2 evaluation plus candidate-byte and dataset binding before any downstream Lane F port is invoked. It remains shadow/no-effect and does not grant promotion authority. |

Production code outside the evaluator crate and qualification-only fixtures must
not call `decide_independently` or `decide_independently_v2` directly. The
Lane E verifier enforces this repository rule.

## Identity and trust requirements

Production ingress MUST:

1. construct `LearningEvidenceVerifierV1` from host-owned current trust state,
   never from the remote evaluation request;
2. verify generator and evaluator signatures, role assignment, objective,
   authority epoch, lifetime, revocation and controller separation;
3. bind the exact frozen plan, metric-role contract and evaluation payload;
4. retain the decision's trust and authentication digests;
5. preserve `AuthorityPosture::DENY_ALL` on every eligibility decision.

A caller-constructed `AuthenticatedPrincipalV1` is structural evidence only.
Unequal identifiers do not prove independent actors.

## Final-holdout ownership

`DurableFinalHoldoutJournalV1` is a local/cooperating-owner durable journal.
It remains valid for trusted single-host use with an independently retained
anchor, but its file lock is not a distributed lease.

New host integration SHOULD use `FencedFinalHoldoutJournalV2` with a
`HoldoutOwnerContextV2` whose nonzero `writer_fence` comes from the host's
current writer-fence authority. Every `consume` call must pass a freshly
obtained current context. A stale context fails before storage mutation.

For multi-host production, the current fence and acknowledged anchor MUST be
owned by a transactional compare-and-swap authority or dedicated holdout
service. The local file cannot self-prove that it is the newest replica and
cannot defend against a hostile filesystem writer or a leaked/cloned raw file
handle. A fence rotation must move the current authority to a new generation;
old-generation journals may remain historical but are no longer current.

Before confirmatory labels or holdout results are released externally, the host
must durably acknowledge the returned anchor in that independent authority.

## Qualification evidence

The repository-controlled Lane E gate must execute, for the exact candidate and
the deterministic synthetic merge candidate:

- closed-world source/traceability verification;
- locked all-target compilation and strict lint;
- `codex-hepta-intelligence-eval` owner tests;
- the ignored durable holdout reopen/replay stress audit;
- signed evaluated-shadow end-to-end tests;
- the Lane E cross-crate causal chain;
- cross-language wire/fault tests;
- formatting and clean-tree checks;
- generation and retention of a commit-addressed qualification receipt.

The receipt binds the source/merge commit, tree, workflow/run identity,
production-contract digest, native-mapping digest, traceability digest and
qualification-input digest. Workflow identity is provenance metadata, not an
independent acceptance signature.

## Repository policy

The intended required check is **Hepta Lane E gap closure** (both exact-source
and synthetic-merge jobs). Repository branch protection/rulesets must require
that check on `main` and restrict bypass. Workflow source alone cannot enforce
a GitHub repository rule; branch protection is an administration-plane control.

## Completion boundary

Repository source closure may become current only after the exact-head and
synthetic-merge evidence for that commit are green and retained. The repository
must not self-close real future-calendar efficacy, independent semantic review,
product scheduler/runtime identity, independent selection, canary, promotion,
or release gates.
