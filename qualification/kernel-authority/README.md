# kernel.authority production evidence admission

This directory defines the machine-checkable admission boundary for production
evidence that repository unit tests cannot manufacture.

The repository can implement authority state machines, exact bindings, durable
stores, fail-closed interfaces, control-plane state machines and evidence
parsers. It cannot self-issue proof of an attested clock, rollback-independent
CAS frontier, deployed revocation transport, HSM/KMS custody, target-host
capacity measurements or independent operator acceptance.

## Commands

Repository/CI parser and hostile-case self-test:

```bash
python3 qualification/kernel-authority/verify.py self-test
```

Admission of a real evidence bundle for an exact candidate:

```bash
python3 qualification/kernel-authority/verify.py verify \
  --evidence /secure/evidence/kernel-authority/production-evidence.json \
  --expected-sha <exact-candidate-commit>
```

A successful verification prints
`PASS_KERNEL_AUTHORITY_PRODUCTION_EVIDENCE_ADMISSION`. It means the bundle is
complete, exact-candidate-bound, internally consistent, content-addressed and
that every canonical receipt summary matches the corresponding bundle claim.
It deliberately prints `activationGranted:false` and `releaseGranted:false`.

## Bundle contract

`production-evidence.json` uses schema
`hepta.kernel-authority-production-evidence.v2` and has exactly these sections:

- `candidate`: exact Git commit and tree.
- `authority`: owner identity and authority state schema.
- `trustedTime`: protected clock backend, bounded uncertainty and qualification
  receipt. Ordinary process `SystemTime` is not sufficient production evidence.
- `antiRollback`: rollback-independent durable CAS frontier and restored-snapshot
  rejection evidence.
- `revocationDistribution`: deployed transport, closed enrolled-node set, feed
  lifetime, convergence SLA and measured `normal`, `delayed`, `partition` and
  `restart` scenarios. Delivery and acknowledgement measurements are compared
  numerically with the declared SLA.
- `keyCustody`: exactly `issuer`, `approver` and `distributor`, including custody,
  staged rotation and compromise-response receipts.
- `capacity`: the complete point × operation matrix from
  `CAPACITY_QUALIFICATION.md`, the full fault matrix and reserve-alert exercise.
  Every measurement includes sample count, percentiles, budget, bytes written,
  fsync p99 and peak RSS.
- `operatorAcceptance`: an independent reviewer receipt bound to the exact
  candidate commit and tree.
- `artifacts`: every referenced receipt as a safe bundle-relative path plus its
  SHA-256. Traversal, aliases, symlinks, missing files and byte substitution are
  rejected.

## Canonical receipt summary

Every path used as a receipt must contain exactly this JSON envelope:

```json
{
  "schema": "hepta.kernel-authority-evidence-receipt.v1",
  "schemaVersion": 1,
  "candidate": {
    "commit": "<40 lowercase hex>",
    "tree": "<40 lowercase hex>"
  },
  "kind": "<declared receipt kind>",
  "producerId": "<independent producer identity>",
  "observedAtUnixMs": 1900000000000,
  "synthetic": false,
  "data": {}
}
```

The verifier requires the receipt candidate to equal the bundle candidate,
rejects `synthetic:true`, rejects reuse of one receipt for multiple claims and
compares `data` exactly with the associated bundle fields. Therefore a digest
alone, a success boolean, an empty receipt, omitted samples, contradictory
measurements or a receipt copied from another candidate cannot pass.

Receipt `kind` values are closed by the verifier and include:

- `trusted_time_qualification`
- `anti_rollback_qualification`
- `revocation_distribution_qualification`
- `revocation_scenario`
- `key_custody_qualification`
- `key_rotation_rehearsal`
- `key_compromise_response`
- `capacity_qualification`
- `capacity_measurement`
- `capacity_fault_result`
- `capacity_reserve_alert`
- `operator_acceptance`

Platform TPM/HSM/KMS/cloud-attestation formats may remain provider-specific.
Their independently authenticated result must be projected into the canonical
summary above, while raw signed material may be retained alongside the bundle.
The generic repository verifier validates the summary structure, exact candidate
and semantic consistency; it does not replace the platform-specific signature or
attestation verifier.

## Required fault cases

The capacity evidence must cover all of:

- `before_external_frontier_cas`
- `after_external_cas_before_local_temp_write`
- `after_temp_fsync_before_rename`
- `after_rename_before_directory_fsync`
- `after_successful_local_commit`
- `during_prune`
- `during_epoch_rollover`
- `restart_with_older_local_snapshot`

Unknown critical fields, duplicate JSON keys, duplicate nodes/keys, stale
candidate identity, missing scenarios or measurements, failed invariants,
unsafe paths, digest mismatch, receipt-content mismatch and synthetic evidence
all fail closed.

## Candidate identity and independent check lanes

`prepare_candidate.py` accepts an exact base SHA and either `exact-head` or
`synthetic-merge`. Use it only in a disposable checkout. A merge run requires
an initially clean detached HEAD; it preserves the source/base identities,
constructs the merge tree without changing either branch, and fixes commit
metadata so identical inputs reproduce the same merge commit. Evidence output
must be outside the source tree. An attached branch or dirty checkout is rejected.

The convergence workflow pins source and main once, then runs governance,
contracts, product consumers and the Agentd host independently for both modes.
Every command retains its actual exit status. One failed check does not hide
subsequent checks, and no retries or lower test thresholds turn a failure green.
Each uploaded log set contains the source, base, candidate commit and tree.
These runs qualify repository behavior, not deployment or independent acceptance.

Receipt validation compares canonical JSON types, not Python's loose numeric
or Boolean equality. Schema versions must be integers. The verifier hashes and
parses the same retained bytes, rejects non-finite JSON numbers, and bounds each
JSON file to 8 MiB, the artifact set to 1,024 files and aggregate content to
64 MiB. Reserve-alert evidence must demonstrate a positive remaining reserve;
an alert only at zero remaining capacity does not demonstrate early warning.

Run the parser/candidate regressions with:

```text
python3 -m unittest discover -s qualification/kernel-authority -p 'test_*.py' -v
```
