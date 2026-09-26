# memory.retrieval operations

Status: source-level operating contract. This document is not evidence that the ordinary Agentd binary has a deployed encoder, protected witness or four-mode rollout controller.

## Startup and ownership

Open the canonical SQLite owner and obtain a Lane C cut. Load authenticated external artifacts and a retrieval policy whose digest matches the generation vector. Validate the complete execution context, including model, tokenizer, encoder, template, tool schema, compact/prompt generations and engram snapshot. Use `product_with_control` to create a bounded live lease; install only its reader in Agentd configuration. Retain its control capability in the protected composition root, never in request handlers.

The existing `HEPTA_COGNITIVE_RETRIEVAL_MODE` process selector accepts `compatibility` and `hnmf-required`. Unknown values are errors. Shadow/canary are requirements in [CANARY_AND_ROLLBACK.md](CANARY_AND_ROLLBACK.md), not additional accepted environment values. Required-mode startup must reject an absent current context; a factory in a library is not automatic binary composition.

## Rotation transaction

1. Read the control snapshot; retain its exact epoch and state digest.
2. Prepare and validate the replacement artifacts and complete generation identity before mutation. Do not splice individually current artifacts into an incoherent cut.
3. Call `control.rotate(expected_epoch, replacement, new_deadline)`. A mismatch is contention; refresh and reconcile intent, never force the epoch.
4. The in-process transition changes the lifecycle binding even for identical payload bytes. In-flight requests carrying the earlier binding fail currentness checks.
5. The durable owner must publish/checkpoint and witness the new epoch under its own crash-consistent protocol. That protocol is not implemented by the RwLock provider.
6. Retain old immutable artifacts for audit and outstanding-reference accounting; do not reactivate their old epochs.

The control operation must not be called 'durably committed' until the independent owner publication protocol provides that receipt. A crash between local rotation and durable publication is a qualification case, not an assumed success.

## Renewal, expiry and revocation

`control.renew` increments the epoch and read binding, even when only the deadline changes. The maximum lease is five minutes; operators must choose a shorter profile-specific bound with enough request/rotation margin. Both wall and monotonic deadlines apply. An expired object cannot be renewed or rotated back to life.

`control.revoke(expected_epoch)` clears the payload and produces a terminal revoked state with a zero lease. Revocation remains possible after expiry. Repeating the same completed revocation returns the existing terminal epoch. No lifecycle method on the read capability grants this control privilege.

A required-mode provider failure is not permission to silently fall back. Fail the request/startup according to the existing product boundary and retain diagnostics without raw private memory text.

## Recovery and rollback defense

Obtain the candidate checkpoint and separately query an authenticated durable owner's latest `(epoch, state_digest)` for the same owner/body identity. Call `recover_product_with_witness`, not the self-hash recovery factory. A revoked checkpoint recovers as revoked; an old live checkpoint cannot pass a witness of later revocation. Live recovery also requires a bounded future lease and a valid complete execution context.

The witness must be outside the Agent-home restore domain, authenticated, and current at the owner linearization point. A copied JSON hash, a witness synthesized from the checkpoint, or a test witness implementation is not deployment evidence. Durable owner/witness composition, disk failure, kill/restart and restoration tests remain prerequisites.

## Alerts and failure classification

Page on required-mode context absence/expiry/revocation, wrong generation/model, a step change in stale rejection or abstention, source/receipt count mismatch, hard SLO breaches, source-freshness qualification failure, or learning-owner failure. Distinguish storage corruption from optional ranker/provider unavailability; an optional component must not invalidate unrelated canonical store ports.

Log request/owner pseudonymous IDs, exact source/tree, policy and lifecycle digests, bounded counts, error class and stage. Do not log raw memory, credentials, artifact signing keys or context payloads. Count rejection, abstention and failure separately; missing metrics are not zero.

## Qualification and evidence retention

The exact-source capture script records the full `codex-rs` tree (including transitive crates and lockfiles), scripts, workflows and module/qualification documents. It verifies the checkout before and after execution. Ordered-parent synthetic merges use fixed commit metadata and compare two independently constructed commit IDs; a merge conflict is failure.

Python validator tests, retrieval package tests, Agentd lifecycle tests, microbenchmarks, end-to-end SLOs and independent acceptance are separate evidence classes. GitHub-hosted ARM tests do not establish x86 named-host latency thresholds. GNU-time RSS around cargo may include compilation and must not be reported as request RSS.

Actions artifacts are temporary. Promote accepted raw logs, source/toolchain/host identity, threshold bytes and content-addressed receipts to the approved long-term owner; never overwrite a historical receipt. `write_immutable` prevents local path overwrite and fsyncs publication, but it does not configure an external retention lock or protect against privileged deletion. Record long-term archive acceptance independently.
