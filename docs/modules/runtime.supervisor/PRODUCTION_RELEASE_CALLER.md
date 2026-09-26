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

The same context command is mandatory before a signed recovery decision. The decision binds the current lifecycle generation and current daemon-derived authority epoch. A daemon restart therefore invalidates a not-yet-submitted recovery decision, even if the durable release transaction is otherwise unchanged.

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

## Signed recovery through the same named caller

When the owner reports `RecoveryRequired`, ordinary `dispatch` and `recover` remain observation-only. They never choose a terminal outcome. The external authority reviews the exact quarantined owner state and signs a `production_recovery` request using the [offline signer ceremony](../../../codex-rs/hepta-supervisor/EXTERNAL_AUTHORITY_SIGNER.md#recovery-signing-ceremony).

Submit the complete tagged signer response through the same caller and the same original request/journal:

```text
hepta-supervisor-release-controller resolve-recovery \
  --fleet-root ABS_FLEET_ROOT \
  --request ABS_REQUEST_JSON \
  --journal ABS_EXISTING_JOURNAL \
  --decision ABS_SIGNED_RECOVERY_RESPONSE
```

The caller checks all of the following before dispatch:

- the decision binds the original Agent and grant;
- the outcome is legal for the original upgrade or rollback transition;
- the intent and `recovery_required` transaction digests match current owner state;
- the observed release is the release already recorded as durable current state;
- the current lifecycle generation and daemon authority epoch match the signed decision;
- the decision file is a bounded regular-file `production_recovery` signer response, not a grant or arbitrary JSON.

Immediately before the RPC, the caller durably records the exact decision digest and a `recovery_resolution_submitted` no-replay boundary. After that publication it never retransmits the recovery effect. A lost or cancelled acknowledgement is resolved only by observing owner evidence.

Terminal success requires a matching signed-intent result and release transaction. The transaction must:

- bind the original grant, Agent, source/target releases and original grant authority epoch;
- have the outcome-compatible terminal phase;
- bind the exact recovery decision digest;
- reconstruct the exact signed `recovery_required` predecessor transaction digest when projected back to that phase;
- carry the exact observed manifest, agentd and optional matrixd digests selected by the decision.

If the acknowledgement is lost, rerun `resolve-recovery` with the same request, journal and decision files. The caller first queries the owner. It accepts the already-terminal result only after the checks above and does not send another recovery RPC. Supplying a different decision for a journal that has crossed the no-replay boundary is a conflict.

Using ordinary `recover` after a recovery decision was submitted deliberately returns an indeterminate result and instructs the operator to use `resolve-recovery` with the exact signed decision. This prevents a generic status observation from silently bypassing recovery-decision audit verification.

## Retained owner results

Before replacing a previous terminal signed intent with a different grant, the existing signed-intent owner archives its exact terminal witness in:

```text
supervisor-signed-history-<grant-sha256>.json
```

Archives bind agent, grant, full intent and any matching release-transaction digest. They are bounded, integrity-checked, regular-file-only and create-only: a conflicting terminal for an existing grant is rejected. Current status never attaches an unrelated newer transaction digest to an older intent. `production_mutation_lookup` returns either the matching current intent or the exact retained terminal, never the status of a different grant.

At most 1,024 terminal archives of at most 16 KiB are admitted per Agent. Capacity exhaustion rejects admission of a new intent while retaining the previous current journal and all old results. It does not erase history, reset the restart budget or authorize an automatic cleanup. Long-term archive export/acknowledgement and safe reclamation remain a separate unqualified maintenance requirement.

Archive integrity is not current execution authority. A historical successful result cannot authorize a new release or make a revoked grant usable again.

## Abort versus successful reconciliation

The legacy recovery helper remains a deliberately narrower fail-closed path:

```text
hepta-supervisor-intent-recovery inspect --fleet-root ABS_FLEET_ROOT --agent AGENT_ID
hepta-supervisor-intent-recovery abort --fleet-root ABS_FLEET_ROOT --agent AGENT_ID --expected-intent-sha256 DIGEST
```

`inspect` is read-only. `abort` acts only on the exact normalized recovery-required intent and only after ambiguous main/Matrix processes are absent. It persists restart suppression, terminalizes matching existing owner journals as `Aborted` and clears replacement intent. It does not prove the source stayed active, the target succeeded, or either release is safe to serve.

Use `abort` when the operator cannot independently establish one exact durable release outcome or deliberately chooses to leave the Agent stopped. Use `resolve-recovery` only when an external authority can attest the exact committed/rolled-back owner state and immutable release digests. Neither command invents release state or starts a replacement as part of the recovery decision itself.

## Verification and evidence

`release_controller_tests.rs` covers full receipt binding, terminal stability with an unavailable daemon, journal corruption, competing writers/symlinks, exact recovery-decision binding, reconstruction of the pre-resolution transaction digest, durable no-replay audit state and tagged signer-output admission. `authority_signer.rs` signs and verifies recovery decisions and rejects a tampered authority epoch. `signed_history.rs` covers immutable retained results, conflicting terminal rejection and full-capacity preservation. `supervisor_signed_tests.rs` exercises real signed upgrade and rollback entry points and invalid authority before the durable effect boundary.

`tests/production_release_product.rs` invokes the actual signer, caller and Supervisor executables in separate processes. Its default native control-protocol child is a fixture, not Agentd. Set `HEPTA_SUPERVISOR_QUAL_AGENTD` to an actual built `codex-hepta-agentd` to qualify the real Agentd/App Server lifecycle. The test forwards a signed mutation through a bounded transport proxy, withholds its acknowledgement and SIGKILLs the caller. A fresh caller recovers by the original grant without retransmission. It then completes independently signed rollback, retains the previous grant result, SIGKILLs Supervisor, and verifies exact live-child adoption without another spawn. The emitted result identifies which backend ran, binary digest, observed PIDs, original grants and owner outcomes. Disposable test keys and no model turn are explicitly qualification conditions, not production deployment.

The exact-candidate `Runtime supervisor qualification` workflow executes the module validation script on source-head and prospective-merge candidates, retains command receipts and publishes a non-skipped `Runtime supervisor required` aggregate. Final acceptance still requires successful current-source runs, physical target-host restart/fault receipts and independently configured production signing policy. Merely compiling these entry points or passing fixture tests does not close deployment, operator acceptance, activation or release gates.
