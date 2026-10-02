# Inactive retained destination admission

Baseline: `ab51180759186d73fcd2605d1cd5918ef59f67d3`.

## Actual owners and prerequisite gap

Agentd already owns run admission through DurableAgentRunCoordinator and its
retained file. Control requests use a bounded owner-only local socket and a
claimed spawn generation. That is not an independently installed four-role
execution issuer trust source. No bridge-specific host trust/currentness provider
is currently composed into Agentd. This stage neither supplies one nor accepts
trust, clock or currentness from a request.

The new host-only adapter invokes the existing verify_execution_plan against a
host-provided ControlTrustStore, then joins the preserved signed payload preimage
to the exact retained run/context/envelope/revision/fence. It pins Agent identity,
spawn/current generations, authority epoch, configuration and ports digests,
admission-open state, and live deadline. It reads the existing retained file
before and after validation. No second run store or unchecked owner snapshot
constructor is exposed.

## Lifetime and trust contract

The result has private fields and no Clone/Serialize/Deserialize implementation.
It exclusively borrows the real retained coordinator. Revalidation rereads file
integrity, the signed authority, trusted clock and host currentness; any failure
permanently invalidates that result even if old values are restored. Validation
checks for host movement while signatures and the retained file are checked.
There is no method converting this object into a mutation or physical-send permit.
Future mutation integration must repeat a fresh final-use check under the actual
owner lock. Snapshot checks do not provide an atomic cross-process generation lease.

The host must authenticate the clock, lifecycle/readiness, Agent generation,
configuration/ports roots, authority epoch and pinned key/revocation state. It must
advance trust_revision for every trust change, even unrelated keys. This adapter
compares that revision; it does not independently fingerprint all trust bytes.
A dedicated test demonstrates this provider obligation rather than asserting
that an unchanged revision guarantees an unchanged trust store.

NativeBoundSourceProof is a preserved preimage fact, not live source currentness.
Source dispatch revision/digest and abort commitment remain bounded observations;
they are not an authenticated source-journal attestation. Before actual mutation,
the host must authenticate the source journal incarnation, retirement/reconciliation
status, current source authority and source-to-destination channel. The retirement
test here retires the destination run, not the source journal. No source retirement
or restart authorization is invented.

## Executed validation

- Nine actual retained-owner admission tests passed, with 188 unrelated tests
  filtered. They cover independent signature/role/revocation rejection, binding
  drift, stale generation/epoch/configuration/ports, expiry, clock rollback during
  initial checking and revalidation, unavailable host/zero revision, host revision
  changes, closed destination admissions, retained-file tampering, explicit reopen
  and destination retirement. Successful validation leaves retained bytes unchanged.
- The first compile exposed that infer-core was dev-only. The same local dependency
  was promoted to normal dependencies; it has no feature table or provider/Agentd
  dependency cycle. Its normal/build graph consists of types, serialization,
  hashing and signature support, plus its existing Windows-only file helper.
- `just bazel-lock-update` completed successfully with no lockfile diff. Cargo.lock
  and the paused AuthBus/state paths remain unchanged. No dependency or trust was
  copied from another worktree.
- The first filename-based test filter ran zero tests and failed; the actual module
  filter `test(lane_b_runtime::bridge_admission::tests)` then ran all nine. The final
  retained log records actual execution, not an empty filter success.
- Repository scoped fix completed with inherited warnings and mechanical fixture
  fixes. Strict Agentd library Clippy is blocked by 13 diagnostics in unchanged
  browser/cognitive/automation/plasticity files; none names the new admission code.
  This stage is not strictly lint-clean and no lint was suppressed.
- Only changed Rust files were formatted, then diff whitespace checked. The stable
  formatter warns that the repository's import-granularity option is nightly-only.
- Parent independent source review requested clock/currentness, trust-revision and
  source-retirement boundary clarification; those tests and boundaries are included.
  No second independent Rust execution is claimed.

## Remaining integration

No wire capability, installed host, Agentd response-shape change, run mutation,
retained image schema change, outbox delivery, capacity release or provider effect
is activated. The successful-provider primary and sticky qualification notice from
the preceding model are untouched. Next work must extend the existing retained
image with a versioned bound record and exact independent ACKs, reject legacy views
of bound runs, and integrate source settlement/outbox persistence with actual
crash/error cuts. It must never erase or reinterpret the primary after a late
qualification downgrade. Windows registrar/AuthBus repairs remain outside this
stage; Windows retained storage, source retirement authority, atomic ingress fencing
and full production acceptance remain open.

Exact-head CI of the baseline had failed source/main-merge matrix, maintenance,
x64 smoke and Lane B; the source-head job retained clean-source evidence. Detailed
log retrieval returned Transport closed twice, so no new causal attribution is
claimed. New published-head hosted validation remains pending.
