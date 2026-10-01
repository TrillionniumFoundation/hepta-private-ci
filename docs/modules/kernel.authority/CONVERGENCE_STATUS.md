# kernel.authority convergence status

**Status date:** 2026-10-01

**Immutable source anchor:** `5a6e7cda38e8e5513babe48b9783dd7947446a4f`

**Source tree:** `f9aa5a8200bfd9627b251138bbf1e4d065f16e20`

**Machine manifest:** `qualification/kernel-authority/convergence_manifest.json`  
**Validator:** `qualification/kernel-authority/convergence_acceptance.py`

This page is the source-bound overlay for the remaining convergence work. It is
not a production acceptance receipt. The manifest and validator deliberately
keep source composition, exact native execution, target-host qualification,
independent acceptance, activation and release as different facts.

## Reading order

1. `TECHNICAL.md` — stable ownership, state, ordering and failure contracts.
2. This page — latest source-bound convergence facts after the canonical feed
   clock, typed production bootstrap and executable port-acceptance changes.
3. `CURRENT_IMPLEMENTATION.md` and `TRACEABILITY.md` — generated source maps.
4. `PORT_MATRIX.md` — declared target-port source maturity.
5. `CAPACITY_QUALIFICATION.md` and `HOT_PATH_DECISION.md` — measurement and
   optimization policy.

No document grants authority that the corresponding exact-candidate and
external evidence gates have not granted.

## Invariants retained

The convergence work keeps one authoritative lease/final-use owner. It does not
add an adapter-owned authority database, a second execution path, or a test-only
owner that differs from the product owner.

The following boundaries remain mandatory:

- the registry and FinalUse owner hold the authoritative lease, nonce,
  revocation and frontier facts;
- parent revocation, epoch change and owner retirement propagate through the
  existing lifecycle rather than through caller caches;
- authority is re-read immediately before the irreversible boundary;
- nonce consumption, revocation convergence, provider attempt identity and
  terminal observation remain durable;
- missing, stale, rolled-back or inconsistent trust material fails closed;
- cancellation after the effect boundary cannot erase the obligation to retain
  and reconcile the terminal outcome.

## Remaining-four convergence matrix

| Area | Source state at the anchor | Exact native execution | Production/target acceptance |
|---|---|---|---|
| Trusted-clock type and ownership | **Closed in source.** Agentd re-exports the canonical `codex_hepta_contracts::FinalUseFeedClock`; compatibility and production paths no longer carry independent feed-clock implementations. `AgentdAutomationEffectHost` retains the refresh clock, feed-admission clock and single FinalUse owner. | Required. The exact-head and fixed synthetic-merge native checks, strict Clippy and two-product-process recovery receipt must succeed for one immutable candidate. Repository source inspection does not mark them passed. | Not granted by source. A selected production clock still needs independent uncertainty and rollback evidence. |
| Production trust bootstrap | **Closed as a typed entry point.** `AgentdProductionAuthorityBootstrap::from_trust_bundle` accepts one complete validated `ProductionAuthorityTrustBundle`; `FleetAuthorityPort::open_production` uses the same trust-bundle contract. Host/request data cannot manufacture the production context. | Required. The selected ordinary product composition must execute the production entry point, not only construct it in a fixture. | **Open.** No repository file invents a KMS/HSM, attested clock or rollback-independent CAS. Ordinary deployment-provider wiring and its external evidence remain false. Compatibility construction is not production. |
| Executable target-port acceptance | **Closed as an evidence projector.** `port_acceptance.py` reopens content-addressed raw native and two-process logs, binds them to the candidate, and emits per-port source, native-pilot, process-recovery, lifecycle-obligation and production-acceptance fields. | Required per declared port. A source callsite alone is insufficient; missing, renamed, ignored, zero-test or contradictory execution remains failure. | **Open.** Unproved lifecycle obligations and every production-acceptance field remain false. Independent target/operator acceptance is external. |
| Measured hot path and capacity | **Collector and policy source exist.** The target workflow pins the exact candidate, protected host driver, independent policy and collector identities; it requires 55 measurement rows, eight fault rows, 25 diagnostics and complete artifact hashing. | Repository tests may validate the collector and policy parsers, but they cannot stand in for the real self-hosted collection. | **Open.** No runtime optimization, production SLO, activation or release is authorized until a real selected target host produces and independently accepts the envelope. |
| Source-bound status and evidence | **Closed for the source facts listed here.** The convergence manifest pins the immutable source commit/tree and a closed list of tracked source paths. The validator rejects source drift and all repository self-grants. | The validator proves only source consistency. Exact native runs remain separate Actions evidence. | All production, target, acceptance, activation and release fields remain false. |

## Trusted-clock and recovery ownership

`FinalUseFeedClock` is now the sole signed-feed admission-clock implementation
used by the Agentd authority composition. A feed replacement clears the prior
window before authority mutation and publishes the new interval only after the
signed update is accepted. Clock failure, feed expiry or invalidation cannot
resurrect the previous interval.

The production bootstrap retains a live production bundle and binds the exact
issuer key set while opening the existing effect owner. It does not export key
bytes and it does not transform the local `AgentdFinalUseTrustStore` into an
attested production provider. The local host store remains a compatibility and
recovery composition whose evidence boundary is explicitly narrower.

The two-process test exercises durable pending revocation, one nonce frame,
provider-attempt identity, authority witness continuity, exact lookup-based
reconciliation, one terminal receipt and rejection of provider redispatch. A
successful retained raw log is still required before those execution fields may
be projected true.

## Production bootstrap boundary

The only source-level production path is:

```text
selected deployment providers
  -> ProductionAuthorityTrustBundle
  -> AgentdProductionAuthorityBootstrap::from_trust_bundle
  -> AgentdConfig::with_automation_effect_production_authority
  -> AgentdAutomationEffectHost::open_production
  -> one FinalUse owner
```

Fleet uses the analogous `FleetAuthorityPort::open_production` entry point.
Compatibility `open` remains visibly separate and cannot satisfy the production
trust evidence contract.

The repository intentionally does not synthesize production evidence from local
paths, test keys, a system clock or a JSON boolean. A real deployment must
supply the independently qualified clock, frontier store and live key-custody
provider together with their evidence. Until that composition is selected and
executed, `ordinaryDeploymentProviderWired` and `productionImplementation`
remain false.

## Executable port acceptance

The executable projection separates the following facts for every declared
port:

```text
source wired
  -> enrolled native cases executed and raw logs reopened
  -> relevant normal product-process recovery executed
  -> lifecycle obligations proved
  -> target-host and independent production acceptance
```

The lifecycle set includes queued revocation, parent retirement, epoch change,
cancellation before the effect boundary, cancellation after the effect
boundary, two-product-process recovery and replay. The current projector refuses
to mark `nativeIntegrationVerified` while any required obligation remains
unproved, and it never sets `productionAccepted` itself.

## Measurement-before-optimization rule

No cached authorization conclusion, split final admission transaction, history
truncation or relaxed recovery check is allowed as a performance shortcut.
Optimization proposals must start from the selected target-host evidence and
must preserve the same linearization and recovery semantics.

The retained target collection records exact candidate/control identities,
collector, policy and protected driver digests, raw artifacts and the independent
hot-path decision. Even a passing target collection keeps production SLO,
activation and release false until their separate authorities act.

## Local validation commands

From the repository root:

```bash
python3 qualification/kernel-authority/convergence_acceptance.py \
  --output /tmp/kernel-authority-convergence.json
python3 qualification/kernel-authority/test_convergence_acceptance.py
```

The validator checks that the immutable anchor is an ancestor of the candidate,
that every tracked source path is unchanged from that anchor, that the canonical
clock/bootstrap/owner/port/capacity contracts are still present, and that all
execution and production claims remain within their evidence boundary.

Native execution remains owned by the existing exact-head, synthetic-merge,
product-process recovery, production-closure and target-capacity workflows. A
queued workflow is not a pass.

## Current completion boundary

At this source anchor:

- canonical trusted-clock ownership: source closed;
- typed Agentd and Fleet production bootstrap entry points: source closed;
- executable evidence-bound port acceptance: source closed;
- real-target capacity collector and hot-path policy: source closed;
- exact-candidate native execution: not claimed by this document;
- ordinary deployment provider wiring: not proved;
- all declared ports natively verified: not proved;
- target collection and production SLO: not proved;
- independent acceptance, activation and release: false.

This is deliberate. The remaining work is execution and external provider/host
qualification, not an invitation to weaken the owner, clock, persistence or
recovery contracts.

## Adversarial audit verification

The source anchor includes the storage FIFO denial-of-service fix, checked
revocation-retry lineage at revision exhaustion, bounded recovery regressions,
strict lint repairs and Rust formatting. See [the detailed audit](AUDIT_20261001.md).

Local development validation passed 217 `codex-hepta-contracts` tests with zero
skips, strict all-target contracts Clippy, 97 qualification/evidence Python
tests, eight kernel-authority B4 tests, the source convergence validator,
status projection freshness and contracts/Agentd/Fleet Rust format checks.
These are local development results, not hosted or production receipts.

The Agentd two-product-process recovery test could not reach execution locally:
its dependency build exhausted the shared workspace disk. Exact-candidate
hosted compilation/recovery and selected production-provider/target-host
qualification remain required. No production, activation or release claim
changes as a result of this audit.

The follow-up source/doc audit corrects qualified Rust owner-anchor resolution
and the general-lease interval profile. It passes all 687 tests discovered by
the development-docs workflow, 97 authority qualification tests and eight B4
tests locally. The native authority runtime is unchanged by this follow-up.
The earlier head's hosted evidence-integrity gate succeeded; that receipt is
not reused as execution evidence for the new candidate. Hosted native/process
qualification for the new head remains pending until exact receipts exist.
