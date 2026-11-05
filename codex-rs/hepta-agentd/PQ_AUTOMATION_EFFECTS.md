# Ordinary automation effects: explicit PQ host schema 4

This composition is selected by Agentd's existing
`--automation-effect-host-file /absolute/owner-supplied.json` option. The ordinary
loader now requires schema 4 and the `MlDsa65V2` authentication profile. Schema 1
HTTP and schema 3 PoN configurations are rejected. Their signing formats and
explicit historical qualification constructors remain available to existing
component controls; they cannot be selected by the ordinary loader.

This document specifies inputs and migration behavior. It does not supply root
keys, grants, a qualified model, independent custody, or provider qualification.
The loopback and Unix-service test fixtures are not production configuration
producers.

## Owner-supplied inputs

The host JSON has these fields; it denies unknown fields. Public key material
uses the existing `PqAuthorityTrustKey` and `UnixPqTrustEndpointConfig` wire types.
Signatures are byte arrays, not an inferred profile selected by signature length.

| Field | Required meaning |
| --- | --- |
| `schema_version` | `4` |
| `authentication_profile` | Serialized `FinalUseAuthenticationProfile::MlDsa65V2` |
| `agent_id`, `spawn_generation` | The actual Agentd owner and current spawn generation |
| `provider_scope`, `destination_id` | The existing stable provider namespace and destination |
| `contract_id`, `contract_authority_epoch` | Explicit contract identity and current authority epoch |
| `contract_root` | Independently supplied ML-DSA-65 contract-root SPKI, canonical key ID, role ID and epoch window |
| `provider` | The HTTP or PoN object described below |
| `authority` | The current grant, revocation, protected-time and independent-frontier policy described below |
| `recovery_provider_policies` | Optional list of at most eight exact historical policy references; default empty |
| `final_use_scope_sha256` | Exact immutable owner-policy digest computed below |
| `contract_signature` | Contract root's ML-DSA-65 signature of the distinct PQ statement below |

An HTTP `provider` has `kind: "http"`, `dispatch_url`,
`lookup_url_template` with the original `{key}` placeholder, `headers`, and
`timeout_ms`. A PoN `provider` has `kind: "pon"`, `chain_binary`,
`chain_binary_sha256`, `chain_store`, `chain_state_backend`,
`chain_genesis_time`, `chain_evaluation_policy`, `chain_task_profile`,
`chain_model_profile`, `chain_workers`, `chain_min_confirmation_depth`,
`chain_min_confirmation_work_depth_hex`, and `timeout_ms`. The original header,
timeout, worker, confirmation, pinned-binary and canonical-store limits remain.
The provider kind and all parameters are included in the signed owner policy. Schema 4
current/historical policy files and signed feeds have a 256 KiB read ceiling;
the legacy host-file ceiling was 64 KiB. This is an explicit new-schema capacity,
not a claim that every resource bound is unchanged.

The `authority` object has `signer_id`, `issuer_keys`, `head`,
`revocation_distributor_id`, `revocation_keys`, `signed_revocations_file`,
`external_clock`, and `external_frontier`. Issuer and feed key rings each contain
one to eight keys. The contract, issuer, feed, clock and frontier roles use
distinct public keys. Clock and frontier socket paths are distinct. All three
current trust paths are absolute and canonical and remain outside the Agentd
fleet, home, run and workspace roots. The original Unix protocol authenticates
the peer UID, service ID, key generation, challenge and signed response.

The independently operated frontier service must already hold the exact
FinalUse frontier for the owner. For a fresh PQ authority, its initial value is
`FinalUseFrontier::for_initial_head_with_profile(head, MlDsa65V2)`. Agentd does
not create a service, provision this external value, choose root keys or sign
its own grants. The current signed revocation feed must authenticate the exact
initial `head`, be fresh under protected time, and use the configured PQ feed
profile. Signature, freshness and exact-head checks precede local authority
creation. An existing authority still requires the original exact durable-head
and external-frontier reopen checks; disagreement is an error, not a reset.

## Producing the signed policy with the existing owner

Use the implementation's `HostV4::scope` serialization as the normative byte
contract. It is SHA-256 of the domain
`hepta.agentd.effect-owner-policy.pq.v4\0` followed by compact `serde_json`
encoding of the explicit object in that method. JSON object keys use the
existing sorted-map encoding; array order remains significant. The object binds
profile, owner, spawn generation, provider scope and destination, contract ID
and epoch, complete contract-root record, full provider object, signer ID and
issuer keys, distributor ID and feed keys, signed-feed path, both complete
external endpoint configurations, and recovery references. The mutable
revocation `head`, `final_use_scope_sha256` itself and `contract_signature` are
excluded. An absent recovery list is normalized to an empty array.

For HTTP, compute the original `HttpProviderEffectConfig::contract_sha256`,
which binds the exact HTTP contract, endpoints, headers and timeout. For PoN,
SHA-256 the domain `hepta.agentd.pon-provider-contract.pq.v3\0` followed by the
compact JSON serialization of `ProviderV4::Pon`. Have the existing externally
controlled contract owner sign the bytes returned by
`HttpProviderEffectContractAttestation::statement_for_pq`:

```text
hepta-provider-effect-attestation-pq-v2
role=automation-provider-contract
contract_id=<bounded contract ID>
contract_sha256=<computed provider contract digest>
authority_epoch=<current epoch>
authority_binding=<computed immutable owner-policy scope>
```

The statement ends with a newline. Populate the digest and signature only after
all policy fields and references are fixed. The ordinary host verifies the real
ML-DSA-65 signature, root pin and epoch window; classical signatures and the old
contract signing domain do not satisfy this verifier.

The grant owner issues the existing schema-2 `FinalUseGrant` for the exact
intent and wire-payload binding, including this current scope. Its lifetime must
fit inside the currently authenticated signed feed's lease. The ordinary entry
checks the current Agentd admission generation, signed feed, epoch, protected
time and independent frontier before work and after awaited durable work,
immediately before provider contact. Original nonce claiming, active-effect
revocation fencing and durable attempt recording remain authoritative. A feed
change while an effect is active can return `DispatchInProgress`; it is not
ignored to force a send through.

## Restart, migration and unknown effects

The PQ authority uses the new `final-use-authority-pq-v2` directory within the
Agentd automation root. Do not copy, rewrite or relabel the classical authority
store. The PQ constructor rejects classical stores and grants. Operator policy
and signed-feed transitions must agree with the original durable owner's head
and independent frontier; conflicting or unavailable material holds admission.
In particular, this loader does not reset a durable head to make a newer feed
fit an old snapshot. A failed reopen needs the existing authority's validated
recovery/transition procedure, not a replacement root or an emptied nonce set.

Provider operation keys remain the original owner/run/step keys. They do not
change when a grant, authority policy or Agentd generation changes. A lost ACK
remains an unknown effect; an absent status result never authorizes another
physical send. A boundary refusal before provider contact retains the original
ProvenAbsent semantics and the already-consumed nonce. A refusal after an
uncertain send leaves the prior unknown effect intact.

To query an older PQ operation after restart, the current signed configuration
may include a `recovery_provider_policies` entry with an absolute canonical
`path` and the raw-file `sha256` of its original schema-4 host JSON. The current
contract root signs these references as part of its new scope. The loader first
checks those exact bytes, verifies the old scope and PQ contract signature,
then requires the same Agent, provider namespace, destination and complete
provider configuration. Historical scope authorization permits only recovery
lookup of the original durable operation. Dispatch accepts only the current
scope and current generation.

Historical feed/socket paths need not remain available. They are signed policy
content, not current trust endpoints. Historical references are not followed
recursively. Changed endpoints, headers, timeout, binary pins or PoN stores
cannot be substituted to query a pending operation through a different provider.
Without an authenticated matching reference, old pending operations stay held.
Old schema-1/schema-3 unknown records are not automatically migrated or retried.

Every new external status lookup or PoN observation checks the current owner,
PQ feed, epoch and independent frontier again. Reading an already durable
terminal receipt does not manufacture a new observation: if optional current
PoN observation is unavailable, that receipt is returned with no chain
observation. These local checks do not make a provider action atomic with an
external revocation service or eliminate the cross-store crash window. Real
root custody, complete restore, real-provider lost-ACK/crash windows and the
ordinary deployed input set still require joint qualification.
