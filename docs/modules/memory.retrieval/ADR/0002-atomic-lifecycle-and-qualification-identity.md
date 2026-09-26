# ADR 0002 — Atomic lifecycle binding and exact qualification identity

Status: source decision, qualification pending. Supersedes any description of reader-owned lifecycle mutation or self-hash-only recovery; it does not grant release authority.

## Problem

A context's payload digest is unchanged by a same-payload rotation or lease renewal. Comparing only payload digests allows an older in-flight request to pass after an epoch change. Reading payload, epoch and lease using separate method calls is also a torn observation. A checkpoint hash can be perfectly valid while predating a later revocation.

## Decision

The product reader returns one locked payload/lifecycle-digest/lease observation. The state digest uses a new v2 domain and binds owner, body, epoch, deadline, revoked disposition and payload. The Agentd read receipt commits that lifecycle digest, and final checks re-acquire it after asynchronous gaps. Execution deadlines cannot outlive the acquired lease.

The composition root receives a reader and a separate private-field control capability. Request code has no product mutation override. Renewal and rotation use epoch compare-and-swap; revocation is terminal and retry-idempotent. Monotonic and wall deadlines jointly bound validity, including backward-clock defense.

Recovery requires a separately current owner witness of the exact checkpoint epoch and hash. The legacy factory fails closed. The RwLock provider remains an in-process component; it does not claim durable witness ownership, cross-process fencing or atomic disk publication.

## Qualification identity

A checked-in document cannot contain the SHA of the commit that contains that document without a self-reference problem. Preserve `sourceBase` as provenance and `observedAtHead` as an explicit observation of a known source. Live qualification records the actual checkout commit, tree, ordered parents and relevant tree objects outside the source tree, before and after execution. A parent observation is never relabeled as a green current-head run.

Synthetic merge qualification freezes the observed main parent and source parent, uses deterministic commit metadata, constructs the candidate twice and checks both the hash and parent order. No qualification tool moves main or grants merge authority.

## Measurement identity

Microbenchmark, E2E execution, independent approval and release are separate evidence classes. The E2E parser requires all nine stages, actual execution counters distinct from observations, completed learning append, consistent outcomes/rates and request-scoped resources. Passing parser fixtures proves the validator, not a real E2E workload.

Local exclusive-create/fsync publication provides non-overwrite behavior for a receipt path, not external WORM storage. Long-term retention and independent acceptance remain owner duties with separately retained receipts.

## Consequences

Old lifecycle hashes and payload-only compatibility observations cannot be promoted implicitly. Expired or revoked providers cannot be revived through a convenience renewal. Every deployment must supply and qualify a protected writer and independent durable witness. The outstanding contradiction metadata, real encoder, four-mode runtime and actual E2E gaps remain explicit blockers rather than being hidden by broad completion labels.
