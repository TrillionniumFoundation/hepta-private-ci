# prompt.registry implementation and qualification dossier

Parent: `docs/modules/prompt.registry/TECHNICAL.md`. Canonical plan:
`docs/DEVELOPMENT.md`, selected by `docs/CURRENT.json`.

## 1. Claim boundary

Source implemented: true. Source composed: true. Product activated: false.
Independently accepted: false. Released: false. Production ready: false.
Current-source files, operation/test navigation and actual executed receipts are
separate evidence. A core-only pass, a generated source archive or a historic
run cannot qualify the current product candidate.

## 2. Source and ownership

The deterministic owner is `codex-rs/hepta-prompt-registry`. Agentd composition
is `codex-rs/hepta-agentd/src/prompt_runtime.rs`, not a phantom prompt_pipeline.rs.
Final-use validation and durable leases live in prompt_final_use.rs and
prompt_final_use_store.rs. The actual cached/provider-policy consumer is
`codex-rs/ext/hepta-prompt`; the intelligence compiler remains in
`codex-rs/hepta-intelligence/src/prompt_delivery.rs`. The optimizer is read-only.
Historical apply-prompt scripts are not part of the delivered build path.

## 3. Public operations

Signed operation-bound publication/admission/relation/realization/lifecycle
paths are conventional checked-in source. Factor lifecycle is Draft, Admitted,
Retired, Revoked. Model compatibility includes model/version, tokenizer,
template, tool schema, context profile, locale, role and payload identity.
Registry insertion does not auto-select or activate a factor.
The complete bounded API and typed recovery policy are in
`docs/modules/prompt.registry/API_CONTRACT.md`.

## 4. Durable storage and maintenance

Strict V4 metadata retains factors, realizations, bindings, relations,
supersession, payload references and lifecycle events. Immutable extents precede
atomic metadata selection. An uncertain post-rename outcome poisons the writer
until reopen/reconciliation; diagnostics do not expose authoritative access.
Copy-compaction omits inactive payloads, preserves retained-history identity,
and does not change or erase the original owner. Identical completed checkpoint
retries are idempotent. Partial/different/unsafe destinations are not overwritten.
Strict restore verification requires a trusted exact identity and never repairs
or creates the candidate. The detailed runbook is `OPERATIONS.md` beside the API.

## 5. Actual-use boundary

Preparation and durable dispatch claims share the current-use validator with a
trusted host clock. Cached ready attachments reconsult the owner and reject
identity changes. A revoked staged context must fail before dispatch recording,
and still fail after restart, leaving no dispatch claim for the rejected attempt.
The extension separately tests owner withdrawal before provider-policy begin.
These are source-level owner/consumer tests. Strong cancellation after an already
admitted dispatch, live transport, streaming/final-output consumers and deployed
host-configuration freshness are not established by this source test alone.
Terminal outcomes continue to record what physically happened.

## 6. Verification and performance

The read-only module workflow freezes one source and base identity for core and
product profiles, each on exact-head and deterministic synthetic-merge lanes.
Each command produces an exit status and log digest. Compiled test inventories
must contain named regressions; zero matched tests cannot count as success.
Checkpoints/restore failures, corruption, pre-rename failures, post-rename
poisoning, orphan tails and idempotent reconciliation have native test cases.
This is not a complete real-power-loss or device-failure campaign.

Actual ignored profiles measure 1k/8k/16k logical records, bounded fsync samples
and the one-realization Agentd compile-stage/current-use path. Their sample and
memory interpretation is in `PERFORMANCE.md`. Retained event history still grows;
metadata capacity, original/backups erasure, and oldest-reclaimable timestamps
are not magically solved by omitting inactive bytes from a new checkpoint.

## 7. Remaining evidence gates

Passing all current exact-head/base-merge core and product checks; independently
validated live transport/output cancellation; externally fenced checkpoint
activation and raw-byte retention/disposal; a durable age policy where required;
target-host security/semantic review, protected postmerge checks, operator
activation/acceptance and release. No source change grants these decisions.
