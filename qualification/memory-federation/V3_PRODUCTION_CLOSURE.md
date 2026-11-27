# memory.federation V3 production-closure qualification

## Status model

This work package separates four claims that must not be collapsed:

1. **source complete** — the canonical one-peer V2 engine, in-process product
   composition, host runtime profile, and authenticated wire candidate exist;
2. **product execution proved** — exact source-head and deterministic current-base
   merge-candidate checks both passed and retained machine attestations bind all
   commands and artifact digests;
3. **independent acceptance** — an independent semantic/security reviewer and
   selected-host operator accepted the evidence;
4. **activation/release** — canary, promotion, and release authorities explicitly
   selected the product.

`productExecutionProved` remains false until both V3 qualification lanes pass for
the exact candidate source and a metadata-only receipt commit records those run
and artifact identities. Passing source tests cannot set independent acceptance,
activation, or release.

## Required source-head and merge-candidate checks

`.github/workflows/memory-federation-v3-qualification.yml` is invoked directly on
relevant pull requests, on pushes to `main`, by controlled `workflow_dispatch`,
and from the blocking `CI required` fan-in for native changes. It qualifies:

- exact commit and tree identity;
- current-base deterministic synthetic merge identity;
- implementation-map current-source verification;
- focused formatting;
- canonical V2 tests;
- quarantined V1 compatibility-feature tests;
- authenticated wire schema, credential, replay, frontier, cancellation, and
  logical two-host fault tests;
- memory product runtime and legacy regression tests;
- Memory extension final-use integration;
- Agentd/App Server composition;
- strict all-target Clippy;
- clean tested source.

Each command is executed through `scripts/hepta_ci_exec.py`. The workflow emits a
self-digesting attestation containing source/base/merge/tested commit and tree,
toolchain, command records, conclusion, and workflow identity. A second artifact
envelope binds GitHub's digest for the uploaded evidence artifact.

## Runtime closure

`FederationRuntimeProfile` is fixed by the host at Agentd composition and can only
narrow architectural ceilings. It governs owner candidates, admitted peers,
discovery concurrency, revalidation concurrency, global budget, and per-owner
budget. Request bytes cannot widen it.

Owner discovery is streamed through bounded unordered concurrency under one
global deadline while preserving completed observations. Unfinished owner slots
become explicit discovery failures instead of causing an unbounded fan-out.

Final revalidation groups bindings by exact owner/capability. Groups execute with
bounded concurrency and share one owner/capability snapshot. Unavailable or timed
out groups return typed stale statuses so callers can distinguish partial source
health. The Memory Extension still applies an all-or-nothing final-use guard to
the exact prepared payload: any stale group discards the whole prepared federated
proposal rather than silently changing already-approved bytes.

A non-empty owner result below the retrieval ceiling is `Complete`; a result at
the ceiling is conservatively `Partial` because the current owner reader exposes
no authenticated `has_more=false` witness. Empty remains `Empty`. Product-level
post-aggregation truncation remains explicit in coverage.

## Legacy boundary

The original V1 `observe` API is removed from the default crate surface and is
available only behind the `legacy-v1` Cargo feature. Product builds use the
default feature set. The dedicated qualification workflow retains one explicit
feature-enabled regression lane until the compatibility surface is removed.

## Cross-host boundary

`codex-hepta-memory-federation-wire` implements a registered canonical schema,
directional peer credential enrollment/rotation/revocation, HMAC-SHA-256,
operating-system CSPRNG nonces, fail-closed bounded replay protection,
authenticated chained frontier witnesses, and cancellation acknowledgements.

It is not connected to the current product adapter. Cross-host activation still
requires a selected mutually authenticated transport, persistent attempt and
replay state where required by the deployment threat model, two real hosts,
network fault qualification, target-host capacity evidence, independent review,
and operator acceptance. The in-process SQLite adapter must not be described as
cross-host federation.
