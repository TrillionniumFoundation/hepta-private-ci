# context.compiler runtime follow-up — 2026-09-27

## Delivered source and claim boundary

This continues PR #1076 on `codex/context-compiler-full-closure-review-20260927`; main and other module branches are unchanged. The runtime change is commit `f2af97f944cef7219d5c0c0fb1b2fc56c56da055`. A fixture-only generic-argument correction is commit `c21a781119e9fc241197b61a304698f023c8979b`, tree `9f779326e71a63764cf7a9cc085948b0421f82ec`. The subsequent documentation commit binds these exact runtime blobs rather than claiming its own hash before it exists.

The four requested phases are **not fully complete**. These are direct fixes to the active Agentd owner, not a newly activated V3 owner, a substitute execution spine, a self-writing migration workflow or production acceptance. The earlier detailed design remains byte-for-byte under `docs/modules/context.compiler/design-baseline`.

## Actual runtime changes

The active `exact_context_delivery` path now reserves one preparation per turn before its first await, counts preparations against bounded capacity, and rejects unresolved/repeated attempts rather than admitting another physical send. An RAII reservation is released on cancellation before a durable claim. Compiled context is shared with `Arc`, avoiding repeated full payload copies; no measured performance claim follows from this source change.

Tokenizer stdin, bounded stdout and process exit share the same timeout. Stdin and stdout progress concurrently. Failure kills the child and bounds cleanup waiting; cancellation retains kill-on-drop, not a fabricated synchronous reaping guarantee. File hashing uses a 64 KiB buffer, and the owner freezes its configured tokenizer identity after its first successful load. Binary/vocabulary hashes are compared against externally supplied expected pins and rechecked around execution.

Final registry revalidation now occurs **after** tokenization. Agentd holds the registry mutex while building the fresh preparation/proof and committing durable pre-send authorization. There is no await in that final region. A revocation already committed during tokenization therefore reaches the existing registry dereference rejection, rather than being hidden by a pre-tokenization snapshot. Exclusive expiry and clock rollback are checked before authorization; expiry is checked again after fsync.

The owner-side framing check now independently requires one complete developer/input_text context slot. Recursive duplicate keys, metadata-only context, wrong roles, duplicate occurrences, object-key context and concatenated context text are rejected. Other provider grammar, supported roles beyond developer, and independent framing qualification remain separate work.

Durable schema 2 separates nonfinal observations from final terminals. Indeterminate remains unresolved after reopen. A later monotone final observation preserves the earlier unknown history, while conflicting finals and time rollback reject. Semantic retries do not depend on a new callback timestamp. New observations retain the canonical provider receipt and verify its intent, digest, disposition and proof binding on reopen. Legacy digest-only records remain historical evidence, not upgraded authenticated receipts.

An uncertain directory sync after rename poisons this writer until reopen. Mutex poisoning is not silently ignored. Exact-delivery errors expose stable reason codes rather than arbitrary domain strings through Display/Debug. This does not finish raw-content redaction in all other owners and wrappers.

## Linearization and recovery limits

The durable authorization commit under the registry lock is the defined pre-send linearization point. A subsequent revocation still needs the provider/transport owner's final-use token and cancellation policy. This implementation does not claim that every revocation after an authorization commit prevents a transport send, nor exactly-once provider execution.

A process crash still loses the active construction-closed preparation/final-proof objects. An unresolved durable pre-send without those active objects returns `RecoveryRequired`. It blocks blind replay but does **not** yet complete independently authenticated late-terminal reconstruction. Do not remove unresolved records or synthesize a success receipt to bypass this boundary.

The original encoded terminal callback is not yet an independently authenticated attempt-bound acknowledgement. V3 admission/product files remain dormant, and the active composition still has provisional product-owned admission. These are implementation gaps, not merely deployment paperwork.

## Tokenizer provisioning change

The active owner now requires these additional expected digests:

```text
HEPTA_CONTEXT_TOKENIZER_BINARY_SHA256
HEPTA_CONTEXT_TOKENIZER_VOCABULARY_SHA256
```

Both must be full SHA-256 values from the selected operator-approved artifact manifest, not a runtime self-assertion that any executable on disk is trusted. Missing or mismatched pins reject. Existing provider/model/profile, executable/vocabulary paths, version, normalization and timeout settings remain required. A changed profile needs a new owner generation, not an in-place environment-variable mutation after first use.

These pins detect observed file drift; they do not establish immutable mounts, interpreter/shared-library identity, resistance to replace-and-restore, a sandbox, or semantic agreement with the real provider tokenizer. Golden provider/model token counts and independent artifact qualification remain required. The subprocess fixtures used by tests are explicitly protocol fixtures, not true tokenizer evidence.

## Schema-2 migration and rollback procedure

Before any deployment, stop new admissions and drain or independently reconcile outstanding provider attempts. Preserve the registry and exact-delivery directory together, including their owner identity, permissions and unresolved-attempt inventory. Record a checksum of the quiescent backup and the selected binary/configuration artifacts. Do not copy a live changing JSON file as a claimed consistent backup.

Opening a schema-1 file performs a deterministic in-memory migration: legacy Indeterminate entries move to nonfinal history; final entries remain final. The next ordinary durable mutation publishes schema 2 through the existing write/fsync/rename/directory-sync sequence. Failure after rename fences the writer and requires reopen; it must not be retried using stale in-memory state.

A schema-1 binary cannot safely read schema-2 state. Rollback therefore requires a compatible quiescent backup **and** independent reconciliation of all attempts since that backup. Never downgrade by deleting observations, changing the schema integer, clearing a pending attempt, or treating absent provider evidence as NotDispatched. This procedure is not a completed target-host rollback drill.

Capacity remains bounded. This change does not implement long-lived archival/retirement or strengthen every filesystem/symlink/rollback-domain boundary. Those gates remain listed in CURRENT_STATE.json.

## Verification actually performed

- Original owner bytes were checked against Git blob `631cc9a868096845d5799dc0aa46ff6084631499`; all six modified/added source blobs were checked against their resulting Git identities.
- A portable patch was constructed from the exact original and final source; `git diff --cached --check` passed. This checks patch whitespace, **not** rustfmt, compilation or Clippy.
- **10 local Python tests passed** for current-state generation, deterministic five-file projection, preservation of prior contract inventories, registered runtime-byte hashes, and rejection of drift, missing files, symlink paths, escaping/duplicate paths and false acceptance/execution states. The raw log and exact tested script identities are in `runtime-state-python-tests.log` and `RUNTIME_LOCAL_CHECKS.json`.
- Five current projections were rendered and compared against the local generator outputs. The two baseline JSON inputs were independently checked against their preserved Git blobs. The full repository `validate_bindings`/readiness suite was **not** executed in this partial local checkout.
- **21 additional Rust regression functions** are registered: tokenizer protocol (4), strict JSON (2), owner/state (12), and signed real-registry subprocess-barrier races (3). They are **not executed locally**. Together with the inherited 19 functions this is 40 added Rust regressions, not 40 passes or whole-module coverage.

No local Rust compiler, pinned rustfmt, complete workspace, actual provider/model tokenizer, or selected target host was available. Rust formatting, compilation, E2E, strict lint, dependencies, crash/process execution and target-host metrics are unverified. Pending/queued GitHub checks are not passes. The existing read-only source-head and deterministic synthetic-merge workflow must establish fresh evidence for the final candidate, not inherit this document's source anchor.

## Remaining delivery gates

Direct compiled V3 authority/product cutover and default-off legacy gating; independently controlled admission; immutable real tokenizer/runtime qualification; full provider framing and typed slots; transport final-use/cancellation composition; post-crash proof reconstruction and independently authenticated late-terminal acknowledgement; cross-holder redaction; long-lived capacity/retention and filesystem qualification; final native source/merge execution; named-host p50/p95/p99 and resource measurements; independent acceptance and operator-controlled activation/release all remain open. No such authority is granted here.
