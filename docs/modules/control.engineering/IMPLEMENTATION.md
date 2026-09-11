# Lane G executable implementation supplement

This supplement binds the existing `control.engineering` design to the additive
implementation under `tools/hepta-engineering-control/control_engineering_v2`.
It is read with the canonical module guide plus `COMPONENTS.json` and
`TRACEABILITY.json` in this directory. Canonical module ownership, contract
ownership, data authority, package predecessors and external gates do not
change.

## Capability boundary

The implementation can issue immutable engineering work envelopes, serialize
repository paths using fenced leases, publish deterministic assignment
projections, verify authenticated exact-source and synthetic-merge evidence,
generate bounded candidates, run candidates in disposable worktrees, request an
independent review and form a dormant external-system assimilation proposal.

It cannot independently accept, select, merge, activate, promote or release a
candidate. It cannot issue runtime authority, mutate a production host, enroll
another host, copy a credential, or mark `RDY-EXT-001` through `RDY-EXT-009`
passed. A successful source test is not an external decision.

## Physical state and transaction boundary

`EngineeringStore` uses SQLite with foreign keys, WAL, `synchronous=FULL` and
`BEGIN IMMEDIATE` for each logical mutation. Its owned tables are:

- `work_envelopes`: immutable source, objective, contract, owner, path,
  authority-ceiling, capacity and expiry facts;
- `path_leases`: holder, path set, state, authority epoch, fencing token,
  revision, issue time and expiry;
- `assignment_generations`: immutable assigned and blocked projections;
- `integration_decisions`: immutable review-eligibility projections;
- `audit_events`: ordered hash-linked immutable event projection.

The owner fact and its audit event commit in one transaction. Reusing an
identity with equal semantics is idempotent; different semantics conflict.
Startup verifies the audit chain before use, and constructor failure closes the
database handle.

## Canonical paths and leases

Paths must be UTF-8 NFC, relative POSIX paths with no empty, `.`, `..`,
backslash, control, NUL or unsupported glob segments. Only trailing `/**` is
accepted at the envelope boundary and is reduced to a canonical prefix.

Lease acquisition validates the current envelope, expiry, path scope and all
active overlap in one immediate transaction. Renewal, release and revocation
require exact revision and authority epoch. Fencing tokens increase
monotonically. An expired, released or revoked holder cannot become valid after
restart by presenting an old token.

## Dependency-aware scheduling

The scheduler bounds package and completed-set iterators before materializing
them. It rejects duplicate IDs, self-dependency, unknown predecessors, cycles
and paths outside the envelope. It then applies predecessor readiness, active
lease exclusion, intra-batch path exclusion, stable priority order and capacity.
The persisted output is an assignment proposal, not execution or merge
authority.

## Evidence verification

The verifier consumes a source-authority receipt, exact-source CI receipt,
synthetic-merge CI receipt and evaluator-independence receipt. It resolves real
Git commits, trees and ordered parents, checks repository identity, validates
SHA-256 fields, verifies signatures and freshness, and rejects generator and
evaluator identity collisions. Success means only
`eligible_for_independent_review`.

`HmacTrustStore` is a deterministic reference/test port. Production composition
must inject the registered authority or HSM verifier; no signing key enters the
engineering store or audit projection.

## Candidate generation and sandbox

An envelope binds the exact base, allowed and protected roots, candidate, file,
byte, time, memory, process and network-isolation limits. The pilot grammar is
`no_change`, `add_file`, `replace_text` and `delete_file`. No-change is inserted
first and identities are content-derived. Binary changes, protected roots,
path escape, ambiguous preconditions, excessive work and source mutation fail
closed.

Candidates run only in detached Git worktrees. Checks use argument vectors, not
shell text, and receive a credential-free environment. POSIX hosts also apply
CPU, address-space, process, file-size and descriptor limits. Mandatory network
isolation fails closed when the host cannot provide it. Windows import and pure
validation remain supported; Windows sandbox qualification requires a host
adapter with equivalent isolation.

The generator can advance a candidate only to `sandbox_tested`; it cannot
produce the evidence or evaluator decision that accepts itself.

## Independent review

The review adapter accepts only a sandbox-tested candidate and an eligible
exact-evidence set with no outstanding reason. It creates a request for a
registered independent, architecture or security role. Acceptance, selection,
merge, activation, promotion and release fields remain false.

## Authorized assimilation

The initial external profile is an explicitly consented, unprivileged Debian
target. Only `query_version`, `query_health` and `read_status` are synthesized.
Manifest inputs are bounded digests and omissions; raw secrets are not copied.
A separate sandbox-parity receipt binds fixture, fault and rollback evidence
plus distinct generator and evaluator identities. Effects, unrestricted
network, production credentials, authority delta, identity collision or input
drift reject. The only successful terminal state is `dormant_candidate`.

## Verification

From `tools/hepta-engineering-control`:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest -v \
  test_hepta_engineering_control.py \
  test_integration_identity.py \
  test_control_engineering_v2.py
python3 lane_g_validate.py
```

The suite covers SQLite reopen, fencing, revision and epoch races, overlapping
paths, dependency cycles, scope escape, semantic identity conflicts, audit
corruption and descriptor cleanup, no-change and deduplication, protected paths,
detached worktree isolation, real Git-object verification, signature tampering,
evaluator collision, expired consent and effect-scope rejection.

A dedicated workflow runs compile, semantic closure, legacy regression and V2
tests on Linux, macOS and Windows. Exact-head and synthetic-merge execution
remain separate evidence receipts.

## Completion semantics

This package closes only repository-owned implementation and documentation
ambiguities for the bounded Lane G source slice after its exact candidate tests
and semantic validator pass. Independent semantic acceptance, real target and
runtime identity, future-time efficacy, empirical biomimicry, target hardware,
real external-owner consent, operator acceptance, production canary, canonical
selection, promotion and release remain external until their actual issuers
provide current evidence.
