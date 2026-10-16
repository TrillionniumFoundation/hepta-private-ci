# P2g — Signed Final-use still cannot grant a physical effect

**Exact parent:** P2f PR #2313 at 35ca2c90cde04e50fb6296f39c15d68cf250f80c, stacked on the
native-qualified P2e three-way Codex Exec Server corpus. This proposal adds
four Unix-only Rust integration tests, this explanation, and source-head plus
prospective-base native CI. No production code, dependency, persistent schema,
original owner or execution route changes.

## What the native tests must prove

- All six inspectable requests from the frozen 50-case corpus are checked by
  the original P2c preflight, prepared in the **actual original Evidence SQLite
  owner**, and reconstructed by durable key on a cold read-only reopen.
- A separately instantiated **test-only Ed25519 signer** signs the exact
  original FinalUseBinding, including subject/destination, original request,
  scope and payload hashes. The existing FinalUseAuthority validates the real
  signature, checks live grant/epoch/revocations and consumes the one-use nonce.
- **Even after a valid signed test-only grant passes enter_verified_use**, the
  original HeptaEvidenceStore::audit_execution_effect_entry_denied_v1 must
  refuse physical execution. The original P2b authority constant stays false.
  Original Final-use used nonces remain consumed across its own state-dir reopen.
- Wrong binding, altered signed data, changed original physical wire,
  changed generation, and revocation after the claim fail closed in the
  original authority and Evidence implementations.
- An actual original indeterminate provider-effect preparation continues to
  require original-owner reconciliation on cold reopen, even when a test-only
  signed Final-use grant has already passed live verification.

The locally held private signing key, normal system clock, and private
temporary directory are test fixtures; they are NOT an independent production
issuer, operator approval, protected time or external anti-rollback oracle.
The test exercises an opaque signed authority entry in process, but **never
calls an executable provider, process, tool, network endpoint or tool effect**.
This is not a test of an original-host production Final-use integration.

## Production gaps unchanged

There is no new original Effect Owner host composition, independently
operator-approved signing service, runtime executable or sandbox/environment
custody, pending-before-effect durable dispatch record, authenticated physical
terminal outcome, crash/power-loss reconciliation, or actual provider-entry
consumption. A test-only valid signed grant cannot produce these missing
evidence objects. No Cell Split, benchmark, throughput or AGI claim follows.

Exact source-head and prospective-base native CI must run pinned Rustfmt,
Cargo --locked, original Final-use and Evidence regression, all four new
integration tests, and strict Clippy. No warnings or failures are suppressed.
P2e/P2f inherited qualifications and the global security/architecture gates
remain independently mandatory; there is no main merge or production route.

**DRAFT / DENY_ALL / NO PHYSICAL DISPATCH.**
