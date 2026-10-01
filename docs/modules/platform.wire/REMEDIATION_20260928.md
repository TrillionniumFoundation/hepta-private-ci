# platform.wire source remediation — 2026-09-28

## Immutable starting point

This revision extends PR #1094 on `codex/platform-wire-final-convergence-20260925`.
The inspected source archive identifies commit `3d48009c55217f22dc8bc0711600a4e83fc2153b`
and tree `ef4e3581584d5070d3c3d020342fcf0d12321a2b`. The immediate publication
parent additionally contains the independent read-only exact-source/ordered-merge
workflow at `263c604a2be4bcdfa0d4928edc5551cf0b47fdc0`. Neither SHA is represented
as the qualified SHA of this later revision.

## Delivered source changes

- The checked `WireSession::new` constructor rejects transcript/posture and
  transcript/registry substitution. `NegotiatedSession` names the same type.
  All native constructor call sites propagate the new `Result`. One-shot
  session decoding checks the selected version from the fixed header before
  decoding or allocating the advertised body.
- Session identity profile V2 binds the shared runtime admission role. The
  initiator/responder direction remains a separate local endpoint role.
  Deploy both ends together or fail closed; discard old sessions and counters.
  Frozen HPTA V1/V2 frame bytes are not reinterpreted.
- Standard incremental HMAC-SHA-256 replaces both handwritten implementations;
  tags use the library verifier. Owned keys zeroize, terminal poison clears both
  directions, and the managed owner drops poisoned state. Rotation cannot
  silently change the registry, negotiated posture or shared runtime role.
- Consuming EOF finalizers distinguish a clean end from a partial header/body.
  Existing `feed` prefix-plus-terminal-error semantics remain; callers process
  delivered frames once, preserve the unconsumed suffix across work-budget
  yields, and never reuse a poisoned connection.
- HTTP Accept matching uses specificity to determine each representation's
  quality before comparing representations. Explicit `q=0` exclusions cannot
  be overridden by wildcards; unmatched and duplicate parameters reject.
  Only explicit wire V2 opts into binary output. This is HTTP representation
  selection, not an authenticated HPTN handshake.
- The actual Lane A path block is generated from the module inventory. Its
  tests now inspect the real repository workflow, not only a template fixture.
  The stale stream-test evidence anchor names the current bounded-work test.
  Fixed-header parsing no longer uses four prohibited `expect` calls.
- The fuzz target additionally exercises HPTN offers, negotiated streaming
  progress and consuming EOF. Existing bidirectional cross-runtime, negative
  vector, near-limit feed and throughput sources are retained.

## Regression and qualification evidence

The source-authoring environment executed 10 generated-path tests, 17 Lane A
foundation tests and 75 implementation-contract tests: 102 Python unit tests.
Lane A self-test/verify, path drift, lifecycle self-test/document drift and
`git diff --check` also passed in that local source copy. This is local source
validation, not an exact GitHub commit or synthetic-merge qualification.

Rust compilation, native regression execution, strict Clippy, fuzz execution
and throughput measurements must be reported by the read-only workflows on
the final published SHA. Test source existence is not an execution receipt.
The exact-source/ordered-merge workflow retains raw command logs and records
for failures as well as successes, with source/base/tested trees, ordered
parents, workflow SHA, runner image, toolchain and file digests.

The new native regressions cover constructor substitution, role/session
binding, zero channel binding, HMAC golden/tag rejection, rotation posture,
poisoned-key retirement, every truncated second-frame prefix at EOF, and
HTTP wildcard exclusion/specificity. No passing Rust result is asserted here.

## Remaining independently evidenced product gates

The candidate contains an authenticated record library and an in-process
runtime.codex wire admission path before final-use authority. It does not by
itself demonstrate a real authenticated network ingress, trusted exporter
provisioning or deployment activation. Complete these at the transport owner:

1. Obtain peer identity, fresh binding material and keys from the actual trusted
   channel; authenticate both offers, selection and policy before session use.
2. Exercise real request/response and actuation with final-use authority and
   revocation intact; test tamper, replay, wrong role, restart and key rotation.
3. Produce protected target-host, recovery, mixed-version and rolling-upgrade
   evidence for the exact source/artifact tuple.
4. Obtain distinct independent reviewer and operations acceptance before
   production implementation, activation or release flags are promoted.

Lifecycle status remains evidence-derived and unqualified/unaccepted/unreleased
without those receipts. Historical successes and author-produced statements
are never substituted for missing current-subject evidence.
