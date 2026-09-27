# Retrieval operations

Status: source-level procedures; not a declaration that the ordinary binary bootstraps the provider. `HEPTA_COGNITIVE_RETRIEVAL_MODE` supports absence/`compatibility`, `hnmf-shadow`, `hnmf-canary` and `hnmf-required`. All HNMF modes require a host-composed provider at startup; compatibility forbids attaching one. Native qualification of this four-mode source integration remains pending. See `CANARY_AND_ROLLBACK.md` and `ADR/0003-signed-lifecycle-delivery.md`.

## Host composition

Provision the external frontier service independently of the Agent home and pin its verifying key. Pin the context publication key separately. Obtain a real current execution context from the generation owners and a matching signed publication. Use `LeasedMemoryRetrievalProviderV1::from_loopback_frontier` with an explicit loopback `SocketAddr`, total request timeout in 10 ms–5 s and maximum publication lease in 1–300000 ms. Install the publication, then compose the provider through `AgentdConfig::with_cognitive_retrieval_context` and select the explicit host mode. The config validates Agent/body identity; do not fabricate missing fields to make it start.

The endpoint and key pins are protected host configuration. No signing private key is transmitted or generated. Ordinary Agentd CLI loading of this typed bootstrap and the external service's persistence/recovery qualification remain unfinished. The runtime router is not a replacement for those owners.

## Frontier wire protocol

A connection carries one request and one response. Each is a four-byte unsigned big-endian JSON byte length followed by exactly that many UTF-8 JSON bytes, maximum 4096 bytes. One total deadline covers connect, every partial write/read and decoding; it is not reset by trickle traffic.

Request fields: `schema` (`hepta.agentd.retrieval-frontier.rpc.v1`), `owner` (Agent ID), `body_generation` (u64), `challenge` (64 lowercase hex characters).

Response fields: the same schema/owner/body/challenge plus `authority_epoch`, `sequence`, `publication_digest` (64 lowercase hex characters or explicit JSON null for revocation), `expires_unix_ms` and `signature` (128 lowercase hex characters). Unknown/duplicate fields and noncanonical hex are rejected. The signature is over `MemoryRetrievalFrontierV1::signing_bytes()`, **not JSON bytes**. The provider then validates time, signature, monotonicity and current publication identity. The transport alone grants no authority.

## Rotation, revocation and recovery

Rotation: publish a strictly advancing epoch/sequence at the independent owner, then install the matching signed context. A digest change at the same epoch/sequence is rejected. Requests crossing rotation fail final revalidation rather than use a mixed generation. The atomic acquisition carries the publication digest and signed deadline, so a new sequence/lease invalidates old reads even when context content is unchanged. Key rotation requires new authorized host configuration; request-supplied keys are never accepted.

Revocation: advance the sequence and publish null. HNMF delivery rejects it and the provider clears the pinned context on observing the new frontier. Unavailable service, timeout and invalid response close required and selected-canary delivery, without switching treatment arms. Shadow and unselected-canary requests continue the separately defined baseline delivery and never label discarded HNMF results as exposure. Shadow failure isolation does not yet provide separate CPU/memory budgets.

Recovery: restart with an empty context cache, obtain a fresh challenged frontier, verify it against protected key pins, install the matching publication and revalidate the SQLite cut. Restoring a cache/Agent-home backup is not recovery of external authority. If the frontier owner's monotonic state cannot be established, keep HNMF delivery disabled.

## Qualification and incident evidence

Use `just test --locked -p codex-hepta-memory-retrieval`, `just test --locked -p codex-hepta-agentd`, the owner/learning packages, all-target Clippy and repository formatting checks. Preserve actual command results and executed test counts. Run current-main, exact source-head and ordered-parent base-merge lanes; no skipped lane is a success. The merge base must be the main fetched for that run; event metadata is retained only as provenance.

Retain source SHA/tree/parents, context and policy digests, owner/body, frontier epoch/sequence, disposition, omission/completeness, resource counts and final-use failure reason. Never log raw private memory, query text or keys. Archive raw benchmark evidence content-addressably before temporary Actions artifacts expire. Git retention detects content changes; protection against administrator deletion requires an independently controlled retention service.
