# memory.federation full-closure qualification

## Status and claim boundary

This work package keeps four claims separate:

1. **source candidate complete** — the one-peer V2 checked engine, the bounded in-process product caller, host-governed runtime limits, legacy isolation, and the authenticated cross-host protocol crate exist in source;
2. **product execution proved** — the exact source head and its deterministic merge with the current base both pass the retained qualification matrix;
3. **independent acceptance** — an independent semantic/security reviewer and the selected-host operator accept the evidence;
4. **activation and release** — canary, promotion, and release authorities explicitly select the product.

`productExecutionProved` remains false until the exact candidate and deterministic current-base merge lanes both succeed and retained machine-readable attestations bind the tested commit/tree, base/merge identity, toolchain, command records, conclusion, payload digest, and GitHub artifact digest. Protocol source or logical-host tests never imply independent acceptance, cross-host activation, or release.

## In-process product closure

The product runtime owns bounded streaming owner discovery, admitted-peer limits, discovery and revalidation concurrency, and one global operation horizon. Each owner operation is bounded by that shared horizon; the current profile does not claim a separately configurable per-owner time budget. Completed owner observations are preserved; unfinished or unavailable owners become typed failed coverage rather than disappearing or expanding fan-out.

Final revalidation groups exact owner/capability bindings and executes groups with bounded concurrency. Retrieval may degrade partially before proposal construction, with coverage recording omitted, unavailable, stale, and truncated sources. Once exact federated bytes have been prepared, the physical-send final-use guard is all-or-nothing: any stale or unavailable binding discards the whole prepared federated proposal instead of silently changing an already-approved payload.

A non-empty owner result below the retrieval ceiling is `Complete`; a result at the ceiling is conservatively `Partial` because the local reader does not expose an authenticated `has_more=false` witness. Empty remains `Empty`. Product aggregation records post-merge item truncation separately.

The original V1 `observe` API is absent from the default crate surface and remains available only through the explicit `legacy-v1` compatibility feature and its dedicated regression lane.

## Authenticated cross-host protocol candidate

`codex-hepta-memory-federation-wire` is an independently qualified, transport-neutral crate. It provides:

- registered, canonical, versioned query/response/cancel/cancel-ack encoding;
- directional peer credentials with enrollment, strict-generation rotation, expiry, and revocation;
- HMAC-SHA-256 authentication over peer identities, credential generation, times, CSPRNG nonce, and canonical message digest;
- bounded fail-closed replay protection;
- authenticated chained frontier witnesses for generation/frontier/clock rollback detection;
- an attempt registry and typed cancellation acknowledgement whose observation times cannot predate attempt start or regress across repeated terminal/cancel observations.

The crate is deliberately not a product workspace member or Agentd caller yet. Its separate manifest and qualification lane prove protocol behavior without activating a network service or widening the current in-process product claim.

## Qualification matrix

`.github/workflows/memory-federation-v2-final-verify.yml` runs on relevant feature/fix branches, pushes to `main`, controlled `workflow_dispatch`, pull-request fan-in, and reusable workflow calls. Both the exact-head and deterministic-merge lanes execute `scripts/run_memory_federation_qualification.sh`, which verifies:

- exact implementation-map source identity without mutating generated provenance;
- V2 format, tests, compatibility-feature tests, product adapter, Memory extension, Agentd/App Server composition, and strict Clippy;
- authenticated wire formatting, metadata resolution, schema/authentication/replay/frontier/cancellation tests, and strict Clippy;
- clean tracked source after execution.

The workflow uploads a self-digesting payload and a second envelope bound to GitHub's uploaded-artifact digest. The payload verifier recomputes the exact checkout identity, mapped source manifest, command manifest, claim boundary, and referenced evidence hashes. The full-closure payload also retains and hashes the Cargo-resolved standalone wire lockfile so its dependency resolution can be reviewed and promoted into tracked source before locked qualification. A failure receipt is diagnostic evidence only and cannot set `productExecutionProved`.

## External cross-host gates

Before any product network activation, all of the following remain mandatory:

- a selected mutually authenticated transport whose certificate identity is bound to the frame peer identity;
- secure credential enrollment, storage, rotation, revocation, and recovery on the selected hosts;
- persistence rules for attempt/replay state consistent with the deployment threat model;
- two independently provisioned real hosts exercising revoke-during-I/O, partition, timeout, replay, rollback, clock skew, cancellation, restart, and overload;
- measured latency, capacity, backpressure, replay-cache pressure, cancellation tail, and recovery behavior;
- independent semantic/security review, operator acceptance, canary, promotion, and release authority.

Until those gates pass, the only accurate label is **authenticated cross-host protocol candidate**. The current SQLite-backed product adapter remains **in-process read-only federation**.
