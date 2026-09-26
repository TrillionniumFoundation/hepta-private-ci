# memory.retrieval threat model

## Protected assets

- exact memory record/revision/content identity;
- Lane C generation vector and owner frontiers;
- model, tokenizer, encoder, template and tool-schema identities;
- retrieval policy and HNMF snapshot;
- selected and actually delivered candidate identities;
- learning assignment and exposure receipts.

## Trust domains

The SQLite cognitive store, vector encoder/index owner, knowledge-graph projection, Agentd product-context owner and learning ledger are separate owners. A digest proves integrity and identity binding; it does not by itself prove issuer authenticity. Authentication must come from owner-only capability construction or a verified signature/registry boundary.

## Principal threats and controls

### Candidate poisoning

A low-score or disabled-channel candidate must not force global OOD or contradiction abstention. Safety evaluation is restricted to the policy-admitted set. Owner generation, exact snapshot binding and final source revalidation prevent stale or invented records from becoming delivered context.

### Contradiction amplification

Grouping all contradiction-support records under one request digest can create false conflicts. Proposition and polarity are explicit; same-side support is not a contradiction. Zero-weight contradiction edges are inert.

### Generation substitution

A provider may attempt to combine a current memory cut with an old model, policy or engram. `RetrievalExecutionContextV1` and the product context state digest bind all identities. Rotation is epoch-fenced and `current()` is checked before publication and final use.

### Revocation race

An in-flight request can observe a context before revocation. Agentd reloads the current context before response publication. The product provider validates its lease and state digest on each call; revocation removes the context and advances the epoch.

### Receipt forgery

Self-consistent unkeyed digests are not issuer authentication. Public constructors validate structure, while product composition must restrict owner receipt creation to authenticated owner adapters. Cross-process receipts require signatures or MACs bound to owner key epoch, scope, purpose and generation.

### Resource exhaustion

All candidate, node, synapse, hop, step, dimension and result counts are bounded. Vector snapshot validation is linear in the bounded snapshot. Qualification includes ceiling probes and RSS/CPU thresholds.

### Rollback and stale recovery

Recovery accepts an independently retained state digest and exact epoch. A non-revoked recovered context also requires a future lease and validates the complete execution context. Durable deployment must keep recovery receipts outside the Agent-home rollback domain.

## Residual risks before activation

- complete four-mode runtime dispatch is not yet accepted;
- calibrated OOD distributions are owner/model dependent;
- cross-process generator receipt authentication remains a composition obligation;
- full concurrent end-to-end Agentd SLO evidence and fault-injection acceptance remain external gates;
- branch protection and independent review are repository governance controls, not properties of the Rust crate.
