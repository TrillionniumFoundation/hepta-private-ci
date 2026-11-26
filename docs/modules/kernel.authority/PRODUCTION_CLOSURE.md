# kernel.authority production-closure program

Status: **repository closure program implemented; successful current-candidate native execution and target deployment evidence remain pending**.

This document binds the four closure stages for `kernel.authority` to concrete
source, tests, workflows and retained receipts. It does not grant production
activation or release. Those flags remain false until the external evidence
bundle defined by `PRODUCTION_TRUST_PROFILE.md` passes independent review.

## 1. Merge-safe security baseline

The working branch keeps one authority spine and one final-use boundary:

- `AuthorityDispatchBinding` is the one-shot general-lease production dispatch
  capability. Fleet computes the exact binding from the mutation and consumes
  the binding at `LeaseLedger::issue`.
- FinalUse claims are one-shot, nonce-backed and revalidated at the guarded
  dispatch entry.
- a newer revocation observed during an active effect persists the exact pending
  head in the V4 authority snapshot, advances the external V2 frontier, fences
  every new claim/entry with `RevocationPending`, and requires that head or a
  strictly stronger monotonic update to be committed after the effect drains;
- recovery covers both external-frontier-first crash windows: an external
  pending frontier with a committed local snapshot and an external committed
  frontier with a pending local snapshot. Repair is accepted only when an
  independently authenticated head reconstructs the existing external frontier
  exactly; recovery never advances that frontier;
- FinalUse key-ring recovery preserves claimed nonce history and rejects a local
  snapshot that cannot be reconciled exactly with the external frontier;
- Agentd owns provider selection, exact wire bytes, dispatch, reconciliation,
  durable witness recording and terminal receipt reuse;
- exact-head and deterministic synthetic-merge candidates are prepared from
  immutable commit/tree identities. Every retained receipt names that identity.

The required convergence workflow remains
`.github/workflows/kernel-authority-convergence.yml`. It executes governance,
contracts, product and host lanes for both candidate modes without retries.
`prepare_candidate.py` creates the candidate and all downstream evidence must
match its commit and tree. Different-SHA or stale artifacts are rejected rather
than silently reused.

The closed-world proof has two coupled inventories. Canonical authority
boundaries enumerate lower-level privileged entry points. The extension API
inventory enumerates every public production wrapper. A wrapper may be treated
as an internal canonical delegate only when it is both exhaustively classified
as privileged and mapped to an existing canonical boundary. New wrappers or
new product callers therefore fail closed rather than disappearing from the
caller proof.

## 2. Mandatory production trust bundle

`codex-rs/hepta-contracts/src/authority_trust.rs` defines a complete
`ProductionAuthorityTrustBundle` containing:

1. a `ProductionAuthorityClock` with a named trust domain and bounded maximum
   uncertainty;
2. a `ProductionAuthorityFrontierStore` with the same trust domain and durable
   exact compare-and-set semantics;
3. a live `ProductionAuthorityKeyCustody` identity exposing only provider,
   role, public key-set digest, generation, revocation floor and exportability;
4. deployment evidence for clock, frontier, verifier-only topology, state
   directory, disaster recovery and KMS/HSM custody;
5. key-custody evidence for versioned selection, overlap rotation, retired-key
   rejection and compromise response.

Construction and every production open revalidate the live components. The
constructor fails closed when any component is missing, unavailable, from a
different trust domain, behind the retained generation, exportable, or bound to
a different public key set.

General leases use:

```rust
AuthorityLeaseRegistry::open_production_state_dir(path, owner_id, &bundle)
```

FinalUse uses:

```rust
open_production_final_use_authority(path, signer_id, issuer_keys, head, &bundle)
recover_production_final_use_authority(path, signer_id, issuer_keys, head, &bundle)
```

The FinalUse constructor recomputes the complete canonical issuer key-ring
digest, including key IDs, public keys and inclusive authority-epoch windows.
That digest must equal the live KMS/HSM custody digest. Private signing material
is never requested by the kernel verifier.

The repository test doubles implement the production marker traits only inside
tests. `SystemAuthorityClock` and ordinary local-file compatibility stores still
do not satisfy the production constructor. Repository source proves the
contract and fail-closed composition; it does not manufacture an attested clock,
linearizable production backend or real KMS/HSM receipt.

## 3. Fleet and Browser/Agentd product pilot

`qualification/kernel-authority/runtime_qualification.py pilot` executes a
candidate-bound process pilot for both product families. It covers:

- Fleet lease creation, exact mutation binding and durable restart/reopen against
  the exact committed frontier;
- Fleet final dispatch and durable witness;
- Fleet revocation and rejection of the old capability;
- Browser/Agentd final-use fencing across the exact local dispatch boundary;
- Agentd provider dispatch with exact wire bytes and one idempotency identity;
- durable TaskFlow authority witness and terminal provider receipt reuse;
- Agentd restart and signed revocation-feed advancement;
- external-frontier rejection of a restored local snapshot;
- pending-revocation admission fencing;
- pending-revocation restart plus both frontier-first crash-recovery windows;
- issuer key overlap and old-key retirement;
- external frontier ahead after an unrelated failed local nonce commit.

Each case retains the exact command, exit code, elapsed time, log byte count and
log SHA-256. The aggregate receipt explicitly records:

```json
{
  "deploymentActivationProved": false,
  "productionTrustProved": false,
  "activationGranted": false,
  "releaseGranted": false
}
```

The pilot therefore proves repository process behavior, not a deployed KMS,
attested clock, production network, storage/backup domain or operator rollout.

## 4. Performance, recovery and storage evolution

The performance lane contains two deliberately separate artifacts.

### 4.1 Current snapshot implementation measurement

`codex-rs/hepta-contracts/tests/kernel_authority_benchmark.rs` is inert during
ordinary tests. When enabled by the qualification harness it measures:

- durable lease put latency, including current snapshot write/fsync behavior;
- final dispatch-entry latency;
- durable revoke latency;
- four-thread contended dispatch-entry latency;
- aggregate throughput;
- persisted snapshot size;
- restart/open latency on the populated state.

It emits count, minimum, mean, p50, p95, p99 and maximum values. The receipt is
marked `qualificationOnly=true` and `productionSloGranted=false`; repository
runner measurements are not substituted for target-host SLO evidence.

### 4.2 WAL/checkpoint, sharding and capacity prototype

`qualification/kernel-authority/storage_model.py` is an executable reference
model, not runtime code. It models:

- an append-only SHA-256 chained journal;
- fsync-before-success records;
- generation checkpoints and a digest-bound manifest;
- recovery after an incomplete final record;
- fail-closed rejection of committed-record corruption;
- fail-closed rejection of a rolled-back checkpoint;
- deterministic owner/lease shard assignment;
- capacity-life projections with a ten-percent rollover reserve.

The model is intentionally isolated from production so it cannot become a
second authority spine. A future runtime WAL implementation must preserve the
existing linearization, anti-rollback and one-shot semantics and must pass the
same external evidence admission before activation.

## 5. Candidate-bound closure workflow

`.github/workflows/kernel-authority-production-closure.yml` runs, for both the
exact head and deterministic synthetic merge:

- the contracts format/test/strict-clippy lane, including the trust bundle and
  durable pending-revocation recovery matrix;
- the Fleet and Browser/Agentd product pilot;
- the latency/recovery benchmark and storage reference model;
- a merge gate that requires every lane for both candidate modes.

Artifacts are named with the workflow run, attempt, immutable source commit,
candidate mode and lane. Logs and receipts live outside the checkout while the
candidate executes, preventing the evidence generator from mutating the source
identity it claims to qualify.

Local equivalents are:

```bash
python3 qualification/kernel-authority/prepare_candidate.py \
  --mode exact-head \
  --base-sha <exact-main-sha> \
  --output /tmp/kernel-authority/identity.json

python3 qualification/kernel-authority/runtime_qualification.py \
  --identity /tmp/kernel-authority/identity.json \
  --output-dir /tmp/kernel-authority/pilot \
  pilot

python3 qualification/kernel-authority/runtime_qualification.py \
  --identity /tmp/kernel-authority/identity.json \
  --output-dir /tmp/kernel-authority/performance \
  benchmark --samples 128
```

## 6. External gates that remain required

Repository closure does not manufacture these facts. Production promotion still
requires all of the following, content-addressed to the selected candidate:

- an independently protected time source and measured uncertainty;
- a rollback-independent frontier backend and restore drill;
- KMS/HSM custody for issuer, approver and revocation distributor roles;
- staged rotation and compromise-response ceremony receipts;
- deployed revocation fanout under normal, delayed, partition and restart cases;
- target-host filesystem, mount, backup and disaster-recovery qualification;
- target-host p50/p95/p99, throughput, lock-wait and restart measurements;
- verifier-only topology evidence;
- independent semantic review;
- operator acceptance, canary, promotion and release.

Until those artifacts pass `qualification/kernel-authority/verify.py`, the
implementation map must keep `productionImplementation`,
`productExecutionProved`, `independentAcceptance`, `activation` and `release`
false.
