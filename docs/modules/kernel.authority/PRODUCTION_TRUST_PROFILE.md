# kernel.authority production trust profile

Status: **required deployment evidence; repository interfaces implemented, deployment evidence not granted**.

This profile defines the minimum external facts a production host must prove before
`kernel.authority` can be described as rollback-resistant, time-trusted, fleet-fresh
or key-custody-qualified. Source tests and local fsync durability do not satisfy these
requirements.

## 1. Trusted time

A production host MUST supply an `AuthorityClock` whose trust domain is independent
of unprivileged process state and the authority state directory.

The qualification artifact MUST identify the clock source and prove:

- time cannot be moved backwards by the authority consumer or restored filesystem;
- restart does not silently reset the accepted authority time horizon;
- unavailable or unverifiable time returns an error and authority fails closed;
- signed FinalUse validity windows and lease expiry are evaluated against the same
  documented host clock policy;
- the maximum tolerated clock uncertainty/skew is documented and bounded.

A wall-clock implementation backed only by ordinary `SystemTime` is compatibility
behavior, not production time evidence.

The repository contains one named local source composition for Agentd automation:
`AgentdFinalUseTrustStore` persists a non-decreasing wall-clock floor in an
owner-only directory outside the Agent home rollback domain and fails closed if
the host clock reopens behind that floor. This provides host wiring and recovery
semantics, but it is not an attested clock and does not satisfy target-platform
qualification by itself.

Production constructors now retain a runtime clock/custody adapter, rather than
validating custody only during open. `AuthorityClock::now_with_uncertainty`
supplies a centre and radius. FinalUse requires the complete possible interval
to lie in the signed half-open validity window at claim, after durable nonce
persistence, and at every final-use boundary. Overflow rejects admission.
Compatibility clocks retain their explicit zero-radius point policy. General
lease claim and final entry likewise require the complete possible interval to
lie in the lease's declared half-open validity window. Pruning requires definite
expiry at the interval's earliest time. Both paths sample after acquiring the
owner lock; overflow and unavailable time reject admission. This source behavior
is covered by `authority_lease_interval_tests.rs` and does not supply external
clock attestation.

## 2. External anti-rollback frontier

A production host MUST supply an `AuthorityFrontierStore<F>` outside the local
authority directory. It MUST preserve the most recently accepted frontier across
process restart, local directory restore/replacement, and ordinary backup rollback.

The backend MUST provide durable compare-and-set semantics for the owner identity:

1. load returns one authoritative current frontier or fails closed;
2. compare-and-set succeeds only from the exact expected frontier;
3. a successful compare-and-set is durable before success is returned;
4. conflicting writers cannot both advance from the same predecessor;
5. loss/unavailability does not fall back to a fresh genesis frontier;
6. restore tests demonstrate that an older local authority snapshot is rejected.

The repository intentionally advances the external frontier before committing the
local replacement. If the external advance succeeds and local commit fails, the
owner fences itself. Recovery requires the documented exact-frontier procedure;
it must never infer that the mutation did not happen or reset authority history.

The named Agentd automation host supplies a concrete single-writer
`AuthorityFrontierStore<FinalUseFrontier>` outside the Agent home directory. Its
source tests cover exact CAS conflict, restart persistence, exclusive-owner
handoff, missing-frontier rejection and restored-local-snapshot rejection. This
local source backend establishes composition and failure semantics for that host;
a selected deployment still has to prove that the filesystem, volume, backup and
boot rollback domains are independent of the authority directory.

## 3. Revocation distribution and fleet freshness

The repository control plane accepts only distributor-signed
`SignedFinalUseRevocationUpdate` objects, exact local-apply receipts and signed
enrolled-node acknowledgements. `FleetRevocationCoordinator` defines the admission
semantics:

- every newer head forces enrolled nodes to catch up again;
- same-epoch heads may only preserve or add revocations;
- a missing node is `CatchingUp` before the convergence deadline;
- at/after the deadline it is `Quarantined`;
- once the signed feed expires every node is `FeedStale`;
- only an exact acknowledgement of the current update can make a node `Ready`.

A deployment still MUST supply the wire transport. Qualification MUST record the
closed enrolled-node set, configured convergence SLA, feed lifetime, measured
delivery/ack latency, packet-loss/partition behavior, restart catch-up behavior and
the exact candidate digest. There is no "last known good forever" fallback.

The Agentd automation host authenticates a complete signed feed at open and refreshes
that file before new effect work. A private feed-bound clock enforces its verified
validity interval at each authority time sample; the HTTP driver rechecks after
witness persistence and before provider entry. Refresh invalidates the window before
changing the authority head and publishes only after success. A database wait cannot
silently extend formerly fresh revocation knowledge.

If a signed update arrives during a guarded effect, the authority durably records
its exact monotonic head in V4 `pending_revocations` and advances the external
frontier before returning `DispatchInProgress`. New claims and entries then fail
with `RevocationPending`. The exact head or a strictly stronger monotonic head must
be retried after the active effect drains. This is not a process-local pending bit.
Recovery may complete only a candidate exactly matching the independently retained
frontier; feed reread alone cannot replace kernel recovery.

## 4. Key custody and rotation

Grant issuer, independent approver and revocation distributor are separate roles.
Production qualification MUST bind every configured `key_id` to an external
custody identity and record:

- key generation/import provenance;
- HSM/KMS or equivalent protected custody;
- activation and retirement authority epochs;
- staged overlap rehearsal;
- emergency compromise/revocation procedure;
- audit retention sufficient to verify historical receipts after retirement;
- proof that application processes do not possess private signing material unless
  that role explicitly requires signing.

Repository signer utilities consume externally provisioned keys and are not a key
custody system. The production runtime-clock adapter retains the exact provider,
role, trust domain, active key-set digest, generation, revocation floor and
non-exportability checks. An observed identity/generation drift fences the adapter;
a later rollback to a previously accepted report cannot un-fence it. Unavailable
custody supplies no admission time. Provider implementations must bound these calls;
any authenticated local cache must expire fail-closed and preserve known revocations.

The normal Agentd bootstrap in this candidate still uses the local trust store,
not a deployed production bundle. Real provider selection, lifecycle invalidation,
rotation ceremonies and normal-product integration remain open. Source fixtures
implementing production traits are tests, not external custody evidence.

## 5. Machine-checkable evidence admission

The repository provides a fail-closed admission verifier for the external facts
in this profile:

```bash
python3 qualification/kernel-authority/verify.py self-test
python3 qualification/kernel-authority/verify.py verify \
  --evidence /secure/evidence/kernel-authority/production-evidence.json \
  --expected-sha <exact-candidate-commit>
```

The bundle contract is defined in
[`qualification/kernel-authority/README.md`](../../../qualification/kernel-authority/README.md).
Admission uses schema `hepta.kernel-authority-production-evidence.v2`. It checks
exact commit/tree identity, content-addresses every retained external receipt,
derives revocation SLA results from measured times and complete node counts, and
requires a complete numerical capacity/fault matrix rather than trusting caller
supplied pass booleans. It does not make the repository the issuer of
TPM/HSM/KMS/cloud attestation, and a pass explicitly does not grant activation or
release.

## 6. Required deployment receipt

A production evidence bundle MUST contain, at minimum:

- candidate commit and tree;
- authority owner identity and state schema;
- concrete `AuthorityClock` backend identity and qualification receipt;
- concrete `AuthorityFrontierStore` backend identity and rollback drill receipt;
- issuer/approver/distributor trust-key IDs and custody references;
- enrolled revocation node IDs and node trust-key IDs;
- configured feed lifetime and convergence SLA;
- measured convergence results under normal, delayed, partitioned and restart cases;
- capacity qualification artifact referenced by
  [CAPACITY_QUALIFICATION.md](CAPACITY_QUALIFICATION.md);
- explicit operator acceptance.

Until all applicable fields exist for the selected host, implementation maps MUST
keep `productionImplementation`, `productExecutionProved`, `activation` and
`release` false. The source target-port matrix separately records uncomposed ports
and distinguishes owner reopen tests from two normal product-process cold starts.
