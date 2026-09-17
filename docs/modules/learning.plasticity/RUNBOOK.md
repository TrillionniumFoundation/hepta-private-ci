# learning.plasticity production runbook

This runbook defines the concrete host obligations for the composed proposal path. It does not authorize activation, weight installation, topology mutation, selection, promotion or release.

## 1. Ownership

- Module owner: `learning-platform`.
- Independent review: `architecture`.
- Artifact lineage owner: `learning.artifacts`.
- Signed learning-evidence trust / revocation owner: `learning.ledger` host authority store.
- Independent evaluation owner: `learning.eval`.
- Proposal file owner: selected product host running `codex-hepta-intelligence`.
- External proposal-anchor owner: host durability service in a rollback domain independent from the proposal file and its backups.
- Writer-fence issuer: host lease/fencing coordinator. A fence is never minted from proposal-file contents.

## 2. Mandatory production invariants

Production composition MUST satisfy all of these conditions:

1. use `run_governed_plasticity_v1` or a stronger reviewed caller;
2. use `ProductionProposalRegistryV1`, not an unanchored `DurableProposalRegistry`, for non-test writes;
3. use a non-zero registry scope digest and non-zero writer fence;
4. store the external anchor outside the proposal file rollback/backup domain;
5. compare-and-store the anchor atomically after every durable proposal append;
6. fail closed when artifact lineage is missing, quarantined or revoked;
7. fail closed when any named evidence material is missing, oversized or hashes differently;
8. fail closed when the prepared artifact/evidence context changes before admission;
9. fail closed on expired/revoked/unknown evidence signers or controller collisions;
10. require an independently signed evaluation with disposition `EligibleForIndependentSelection`;
11. retain `RequiresIndependentAcceptance` and `DENY_ALL` on the proposal record;
12. never route a proposal receipt directly to a weight installer or topology mutator.

## 3. Initial operational thresholds

These are **pre-activation acceptance thresholds**, not measurements from a deployed host. The selected host must measure them under representative load before activation.

| Signal | Initial threshold | Action |
| --- | --- | --- |
| missing/corrupt/revoked evidence accepted | exactly `0` | release blocker; stop writes |
| stale prepared context accepted | exactly `0` | release blocker; stop writes |
| unanchored non-empty registry opened | exactly `0` | release blocker; quarantine host |
| external anchor CAS conflict | any occurrence | stop writer, investigate fencing/duplicate host |
| `AnchorCommitIndeterminate` | any occurrence | poison writer, page operator, reconcile before reopen |
| proposal authority grants any capability | exactly `0` | security incident |
| product caller installs weights or mutates topology | exactly `0` | architecture/security incident |
| evidence bytes resolved per proposal | <= 8 MiB total; <= 64 KiB per material | reject over limit |
| generator signal surface | <= 4,096 parameters | reject over limit; never truncate |
| candidate count | <= 32 (V3 generator currently emits 1–2) | reject over limit |
| norm layers | <= 256 | reject over limit |
| proposal registry records per file | <= 4,096 | rotate only through reviewed host procedure |

Latency SLOs are intentionally not asserted until the selected resolver/anchor backend is known. The host must publish p50/p95/p99 for evidence resolution, governed admission, durable fsync and external-anchor acknowledgement before activation.

## 4. Required telemetry

`codex-hepta-intelligence::PlasticityProductEventV1` emits digest-only events at:

- governed admission;
- durable proposal write;
- external anchor acknowledgement.

The host should count outcomes by stable error class without logging raw parameter values, evidence bytes, credentials, signing keys or model contents. Required counters include:

- admitted proposals;
- rejected artifact lineage;
- missing/corrupt evidence;
- stale prepared context;
- signature/trust/revocation failures;
- controller collisions;
- independent-evaluation ineligible/insufficient outcomes;
- durable write failures;
- external anchor conflicts/indeterminate acknowledgements;
- poisoned writer handles.

Alert immediately on any anchor conflict, poisoned writer, authority-grant rejection, or evidence-integrity mismatch. Rate-based alerts for ordinary ineligible candidates should be tuned from measured qualification traffic rather than invented in this document.

## 5. Writer start and failover

### Normal start

1. acquire the host writer lease;
2. obtain a new non-zero writer fence from the lease/fencing coordinator;
3. open the proposal file read/write;
4. load the external anchor for `(scope, fence)`;
5. call `ProductionProposalRegistryV1::open`;
6. if history is non-empty and no external anchor exists, stop — do not reconstruct an anchor from the file;
7. emit host-ready telemetry only after open succeeds.

### Failover

A replacement writer must receive a new fence. Reusing the old writer fence across failover is prohibited. The host must preserve the prior anchored history for audit and either continue the same reviewed lineage with an explicitly migrated anchor or start a new scope/file according to the host retention procedure.

## 6. Anchor failure / rollback incident

If `AnchorCommitIndeterminate`, anchor mismatch, acknowledged history missing, or CAS conflict occurs:

1. stop new proposal writes immediately;
2. keep the proposal file and external anchor unchanged where possible;
3. snapshot both independently for incident evidence;
4. do not truncate or replace history based only on the proposal file;
5. compare the external anchor sequence/digest with the checksum-chain frames;
6. if the acknowledged frame is absent or mismatched, quarantine the file and restore from a copy containing that exact acknowledged frame or a reviewed successor;
7. if the file contains a fully durable successor that was never externally acknowledged, treat the state as indeterminate; reconcile under operator procedure rather than silently advancing the anchor;
8. issue a fresh writer fence before resuming;
9. reopen through `ProductionProposalRegistryV1` and verify the authoritative anchor before allowing writes.

An old but internally valid prefix is a rollback, not a valid recovery state.

## 7. Evidence/trust incident

On signer revocation, authority-epoch rotation, artifact quarantine or evidence-store corruption:

- reject new admissions using the stale trust/context;
- rebuild a `LearningEvidenceVerifierV1` from the new host-owned trust snapshot;
- prepare the proposal again from current artifact/evidence state;
- collect fresh signatures; do not reuse previous attestations across a changed trust digest, authority epoch or context digest;
- preserve rejected proposal/evaluation digests for audit without promoting them.

## 8. Canary procedure

A structural or parameter canary is proposal-only until a separate activation package exists.

1. run exact-head focused tests and strict lint;
2. prepare governed proposals from frozen representative evidence;
3. verify deterministic generator parity across repeated runs and supported hosts;
4. verify every negative case: missing evidence, digest drift, signer revocation, controller collision, stale artifact, stale prepared context, anchor rollback and anchor CAS failure;
5. write to an isolated externally anchored proposal registry;
6. restart and reopen from the external anchor;
7. compare proposal/governance/frame digests across restart;
8. verify there was no current-generation model/topology mutation;
9. obtain independent review evidence before any activation request.

## 9. Stop conditions

Stop the writer and fail the qualification candidate on any of:

- authority violation;
- cross-owner mutation;
- unbounded/truncated generator input;
- generator nondeterminism;
- evidence resolver returns mismatched bytes;
- stale/revoked signer accepted;
- evaluator/controller independence failure;
- current artifact lineage changes during prepare/admit;
- durable file corruption;
- missing/mismatched external anchor;
- anchor CAS conflict or indeterminate acknowledgement;
- current-generation weight or topology mutation;
- exact-head focused test/lint failure.

## 10. Activation and release

Passing this runbook establishes source/host readiness only. Activation still requires a named selected host, current exact-head evidence, operator acceptance, canary evidence, rollback rehearsal and the repository's external governance gates. Release remains a separate decision outside `learning.plasticity`.
