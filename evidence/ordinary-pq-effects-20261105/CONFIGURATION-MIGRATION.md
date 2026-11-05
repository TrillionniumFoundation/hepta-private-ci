# Ordinary effect authority configuration migration

This document describes the implementation at Hepta `ee57cd57c322a8fecdf674a662c741452baf6478`. It is a configuration contract, not a record of production provisioning. Native execution evidence is recorded separately in this directory.

## Compatibility and ownership

Ordinary `AgentdAutomationEffectHost::open` now requires schema **4** and an explicit **`ml_dsa65_v2`** authentication profile for both `http-v1` and `trillionnium-pon-local-v1`. Legacy HTTP schema 1 and PoN schema 3 are rejected before preparing the provider, contacting external trust services or opening the FinalUse owner. There is no production classical fallback. Legacy loaders remain available only to explicitly named test fixtures.

This is a deliberate startup compatibility change for existing ordinary effect configurations. Changing only the schema or profile string is insufficient: the contract, issuer and revocation authorities must be valid ML-DSA-65 authorities, and the retained owner must agree with its externally registered frontier. The existing classical owner directory must not be renamed, copied or reinitialized to manufacture that agreement. This change does not provide a production migration tool for classical consumed-nonce history. Retained effects and uncertain provider outcomes still require their original reconciliation procedure before any separately authorized migration can be qualified.

The daemon's existing automation effect configuration path remains the entry point. The state owner remains `automation_root()/final-use-authority`, the original AutomationStore owns durable intent and provider attempts, and the original provider adapters own dispatch and reconciliation. No new grant wire type, dependency or lockfile change is introduced.

## Required schema 4 fields

The loader rejects unknown fields. Rust byte vectors and fixed-size byte arrays use their existing Serde JSON representation; an Ed25519 32-byte verifying key is not a substitute for a pinned ML-DSA-65 SPKI.

| Field | Required value or binding |
| --- | --- |
| `schema_version` | Integer `4`. |
| `authentication_profile` | Exact string `ml_dsa65_v2`. |
| `provider_scope`, `destination_id` | Existing bounded identifiers used by stable provider identity and effect destination admission. |
| `final_use_scope_sha256` | Exact scope digest used by the effect intent and FinalUse binding. |
| `provider` | A tagged `http-v1` or `trillionnium-pon-local-v1` object, with the fields below. |
| `contract_id`, `contract_sha256` | Identifier and digest of the configured provider contract. |
| `contract_authority_epoch` | Nonzero epoch matching the configured FinalUse head and, at admission, the signed revocation feed and grant. |
| `contract_signature` | ML-DSA-65 signature over `HttpProviderEffectContractAttestation::statement_for_pq(...)`. |
| `contract_key` | Pinned `PqAuthorityTrustKey`, including canonical public SPKI, exact public-key ID and allowed authority-epoch interval. |
| `final_use.signer_id` | Exact FinalUse owner identifier already registered with the external frontier service. |
| `final_use.issuer_keys` | One to eight pinned PQ issuer trust keys. |
| `final_use.head` | `FinalUseRevocations`: `authority_epoch`, `revision`, `revoked_grant_ids`. This configured head is not a replacement for an authenticated current feed. |
| `final_use.revocation_distributor_id` | Exact distributor identity expected by the signed-feed verifier. |
| `final_use.revocation_keys` | One to eight pinned PQ revocation-distributor trust keys. |
| `final_use.signed_revocations_file` | Absolute path to a protected, bounded `SignedFinalUseRevocationUpdate` file. Unsigned head JSON is rejected. |
| `final_use.external_clock` | Existing `UnixPqTrustEndpointConfig` for authenticated protected time. |
| `final_use.external_frontier` | Existing `UnixPqTrustEndpointConfig` for retained FinalUse frontier load and compare-and-set. |

Each external endpoint carries `socket_path`, `peer_uid`, `service_id`, `key_generation`, `public_key_id`, `public_key_spki` and `timeout_ms`. Socket paths must be absolute, canonical, distinct and outside the local FinalUse owner directory. The two services and the contract, issuer and revocation roles must use distinct actual SPKI bytes. Distinct labels on the same key do not pass this check. Operational custody and persistence outside rollbackable state still require deployment evidence; a successful signed response alone does not establish those properties.

The clock must answer and the external frontier must already contain the requested owner. Missing registration or service unavailability fails closed. The loader does not bootstrap a frontier from local configuration.

The configuration file is limited to 256 KiB. This allowance accommodates PQ key/signature material; it does not increase control-frame or effect-payload budgets. On Unix, protected files must be regular, canonical, non-symlink files with no group/other permissions, one hard link, matching opened/named file identity, and the same owner as a parent directory that is not group/other writable. Contents are read through the same bounded descriptor used for metadata checks. These checks do not claim to eliminate every same-owner filesystem race.

## Provider contract signing

The new attestation uses the exact V2 statement returned by the public helper:

```text
hepta-provider-effect-attestation-v2
authentication_profile=ml_dsa65_v2
contract_id=<contract_id>
contract_sha256=<contract_sha256>
authority_epoch=<authority_epoch>
```

The final newline is part of the statement. Use `statement_for_pq` rather than reconstructing or normalizing the bytes. Verification uses pure ML-DSA-65 with the canonical empty context through the existing pinned-SPKI verifier. V1 statements and signatures retain their original bytes and cannot satisfy the ordinary PQ gate. The verified profile is set only by successful verification.

For HTTP, `provider` contains `provider_kind: "http-v1"`, `dispatch_url`, `lookup_url_template` and `timeout_ms`. `headers` is optional and defaults to an empty map. The existing `HttpProviderEffectConfig::contract_sha256()` codec is unchanged. Endpoint, header or timeout changes require recomputing and resigning that contract. HTTP timeout remains between 1 and 30,000 ms, and existing header limits still apply. This local contract signature does not change the remote server's transport authentication or receipt-signing algorithms.

For PoN, `provider` contains `provider_kind: "trillionnium-pon-local-v1"` and these existing provider settings:

```text
chain_binary, chain_binary_sha256, chain_store, chain_state_backend,
chain_genesis_time, chain_evaluation_policy, chain_task_profile,
chain_model_profile, chain_workers, chain_min_confirmation_depth,
chain_min_confirmation_work_depth_hex, timeout_ms
```

The PoN contract digest is SHA-256 over the exact domain bytes `hepta.agentd.pon-provider-contract.pq.v3\0`, followed by the existing Serde JSON encoding of `{provider_scope, destination_id, final_use_scope_sha256, provider}`. Reproduce the serialization in the loader and signed fixture; arbitrary JSON whitespace or a different serializer is not an interchangeable signing format. All binary, path and policy fields are covered by the provider object. The loader verifies the real pinned binary and requires an existing canonical Node namespace with `native.sqlite`. State backend, worker-count, confirmation and timeout limits remain enforced. This contract does not make legacy Chain task/evaluation profiles PQ.

## Admission, renewal and recovery behavior

Each new effect admission verifies the signed revocation feed using protected time. The grant must use PQ schema 2; grant, feed and contract epochs must agree; grant expiration must not exceed the authenticated feed expiration. A lease binds the exact authenticated head and expiration. Production drivers must carry that lease and check it before dispatch and again inside the worker before provider contact. There is no optional production lease path.

Epoch renewal therefore also requires a valid contract at the new epoch and a compatible ordinary-owner configuration. An old contract does not acquire a new epoch merely because a later revocation feed arrives. Key and owner migration must preserve the existing monotonicity and consumed-nonce requirements; resetting local state is not renewal.

An effect can consume its nonce and then be refused before provider contact if the authority head changes. The nonce is not refunded. Unknown provider outcomes retain the original reconcile-only path; they do not authorize another dispatch.

An exact durable terminal receipt is read after owner/intent validation and before obtaining a fresh feed lease. This allows the caller to read a previously completed result after later revocation, grant expiry or service loss. Altered intent, payload or command identity does not receive that receipt. Historical readback grants no new authority and makes no claim of Chain finality.

Cold opening of the ordinary host still requires the clock and external frontier to answer. The executed HTTP test first reopens the owner successfully, then removes clock/frontier availability before reading the exact terminal receipt. Its HTTP provider remains observable and its request count stays one. The actual Chain provider-unavailability assertion was not reached because the new real-Chain case failed earlier at the unchanged wire limit. They do not establish successful cold startup while those trust services are unavailable.

## Separate native neural test input correction

Native Agentd lint compiles integration test targets and exposed two existing initializers that had not supplied the required `SmolLmNeuralReadConfigV1.runtime_snapshot` field. These corrections are test-harness changes, separate from ordinary effect schema 4:

- The explicit comparison fixture selected by `HEPTA_PN3_NEURAL_COMPARISON_CONFIG` now requires `schema: "hepta-smollm-neural-comparison-native-v2"`, an absolute `runtime_snapshot` path and `runtime_snapshot_sha256`. It reads at most 16 MiB plus one byte and rejects empty, oversized or digest-mismatched inputs. It uses the complete existing 13-file source-pin set. The snapshot must be pinned before the comparison; there is no capture-at-load fallback or empty successful substitute. Existing external v1 fixture inputs need a separately prepared v2 input before that experiment can run.
- The existing qualification-rejection case supplies explicitly invalid, nonempty snapshot bytes. Its original assertions still require refusal at the untrusted qualification boundary before creating inference, worker or material state. It does not manufacture a valid runtime snapshot.

Neither correction demonstrates a successful real-model comparison. Model, task, generation-count and evaluation assertions and the existing workload budgets are unchanged. The ordinary effect verification does not grant execution credit to the separate neural campaign.

## Source references

- [Ordinary PQ loader and dispatch lease](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/ee57cd57c322a8fecdf674a662c741452baf6478/codex-rs/hepta-agentd/src/automation_effect_host_pq.rs)
- [Original effect owner, durable readback and worker dispatch](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/ee57cd57c322a8fecdf674a662c741452baf6478/codex-rs/hepta-agentd/src/automation_effect_host.rs)
- [Versioned PQ contract attestation](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/ee57cd57c322a8fecdf674a662c741452baf6478/codex-rs/model-provider/src/provider_effect_pq.rs)
- [Existing authenticated Unix trust endpoint types](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/ee57cd57c322a8fecdf674a662c741452baf6478/codex-rs/hepta-contracts/src/authority_trust_unix.rs)
- [Signed configuration fixtures](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/ee57cd57c322a8fecdf674a662c741452baf6478/codex-rs/hepta-agentd/src/automation_effect_host_pq_fixture.rs)
- [Native neural comparison input](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/ee57cd57c322a8fecdf674a662c741452baf6478/codex-rs/hepta-agentd/tests/support/neural_native_owner.rs) and [comparison selector](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/ee57cd57c322a8fecdf674a662c741452baf6478/codex-rs/hepta-agentd/tests/neural_comparison_native.rs)
