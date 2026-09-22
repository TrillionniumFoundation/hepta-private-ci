# kernel.authority production evidence admission

This directory defines the machine-checkable admission boundary for production
evidence that cannot be manufactured by repository unit tests.

The repository can implement authority state machines, exact bindings, durable
stores, fail-closed interfaces, control-plane state machines and evidence
parsers. It cannot self-issue proof of an attested clock, rollback-independent
CAS frontier, deployed revocation transport, HSM/KMS custody, target-host
capacity measurements or independent operator acceptance.

## Commands

Repository/CI self-test:

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
`PASS_KERNEL_AUTHORITY_PRODUCTION_EVIDENCE_ADMISSION`. That result means the
bundle is complete, exact-candidate-bound, internally consistent and
content-addressed. It deliberately prints `activationGranted:false` and
`releaseGranted:false`: deployment activation and release remain separate
operator-governed transitions.

## Bundle contract

`production-evidence.json` uses schema
`hepta.kernel-authority-production-evidence.v1` and has exactly these sections:

- `candidate`: exact Git commit and tree.
- `authority`: owner identity and authority state schema.
- `trustedTime`: named protected clock backend, bounded uncertainty and a
  content-addressed qualification receipt. The receipt must establish
  fail-closed behavior and independence from rollback of the local authority
  directory.
- `antiRollback`: named rollback-independent CAS frontier backend and a
  qualification receipt proving durable compare-and-set, conflicting-writer
  exclusion, no silent genesis fallback and rejection of an older restored
  local snapshot.
- `revocationDistribution`: named deployed transport, closed enrolled-node
  set, feed lifetime, convergence SLA and measured `normal`, `delayed`,
  `partition` and `restart` scenarios. The current head must be
  acknowledged by the full enrolled set and a stale feed must fail closed.
- `keyCustody`: exactly `issuer`, `approver` and `distributor` roles.
  Each role names its custody backend, active key IDs, custody/rotation/
  compromise-response receipts, historical audit retention and
  `applicationPrivateKeyExposure:"role_process_only"`.
- `capacity`: target-host measurements at `empty`, `1k`, `8k`,
  `90_percent` and `max`, plus the complete crash/fault matrix required by
  `CAPACITY_QUALIFICATION.md`.
- `operatorAcceptance`: an independent reviewer receipt bound to the exact
  candidate commit and tree.
- `artifacts`: every referenced receipt as a safe bundle-relative path plus
  its SHA-256. The verifier rejects path traversal, aliases, symlinks, missing
  files and byte substitution.

The evidence bundle is intentionally self-contained. Receipt producers may use
their own platform-specific formats, signatures and attestation mechanisms, but
their immutable bytes must be retained in the bundle and referenced by digest.
A deployment-specific verifier may additionally authenticate those receipt
formats before invoking this admission check; this generic repository verifier
does not claim to replace TPM/HSM/KMS/cloud-attestation validation.

## Required capacity fault cases

The capacity receipt must cover all of:

- `before_external_frontier_cas`
- `after_external_cas_before_local_temp_write`
- `after_temp_fsync_before_rename`
- `after_rename_before_directory_fsync`
- `after_successful_local_commit`
- `during_prune`
- `during_epoch_rollover`
- `restart_with_older_local_snapshot`

The verifier is fail closed: missing sections, unknown critical fields,
duplicate JSON keys, duplicate nodes/keys, stale candidate identity, missing
scenarios, failed booleans, unsafe artifact paths and digest mismatches reject
the bundle.
