# Canonical and short roots for owned macOS test fixtures

## Original failure evidence

The original Mac Intel job `139214394580` in run `45616349339` failed tests
before its eventual job timeout. Its complete job transcript is 1,876,725 bytes,
SHA-256 `e63d41ea1043566e4e1de91bbdfb55d3f7bdfe925be71d962d63ffc0187a2ade`.
The checkout was prospective merge `4eebcef0c284da9a1964d6c01c15c0f219f7aff9`;
its tree `28a74dbbf9b668c4691a93c8fd15c5ae2b4c92e9` equals the tree of PR head
`4be2e45d4c90fe539abf61814fa9b362d8922881`.

The relevant failures have two independent causes at fixture setup:

* Positive cognitive-store fixtures pass a temporary directory alias to the
  production contract that requires a canonical, symlink-free root. There are
  65 visible failure blocks with that error, including all 57 failures in the
  `ext/hepta-memory` unit-test target. The crash/WAL subprocess also receives
  the alias and exits before reaching its intended exit-code oracle. Four
  external trust/frontier fixtures separately fail their canonical-parent
  checks.
* Real Agentd socket binding rejects long paths with `SUN_LEN`. There are 25
  visible failure blocks across ten target labels, including repeated cases
  in the ordinary cognitive target and its qualification target. The shared
  harness already canonicalizes its root, but the canonical default macOS
  temporary directory still makes the socket path too long.

These are counts of visible failure blocks, not independent experiments.
Original job output and bounded child stderr do not replace missing individual
test artifacts. Release-install `EACCES` and Code-mode readiness timeouts are
separate findings and are outside this change.

## Source change

The candidate is based on `4497d4b5029b8e1a39a670e780f1722a09edc909`.

Owned positive Unix fixtures resolve the root they have already created before
constructing a fleet layout. The local-turn binding fixture reuses the existing
`cognitive_test_support::layout` helper. The crash/WAL fixture passes the same
canonical fleet root into its child process. External trust and recovery-frontier
files remain outside the agent home; their existing owned parents are resolved
before the files are passed to production validation.

Three macOS socket fixtures use a short randomized `TempDir` under `/tmp`: the
shared Agentd product harness, the ranker socket test, and the real Agentd worker
test. Their existing canonicalization remains in place. The directory owner is
retained across the entire scenario; the worker host shuts down before its
`TempDir` leaves scope. Other platforms retain their original socket-fixture
locations. This follows the existing short-root pattern in the Matrixd and
Supervisor socket tests.

There is no new cross-crate test API or dependency. Production owner, ACL,
symlink, canonical-path, identity, signature and rollback checks are unchanged.
All test assertions, process arguments, readiness deadlines, retry settings and
resource limits remain in force. Deliberate redirection/invalid-path negative
fixtures are not rewritten.

## Qualification boundary

This is a source candidate, not a claim of native Mac success. The earlier
uncommitted draft was lost in an environment reset; this candidate was rebuilt
against the exact base tree, with every affected original file verified before
editing. The old draft was neither compiled nor executed.

The affected original tests remain the qualification gates. The changes require
the normal Mac test graph, including actual socket binding and the original
crash/WAL child-process case. Formatting and source review alone do not close
those behavioral requirements. No model evaluation or training is part of this
fixture change.
