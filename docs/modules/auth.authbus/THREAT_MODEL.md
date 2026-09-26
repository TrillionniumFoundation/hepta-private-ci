# auth.authbus threat model

Status: normative production-activation contract

This document defines the adversary model and the security invariants that the
`auth.authbus` implementation and qualification lanes must preserve. A passing
unit test or a cooperative current caller is not a substitute for these
invariants.

## Protected assets

- issuer identities, key epochs, purposes, revocation state and verifying keys;
- trusted-time frontier and rollback resistance;
- policy revision, principal/action/scope binding and authorization decisions;
- quota balances, active reservations and terminal settlement state;
- the SQLite authority database, recovery frontier and external checkpoint;
- signed ingress, evidence outbox and Bao final-use receipts;
- audit records used to decide whether production activation is allowed.

## Trust boundaries

1. **External callers are untrusted.** They may supply claims, signatures,
   identifiers, payloads and operation requests. They may not supply trusted
   issuer material or construct an object that the authority treats as verified.
2. **Persistent issuer registries are authority inputs.** A registry is trusted
   only after ownership, permissions, link count, canonical path, size and
   open/read metadata stability checks. SQLite issuer records are read inside the
   same authority transaction that consumes them.
3. **The authority host is the only writer capability.** Raw store mutation is
   crate-private. Public APIs expose the fenced host and read-only result types.
4. **One process owns one authority database.** An exclusive cross-process owner
   lock is held from before database/checkpoint opening until host drop. SQLite
   serialization alone is not an owner fence.
5. **The external checkpoint is a rollback witness.** It is not ordinary cache
   state. Read/compare/atomic replace and parent-directory fsync occur while the
   owner fence is held.
6. **Provider execution is outside the authority transaction.** Durable
   `dispatch_attempted` state precedes the side effect. Ambiguous results are
   terminally fenced as indeterminate until explicit reconciliation.
7. **Tests are not production capabilities.** Any test-only constructor is
   feature-gated and the closed-world dependency inventory rejects that feature
   from normal dependencies.

## Adversaries and failures

The implementation must remain fail-closed under:

- a caller choosing its own public key, issuer ID, epoch, purpose or revoked bit;
- replay, payload substitution, scope substitution and sequence rollback;
- use of a settlement key for message admission or a message key for settlement;
- an already revoked or retired issuer epoch;
- forged quarantine requests and fabricated retirement evidence;
- a second process opening the same database or checkpoint;
- process death before and after database commit, dispatch, rename or fsync;
- torn/truncated checkpoint writes, missing witness files and stale generations;
- symlink, hard-link, foreign-owner and writable-by-others file attacks;
- trusted-time rollback, stale attestations and source-revision substitution;
- abandoned held reservations and abandoned dispatch-attempted reservations;
- disk full, I/O error, SQLite corruption and migration/schema drift;
- unbounded history, reservation or retry growth intended to exhaust capacity.

## Mandatory invariants

### Issuer authority

- Production code cannot construct `IssuerRegistration` or settlement verifier
  material from public fields.
- Signed message admission resolves a sealed handle from a verified persistent
  registry. Settlement resolves issuer purpose, epoch, key and lifecycle from
  SQLite inside the settlement transaction.
- Exact `(purpose, issuer_id, key_epoch)` matching is required.
- Revoked or retired epochs never authorize admission, settlement or quarantine
  state changes except the explicit authority-controlled retirement path.

### Ownership and durability

- At most one live authority host owns a database.
- Every public mutation runs through the host while the owner lock is held.
- A successful mutation cannot be reported before checkpoint synchronization is
  attempted; synchronization failure is returned as failure.
- Checkpoint generation is monotonic and the digest is non-zero.
- A missing checkpoint may be bootstrapped only by the fenced first owner and
  only from the current authoritative frontier.

### Reservation lifecycle

- Held quota plus available quota conserves the configured limit.
- A held expired reservation releases reserved quota exactly once.
- A dispatch-attempted expired reservation becomes indeterminate; it never
  silently releases quota.
- Expiry scanning is bounded per transaction and reports remaining backlog.
- Terminal transitions are monotonic and exact duplicate settlement is either a
  verified no-op or a deterministic conflict.

### Qualification

- Forged-key, revoked-key, epoch-substitution, purpose-substitution and forged
  quarantine cases are negative tests.
- Two independent processes contend for the owner lock.
- Crash points cover commit, checkpoint write, rename and directory fsync.
- Qualification records exact source SHA, source tree, schema digest, artifact
  digests and workflow run ID. Cancelled, skipped or static-only gates are not
  success.

## Explicit non-goals

- Distributed multi-writer consensus is not provided.
- A compromised operating-system kernel or compromised authority process is not
  contained by this module.
- File ownership checks do not replace KMS/HSM controls for production private
  keys.
- An operator with authority to replace the trusted registry can rotate or
  revoke keys; that operation must be governed by the key-rotation procedure.

## Activation blockers

Production activation remains blocked if any mandatory invariant is not enforced
by types, filesystem/database fencing and executable qualification. Documentation
or a product convention that callers "must not" bypass a boundary is not an
acceptable control.
