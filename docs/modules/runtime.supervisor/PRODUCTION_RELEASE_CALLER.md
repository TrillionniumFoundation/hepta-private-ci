# Independently authorized production release caller

Status: executable source and qualification contract. Deployment, activation, release approval and independent acceptance are not implied by this document.

## Ownership and normal entry

`hepta-authority-signer` remains the independent signing tool. The Supervisor receives only configured public verifier keys. `hepta-supervisor-release-controller` receives a signed request, not private signing material, and owns only its request/delivery-observation journal. Fleet remains authoritative for admitted immutable release bindings; Supervisor remains authoritative for lifecycle and release transaction results. Agentd remains responsible for its own readiness, admitted-handler drain and task outcomes.

The production-authority build is explicit:

```text
cargo build --locked -p codex-hepta-supervisor --features production-authority --bins
```

Normal execution is context → independent authorization/signing → durable caller admission → signed Supervisor mutation → typed Agentd drain → immutable replacement → exact readiness → owner transaction terminal → caller terminal observation. It uses the existing release state machine; there is no alternative release kernel or locally minted authority.

## Atomic signing context

```text
hepta-supervisor-release-controller context --fleet-root ABS_FLEET_ROOT --agent AGENT_ID
```

`ProductionMutationContext` reads agent state, `control_revision` and daemon-derived `authority_epoch` under the same owner lock. These values are public fences, not authorization. The independent signer binds the source/target releases, expected lifecycle generation and control revision, authority epoch, H7 artifact, transition and validity interval into the existing signed grant. A changed context requires fresh independent authorization; callers must not rewrite and resign a grant themselves.

The additive read-only `production_mutation_context` and `production_mutation_lookup` methods do not change existing snapshot, mutation or status payloads. An older server rejects unknown methods. No old wire meaning is redefined.

## Request and journal binding

A `ProductionReleaseRequestV1` contains `schema_version`, `operation_id`, `agent_id`, `grant` and `h7_envelope`. Request bytes are bounded to 256 KiB. Operation identifiers are bounded to 128 ASCII bytes. Unknown fields and inconsistent agent, transition or artifact bindings are rejected.

```text
hepta-supervisor-release-controller dispatch --fleet-root ABS_FLEET_ROOT --request ABS_REQUEST_JSON --journal ABS_NEW_JOURNAL --wait-seconds 30
```

The caller canonicalizes the journal parent, rejects symlinks, acquires a regular-file sidecar lock, writes its canonical request/grant binding as `Prepared`, synchronizes the file and durably publishes the same-directory replacement before network dispatch. The journal includes a domain-separated integrity digest and bounded diagnostic error; it contains no private key. The lock is independent of the replaced data inode and prevents concurrent writers for the same canonical journal path.

A caller receipt must match the exact agent, grant digest, transition, source release, target release and expected control revision plus one. Matching only the grant digest is insufficient. `Prepared`, `Accepted`, `Indeterminate` and `RecoveryRequired` are never presented as successful release completion.

## Lost acknowledgement and restart

```text
hepta-supervisor-release-controller recover --fleet-root ABS_FLEET_ROOT --request ABS_REQUEST_JSON --journal ABS_EXISTING_JOURNAL --wait-seconds 30
```

Recovery queries the existing operation by its original grant digest. It does not retransmit a mutation, replace the request identity, create a new grant or infer rejection from a missing owner observation. A prepared-but-not-observed request remains indeterminate. The server bounds request-frame reads and response writes separately: expiration of a socket deadline does not cancel an already received lifecycle handler. The connection permit remains occupied until that handler finishes, so cancelled sockets cannot generate an unbounded population of detached resolver jobs. An existing completed caller journal returns its identical terminal result without querying an unavailable owner or downgrading to unknown. A duplicate `dispatch` of the same bound request takes this same recovery path; differing request bytes/semantics conflict.

Wait budgets are checked before dispatch and cannot exceed one hour. Waiting may return a nonterminal result; the CLI uses a nonzero exit for indeterminate or recovery-required outcomes; an accepted-but-pending result remains explicitly nonterminal. Consumers must inspect that result rather than treating process exit or accepted dispatch as effect success.

## Retained owner results

Before replacing a previous terminal signed intent with a different grant, the existing signed-intent owner archives its exact terminal witness in:

```text
supervisor-signed-history-<grant-sha256>.json
```

Archives bind agent, grant, full intent and any matching release-transaction digest. They are bounded, integrity-checked, regular-file-only and create-only: a conflicting terminal for an existing grant is rejected. Current status never attaches an unrelated newer transaction digest to an older intent. `production_mutation_lookup` returns either the matching current intent or the exact retained terminal, never the status of a different grant.

At most 1,024 terminal archives of at most 16 KiB are admitted per Agent. Capacity exhaustion rejects admission of a new intent while retaining the previous current journal and all old results. It does not erase history, reset the restart budget or authorize an automatic cleanup. Long-term archive export/acknowledgement and safe reclamation remain a separate unqualified maintenance requirement.

Archive integrity is not current execution authority. A historical successful result cannot authorize a new release or make a revoked grant usable again.

## Abort versus successful reconciliation

The offline exact-digest abort directive acts only on a normalized recovery-required intent and only after ambiguous main/Matrix processes are absent. It persists stop suppression, terminalizes matching existing owner journals as `Aborted` and clears replacement intent. It does not prove the source stayed active or the target succeeded. Independently signed committed/rolled-back reconciliation continues to use the existing `resolve_production_recovery` validator and live admission frontier.

## Verification and evidence

`release_controller_tests.rs` covers full receipt binding, terminal stability with an unavailable daemon, journal corruption and competing writers/symlinks. `signed_history.rs` covers immutable retained results, conflicting terminal rejection and full-capacity preservation. `supervisor_signed_tests.rs` exercises real signed upgrade and rollback entry points and invalid authority before the durable effect boundary.

`tests/production_release_product.rs` invokes the actual signer, caller and Supervisor executables in separate processes. Its default native control-protocol child is a fixture, not Agentd. Set `HEPTA_SUPERVISOR_QUAL_AGENTD` to an actual built `codex-hepta-agentd` to qualify the real Agentd/App Server lifecycle. The test forwards a signed mutation through a bounded transport proxy, withholds its acknowledgement and SIGKILLs the caller. A fresh caller recovers by the original grant without retransmission. It then completes independently signed rollback, retains the previous grant result, SIGKILLs Supervisor, and verifies exact live-child adoption without another spawn. The emitted result identifies which backend ran, binary digest, observed PIDs, original grants and owner outcomes. Disposable test keys and no model turn are explicitly qualification conditions, not production deployment.

Final acceptance requires actual current-source and applicable merge-candidate executions, physical restart/fault receipts and independently configured production signing policy. Merely compiling these entry points or passing fixture tests does not close those gates.
