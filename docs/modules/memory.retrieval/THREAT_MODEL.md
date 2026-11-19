# memory.retrieval threat model

## Assets and trust boundaries

Protected assets are private memory content, exact revisions and sources, Lane C generation identity, retrieval policy, model/index identities, recall receipts, delivered-context identity and learning assignments. Trust boundaries are SQLite owner to adapter, generator owner to recall core, current-context provider to Agentd, optional ranker to delivery, Agentd to learning ledger, and qualification evidence to human promotion.

## Principal threats

- Forged or replayed generator receipts that are internally hash-consistent but not owner-issued.
- Cross-generation, cross-scope or restored-old-database candidate substitution.
- Poison candidates that force global OOD/contradiction abstention while remaining below policy admission.
- Same-side contradiction evidence misclassified as opposition.
- Zero-activation or zero-weight graph structure creating support or conflict.
- Context-provider rollback, stale rotation, lease extension, revocation bypass or owner/body substitution.
- Ranker addition of unadmitted records or exposure logs that differ from delivered content.
- Vector-score relabelling without a real encoder/index owner.
- Benchmark/result forgery, stale source maps, draft/self-approved promotion and mutable baselines.

## Controls

Inputs are bounded, typed, canonically ordered and generation-bound. Exact owner revisions/content/source are revalidated before materialization and again before final use. Provider changes are revision fenced; leases and revocation fail closed. Shadow results cannot be recorded as exposure. Production-claim promotion requires exact-head independent approval. Qualification receipts bind source/tree/host/log/limits digests and production baselines are append-only reviewed manifests.

## Residual risk

In-process hash receipts provide integrity but not cryptographic remote identity. A future cross-process generator boundary requires sealed capabilities or signatures with issuer, purpose, scope, key epoch and revocation. The current repository also lacks a qualified vector encoder/index owner and production target-host acceptance; these gaps keep production, activation and release false.
