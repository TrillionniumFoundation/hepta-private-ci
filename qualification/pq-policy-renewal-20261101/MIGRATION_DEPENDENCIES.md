# Normal PQ business-path dependencies

This is a source review, not a successful execution report. It supplements the
policy-renewal change and does not enlarge that change's accepted security scope.
The reviewed PQ tree is `0f7c63418a7eec6cff5e4348e8cdc733850f8386` (PR #4552).
The separate ordinary Cell tree is
`a6c58700d23efd575d2803637aa7d9203d27e7bf` (PR #4497).

## Ordinary Cell plus PQ FinalUse

The PQ tree already provides the ordinary host's explicit PQ authorizer route.
It would be incorrect to describe a new ML-DSA wrapper as the missing work.

| Existing boundary | Reviewed behavior | Source |
| --- | --- | --- |
| Ordinary qualified SmolLM host | Opens `UnixFinalUseAuthorizer` after original qualification/CURRENT and checks the authorizer profile against the selected artifact profile. | [smollm_cognitive_host.rs](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/0f7c63418a7eec6cff5e4348e8cdc733850f8386/codex-rs/hepta-infer-worker-host/src/smollm_cognitive_host.rs), blob `20fe75e7b23e5ce031eb105b84626e6d40a12669` |
| Configuration selector | Explicit `authentication_profile: "ml_dsa65_v2"` enters `from_pq_config`; another explicit profile is refused. The absent-field route retains classical compatibility. | [final_use_authorizer.rs](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/0f7c63418a7eec6cff5e4348e8cdc733850f8386/codex-rs/hepta-infer-worker-host/src/final_use_authorizer.rs), blob `6ba6f4da7e88974ce5b046437191d5f439a229c7` |
| PQ authorizer | Requires authenticated external clock and frontier replies before opening local authority state, sends a fresh request challenge, validates a schema-2 grant and signed revocation feed, and claims through the original authority. | [final_use_authorizer/pq.rs](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/0f7c63418a7eec6cff5e4348e8cdc733850f8386/codex-rs/hepta-infer-worker-host/src/final_use_authorizer/pq.rs), blob `8e0d6af2b5446d97d830eb2ef24a0dcc146cf2bb` |
| External trust clients | Signs/binds service replies to the exact fresh request and enforces the declared service key generation, identity, peer UID, frame bounds, and timeout. FinalUse and Learning use different frontier operations. A valid service signature alone does not establish independent operation or durable storage. | [authority_trust_unix.rs](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/0f7c63418a7eec6cff5e4348e8cdc733850f8386/codex-rs/hepta-contracts/src/authority_trust_unix.rs), blob `41771824974f6691dd6bf70e0081279e83254b3a` |
| Separate ordinary Cell entry | Adds pinned complete Cell material and one shared 120-second startup execution across qualification, Cell verification, and model load. It calls its tree's classical authorizer. | [smollm_cognitive_host.rs](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/a6c58700d23efd575d2803637aa7d9203d27e7bf/codex-rs/hepta-infer-worker-host/src/smollm_cognitive_host.rs), [smollm_neural_startup.rs](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/a6c58700d23efd575d2803637aa7d9203d27e7bf/codex-rs/hepta-infer-worker-host/src/smollm_neural_startup.rs) |

The next bounded composition task is to merge/adapt the ordinary Cell host with
the existing PQ host in one exact source tree. In particular, retaining the
ordinary Cell host alone would discard the PQ host's artifact/FinalUse profile
match, while retaining the PQ host alone would discard the complete Cell route
and the shared startup execution. Both behaviors must survive conflict resolution.

The external configuration requires actual issuer, clock, and frontier socket
endpoints; their pinned identities, peer UIDs, ML-DSA keys and generations;
canonical protected paths; issuer and revocation-distributor identities; an
authenticated initial revocation head; and independently retained frontier
state. `PqFinalUseAuthorizerConfig` and `UnixPqTrustEndpointConfig` define the
concrete fields. The reviewed authorizer refuses trust endpoints equal to the
issuer endpoint or inside its local authority-state directory; it does not
establish operator or failure-domain independence merely by path comparison.

The existing
[PQ authorizer test](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/0f7c63418a7eec6cff5e4348e8cdc733850f8386/codex-rs/hepta-infer-worker-host/src/final_use_authorizer/pq_tests.rs)
uses actual Unix IPC and production authorizer code with test-owned clock,
frontier, and issuer services. It exercises valid claims, rejection, resumed
claims, and reopening spent-nonce state. Its fixed test clock and test service
keys are fixtures; they are not supplied production authorities, independent
deployments, or evidence that the ordinary Cell product completed a run.

A combined candidate still needs a successful, observed normal product route:
original qualification and CURRENT selection, complete Cell verification,
actual authorized model load, ordinary cognitive read, and observed terminal
unload. Negative controls must cover artifact/FinalUse profile mismatch,
classical grants in the PQ profile, invalid or stale trust-service replies,
revocation, stale authority/frontier state, and service recovery followed by a
successful new operation. These controls must use the original capacity and
startup deadlines. Separate branch test results cannot qualify the combined
tree. Settlement and publication need their own original-owner acceptance;
passing the inference route does not establish them.

## Versioned ObjectiveStart and RunStart

This migration crosses the ingress, composition owner, durable journal, and
recovery anchor. Removing `require_run_start_v1()` would not implement it.

| Owner or boundary | Exact remaining dependency | Source |
| --- | --- | --- |
| Objective wire | `AuthBusObjectiveIngress` has no `auth_version` field. The text wire's PQ version support does not version this separate objective message. Producer and consumer must agree on explicit PQ domains and signature representation. | [hepta-agent-protocol/src/authbus.rs](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/0f7c63418a7eec6cff5e4348e8cdc733850f8386/codex-rs/hepta-agent-protocol/src/authbus.rs), blob `fb1fcaf518634c6ef82e17cde8d92f24a844b348` |
| Active Agentd path | `objective_runtime.rs` calls `require_run_start_v1`, parses a 64-byte signature, constructs `RunStartAuthenticationV1`, and calls the V1 intelligence publication API. Its current-authentication check also requires V1. | [objective_runtime.rs](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/0f7c63418a7eec6cff5e4348e8cdc733850f8386/codex-rs/hepta-agentd/src/objective_runtime.rs), blob `3888aed612d568852c14c00640a3278334804634` |
| Intelligence composition | `ObjectiveRunBindingsV1` contains `RunStartAuthenticationV1`. Both successful/abstaining objectives and durable hard-conflict records consume this authentication. Migrating only the success branch leaves another authenticated state transition unversioned. | [objective_run.rs](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/0f7c63418a7eec6cff5e4348e8cdc733850f8386/codex-rs/hepta-intelligence/src/objective_run.rs), blob `a2f361edbf1e0f8fd1024d085edcd71b4f2396f0` |
| Journal owner | `RunStartAuthenticationV1.signature` is `[u8; 64]`; normal and conflict record encoders/decoders store this fixed shape. The existing `hepta.run-start-record.v2` domain is already used for the classical record's protocol extension and must not be relabeled as PQ. | [hepta-learning-ledger/src/run_start.rs](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/0f7c63418a7eec6cff5e4348e8cdc733850f8386/codex-rs/hepta-learning-ledger/src/run_start.rs), blob `e93f1208bddd3dba92a7eecf06873a3feff949e9` |
| Recovery | The journal offers `RunStartRecovery::Acknowledged(RunStartAnchor { sequence, chain_digest })`, but the active host opens/reopens its journal with `RunStartRecovery::Unacknowledged`. An internally consistent old journal is not evidence of the latest acknowledged state. | Same `run_start.rs` and `objective_runtime.rs` sources above. |
| External anchor | The reviewed `PqTrustOperationV2` includes clock, FinalUse frontier and Learning frontier operations, but no RunStart-anchor load/CAS operation. Existing frontier types cannot silently serve as a differently owned journal anchor. | Same `authority_trust_unix.rs` source above. |

The active module is `objective_runtime`; the old `objective_ingress.rs` and
`objective_dispatch.rs` files are not declared as modules in the reviewed
[Agentd library](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/0f7c63418a7eec6cff5e4348e8cdc733850f8386/codex-rs/hepta-agentd/src/lib.rs).
Editing only those files would not move the ordinary runtime path.

A coherent migration must preserve classical-record decoding without allowing a
classical record to satisfy the selected PQ profile. It needs distinct PQ
authentication and record domains, normal and conflict replay semantics,
sequence/idempotency handling, authenticated epoch/revocation rechecks, journal
append/anchor-acknowledgement crash handling, and the original seven-owner
handoff's recovery behavior. The acknowledged anchor must be independently
retained and authenticated; copying it into the same rollback domain does not
close whole-state rollback.

The required positive control is a legal PQ objective reaching its intended
original-owner operation and surviving a valid restart, including the
hard-conflict and explicit-abstain journal outcomes where appropriate. The
negative controls need classical/PQ cross-profile rejection, stale epoch and
revocation rejection, rollback and interrupted-commit recovery, and a later
valid operation succeeding after rejection. Journal limits, deterministic
objective semantics, and the original authority-denying compilation posture
must remain intact.

## Scope of this candidate

The delivered policy-renewal patch closes the selected-policy/SQLite-renewal
window and wires the actual text dispatcher to the policy-bound API. It does
not implement either cross-tree Cell composition or the versioned RunStart
protocol above. Those paths remain separate acceptance work, and no native
success or independently deployed trust service is inferred from this review.
