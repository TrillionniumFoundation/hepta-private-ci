# learning.eval production contract

This file is the normative production-use contract for
`codex-hepta-intelligence-eval`. It does not grant selection, promotion,
release, filesystem, network or external-effect authority. Where descriptive
documents conflict with this file about which evaluation entry point may admit
external evidence, this file wins.

## 1. API status

| Surface | Status | Allowed use |
| --- | --- | --- |
| `evaluate_legacy_inprocess_v1` | private legacy | crate-local compatibility fixtures only |
| `decide_independently` | trusted-only compatibility | deterministic in-process composition and qualification fixtures; not an external/production ingress |
| `decide_independently_v2` | trusted-only compatibility | deterministic in-process composition with preregistered metric roles; not an external/production ingress |
| `decide_with_signed_evidence_v1` | compatibility external admission | qualification-scoped historical callers only; no `SystemLongitudinal` claim |
| `decide_with_signed_evidence_v2` | production-required | external `Qualification` claims with preregistered metric roles |
| `decide_with_signed_longitudinal_evidence_v3` | production-required | external `SystemLongitudinal` claims with signed observed-time evidence |

A production caller MUST NOT treat `AuthenticatedPrincipalV1` fields alone as
proof of identity. Production admission MUST construct a
`LearningEvidenceVerifierV1` from the independently provisioned trust set and
MUST verify the generator-plan and evaluator-bundle signatures before an
eligibility decision is consumed.

The only current product-facing composition mapped by this repository,
`codex_hepta_intelligence::run_evaluated_shadow_v1`, uses signed V2 evaluation
and separately signs the exact candidate bytes/generation. Source CI verifies
that this consumer continues to use the signed path.

## 2. Qualification semantics

Eligibility is evidence for an independent selector. It is never promotion.
Every independent decision MUST continue to emit
`AuthorityPosture::DENY_ALL`.

The preregistered production path freezes:

- objective, dataset and estimand digests;
- candidate and baseline identities;
- complete metric contracts and V2 metric roles;
- family alpha and simultaneous-comparison count;
- cross-fold lineage and final-holdout identity;
- support, confidence, retention and unlearning evidence;
- generator/evaluator identities and the signed request payload.

Any semantic change after plan freeze requires a new plan digest and consumes a
new admissible holdout scope.

## 3. Identity and trust boundary

Generator and evaluator independence is accepted externally only after signature
verification. The verifier must bind the configured signer to the claimed
principal and authorized role, then enforce principal, credential-chain and
signing-key separation. Display names, role strings or locally supplied identity
digests are not sufficient production evidence.

Direct unsigned decision functions remain useful deterministic cores. They are
not admission boundaries and MUST NOT be called by production ingress code.
The Lane E source verifier rejects new production-source callers of those direct
entry points outside the evaluation crate and explicit qualification fixtures.

## 4. Durable final-holdout ownership

`DurableFinalHoldoutJournalV1` is a single-host/cooperating-owner durable
journal. Its OS file lock does not authenticate writers and does not, by itself,
provide linearizable multi-host ownership.

A multi-host product MUST place the journal behind a linearizable external fence
that supports compare-and-swap. The repository-provided
`FencedFinalHoldoutOwnerV1` reserves a plan in that fence before mutating the
journal and commits the new anchor only after the journal is synchronized.
A failed or ambiguous fence transition fails closed and leaves the reservation
pending for explicit reconciliation; another host cannot silently reuse that
holdout.

The external fence owner is responsible for:

- authenticated caller identity and authorization;
- monotonic epoch/currentness;
- linearizable compare-and-swap;
- durability independent of journal backups and host snapshots;
- restore policy that cannot move the acknowledged fence backward;
- operational reconciliation of pending reservations.

A local filesystem lock is not a substitute for those properties.

## 5. CI evidence and provenance

Repository-controlled source closure requires the
`Hepta Lane E gap closure / rust-closure` check at the exact candidate head and
the ordered-parent synthetic-merge job on pull requests.

The workflow must retain a commit-addressed
`learning-eval-evidence.json` artifact containing at least:

- source commit SHA and tree SHA;
- workflow/run build identity;
- deterministic test-input digest;
- Lane E traceability and production-ingress coverage digests;
- bounded durability/signed-admission stress iteration count;
- generation timestamp and expiry;
- signer identity.

The test job emits the commit-addressed JSON without OIDC privileges. Pull-request
code never receives `id-token: write`. After the same workflow's exact-main
`rust-closure` job succeeds on a trusted `push`, a separate `sign-evidence` job
checks out that exact SHA, re-verifies the closed world, checks the JSON's
commit/tree/run binding, then keylessly signs it with the repository's existing
Sigstore cosign action and uploads the JSON together with its `.sigstore` bundle.
The signature proves the GitHub Actions workload identity that signed the
artifact; it does not convert repository tests into independent scientific or
production acceptance evidence.

## 6. External gates

Repository CI may close repository-controlled source gaps only. It MUST NOT
self-issue:

- live authenticated product outcomes;
- real future-calendar efficacy or retention observations;
- target-host/device measurements;
- privacy/subgroup approval;
- independent semantic/operator acceptance;
- canary, selection, promotion or release decisions.

Those gates remain external exact-candidate evidence and are intentionally
represented as open in the Lane E implementation matrix.

## 7. Required repository governance

For a protected production branch, repository administrators must require at
least the Lane E gap-closure check and the repository's ordinary blocking CI,
disallow force-push/deletion, and restrict bypass to the organization's explicit
break-glass policy.

This repository source records the required check names but cannot turn a GitHub
branch/ruleset administrative setting on by itself. A branch that reports
`protected=false` is not governance-closed even when all source checks pass.
