# Ordinary Cell and initial-material PQ composition

## Source and claim boundary

This change continues the ordinary Cell branch at
`a6c58700d23efd575d2803637aa7d9203d27e7bf` (PR #4497). It composes the canonical
PQ source changes from `bcb8f97164cefe494918fb0efe482029d7dfe6be` through
`cd3c1b860f2b0f05c24bfb8d4b5da6ba7f99704a` (PR #4558), retaining the newer
Cell material closure, cancellation, Windows private namespace and live-owner
fences. The unrelated older PoN/vendor commits on the PQ branch are not a source
replacement for #4497.

The change does not qualify a deployment or the entire Chain as post-quantum.
The protected configuration, issuer, key custody, signed clock service,
revocation distributor and durable external CAS frontier remain independently
operated trust dependencies. Temporary services and fixed test keys establish
local behavior only. The canonical protected Unix transport currently supports
Linux; unsupported platforms refuse this PQ service composition. The explicit
classical Windows owners retain their prior platform contract.

## Ordinary consumer binding

`UnixFinalUseAuthorizer::open` selects canonical PQ only when the protected
configuration explicitly contains `"authentication_profile":"ml_dsa65_v2"`.
The existing untagged classical configuration remains classical and bounded to
64 KiB. Unknown explicit profiles fail. A malformed PQ config, failed PQ
signature, clock error or frontier error never invokes the classical constructor.

The ordinary evaluated/Cell host compares the authenticated selected artifact
profile with the actual FinalUse owner's immutable profile before opening the
inference journal. The canonical issuer signs a fresh challenge-bound grant;
the revocation feed is separately signed and freshness bound. The original
FinalUse owner consumes durable nonces and uses the independent CAS frontier.

Historical and public initial material retain the profile authenticated by the
original selector and CURRENT. Their immutable selector window uses the profile's
expiry rule: classical compatibility remains inclusive, canonical PQ is
half-open. A renewed CURRENT cannot renew an expired selection.

Initial preparation derives authentication time from the actual configured PQ
authorizer's protected clock. The same clock object is retained through initial
load observations, query observations and the `InitialCurrentOwner` provider
used by the Agentd ranker. Milliseconds are converted to seconds at the artifact
boundary. An unavailable or invalid PQ clock fails the read; process wall time
is used only by the explicit classical profile.

The initial startup execution is created before blocking-executor queueing and
is passed unchanged through trust requests and physical loading. The ordinary
Agentd attachment also checks that original deadline. The existing 120-second
budget is not restarted after a trust request or at the initial loader. A failed
post-load preparation retains the original session for explicit cleanup.

## Incompatible experimental V2 retirement

#4497 previously contained a separate experimental raw-key ML-DSA V2 API. It
used a different signing domain/context, envelope, trust digest and schema-3
store variant. That API is not wire or state compatible with canonical PQ.

The active implementation now has one canonical PQ profile. The old
`open_ml_dsa65_v2` constructor, raw-key helper and their obsolete test support are
removed. The original native Agentd turn/start test now exercises the canonical
protected configuration route with real ML-DSA signatures and separate signed
clock, signed revocation-feed and durable frontier service fixtures.

An old experimental V2 configuration or schema-3 PQ state must fail, rather
than being reinterpreted as canonical or silently reinitialized. In particular,
failure must not erase the durable claim journal. No automatic old-to-new state
or key migration is provided by this composition. A production transition needs
an independently authorized migration preserving spent nonces, revocation
generations and external frontier continuity. Creating a fresh namespace alone
does not establish that migration.

## Verification scope

The added or extended local regressions cover:

- incompatible experimental state refusal with snapshot and claim journal
  unchanged;
- real ML-DSA CURRENT and selector verification for both initial material
  profiles, rejection of a classical signature under PQ, and exact selector
  expiry while CURRENT is still valid;
- retention of the same protected clock object and refusal after the real
  signed clock service becomes unavailable, without wall-time fallback;
- the original initial and evaluated loader refusing an expired or cancelled
  startup before journal admission, issuer use or model spawn;
- canonical PQ at the existing native Agentd turn/start fence, preserving the
  original durable terminal record and reopen checks.

This document describes the implemented checks, not a test-pass certificate.
Exact commands, toolchain, results and unrun platform/model-dependent cases
must accompany the candidate's validation record. Large pinned-model tests and
independent WAN/deployment qualification are not implied by these fixtures.

The existing four-lane Cell CI job retains its source-head/base-merge and
x64/arm64 matrix, 60-minute job budget, and original 23/40/3 test minima.
Additional mandatory receipts run the 195-test contracts library, the exact
initial-material, protected-clock and original-startup regressions, and the
original native PQ turn/start case. The native case first builds the real locked
Codex CLI from that tested tree, validates the original Cargo JSON/package/ELF
binding, and checks its executable hash before and after use. These are required
future candidate observations, not local execution claims.

`CALLERS.toml` retains its original scan roots, ignored-path policy and typed
FinalUse receiver checks. It names the canonical delegates explicitly and pins
their reviewed source bytes. The authenticated CURRENT factory has its own
closed caller set after the ranker refactor. This static source proof grants
neither runtime authority nor cryptographic/deployment qualification.
