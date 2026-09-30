# Retrieval operations

Status: source-level procedures. The ordinary binary has an explicit pinned-descriptor loader; native execution and deployment qualification remain pending. `HEPTA_COGNITIVE_RETRIEVAL_MODE` supports absence/`compatibility`, `hnmf-shadow`, `hnmf-canary` and `hnmf-required`. All HNMF modes require a current provider at startup; compatibility forbids attaching one. See `PROCESS_BOOTSTRAP.md`, `ROLLOUT_POLICY.md`, `CANARY_AND_ROLLBACK.md`, `ADR/0003-signed-lifecycle-delivery.md` and `ADR/0004-protected-rollout-and-shadow-budgets.md`.

## Host composition

Provision the external frontier service independently of the Agent home and pin its verifying key. Pin the context publication key separately. Obtain a real current execution context from the generation owners and a matching signed publication. An embedding can use `LeasedMemoryRetrievalProviderV1::from_loopback_frontier` with an explicit loopback `SocketAddr`, total request timeout in 10 ms–5 s and maximum publication lease in 1–300000 ms. Install the publication, then compose the provider through `AgentdConfig::with_cognitive_retrieval_context` and select the explicit host mode. The config validates Agent/body identity; do not fabricate missing fields to make it start.

The ordinary binary alternatively accepts paired `--retrieval-bootstrap-descriptor` and `--retrieval-bootstrap-descriptor-digest` arguments. The loader verifies the exact protected descriptor bytes, loads a bounded strict signed publication and performs a fresh challenged-frontier acquisition. It rereads the publication on each acquisition to support signed rotation; identical reinstall cannot renew the monotonic lease. Descriptor v1 preserves the historical fixed canary policy. Descriptor v2 requires a complete ppm/salt rollout policy and four non-delivery structural ceilings. The complete descriptor, wire, signature, rollout and filesystem trust contracts are in `PROCESS_BOOTSTRAP.md` and `ROLLOUT_POLICY.md`.

The endpoint, key pins and rollout policy are protected host configuration. No signing private key is transmitted or generated. The external service's persistence/recovery qualification, actual protected launcher/sandbox and full-chain ranker/learning/vector composition remain unfinished. Source implementation of the CLI does not establish those owners or imply a passed real-process startup test.

## Frontier wire protocol

A connection carries one request and one response. Each is a four-byte unsigned big-endian JSON byte length followed by exactly that many UTF-8 JSON bytes, maximum 4096 bytes. One total deadline covers connect, every partial write/read and decoding; it is not reset by trickle traffic.

Request fields: `schema` (`hepta.agentd.retrieval-frontier.rpc.v1`), `owner` (Agent ID), `body_generation` (u64), `challenge` (64 lowercase hex characters).

Response fields: the same schema/owner/body/challenge plus `authority_epoch`, `sequence`, `publication_digest` (64 lowercase hex characters or explicit JSON null for revocation), `expires_unix_ms` and `signature` (128 lowercase hex characters). Unknown/duplicate fields and noncanonical hex are rejected. The signature is over `MemoryRetrievalFrontierV1::signing_bytes()`, **not JSON bytes**. The provider then validates time, signature, monotonicity and current publication identity. The transport alone grants no authority.

## Rotation, revocation and recovery

Rotation: publish a strictly advancing epoch/sequence at the independent owner, then install or atomically replace the matching signed context publication. A digest change at the same epoch/sequence is rejected. Requests crossing rotation fail final revalidation rather than use a mixed generation. The atomic acquisition carries the publication digest and signed deadline, so a new sequence/lease invalidates old reads even when context content is unchanged. Key or rollout-policy rotation requires new authorized host configuration and an approved descriptor digest; request-supplied keys, modes, salts, thresholds or budgets are never accepted.

Revocation: advance the sequence and publish null. HNMF delivery rejects it and the provider clears the pinned context on observing the new frontier. Unavailable service, timeout and invalid response close required and selected-canary delivery, without switching treatment arms. Shadow and unselected-canary requests continue the separately defined baseline delivery and never label discarded HNMF results as exposure. Their descriptor-pinned candidate/node/synapse/step limits are checked before optional HNMF work. These static limits do not provide separate CPU, RSS, allocation, wall-time or cancellation isolation.

Recovery: restart with an empty context cache, obtain a fresh challenged frontier, verify it against protected key pins, install the matching publication and revalidate the SQLite cut. Restoring a cache/Agent-home backup is not recovery of external authority. If the frontier owner's monotonic state cannot be established, keep HNMF delivery disabled. A rollback to a lower canary threshold or compatibility is a new host launch using approved descriptor bytes; do not mutate a live descriptor beneath its digest.

## Qualification and incident evidence

Use `just test --locked -p codex-hepta-memory-retrieval`, `just test --locked -p codex-hepta-agentd`, the owner/learning packages, all-target Clippy and repository formatting checks. Preserve actual command results and executed test counts. Run current-main, exact source-head and ordered-parent base-merge lanes; no skipped lane is a success. The merge base must be the main fetched for that run; event metadata is retained only as provenance.

Retain source SHA/tree/parents, descriptor digest and schema, rollout-policy version/threshold/salt digest, shadow ceilings, context and policy digests, owner/body, frontier epoch/sequence, disposition, omission/completeness, resource counts and final-use failure reason. Never log raw private memory, query text, signing keys or raw rollout salt. `E2E_MEASUREMENT.md` specifies the v2 exact-source sample/receipt contract and counter attribution; it does not supply measured values.

The original historical microbenchmark ZIP and a canonical member-hash manifest are retained under `qualification/memory-retrieval/BASELINES/808b68350dc4f9d1b542803ac75a8d7e255ee836dd95de2255ad42a57b23b212/`. The maintenance workflow verifies their bytes with `hepta_memory_retrieval_archive.py`. They remain historical evidence for their original source, not current-head or E2E qualification. Git retention detects content changes; protection against administrator deletion requires an independently controlled retention service. Archive new raw benchmark and E2E evidence before temporary Actions artifacts expire.
