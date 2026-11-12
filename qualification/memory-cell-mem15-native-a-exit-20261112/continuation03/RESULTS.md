# MEM15 native A-exit capture: recovered continuation 03

**The four capture fixtures passed their expected control outcomes. Scientific acceptance remains HOLD.** Original receipts and two independent readback checks establish separate importer A and worker C processes, exact ACK/input bindings, source-read deltas **4 / 0 / 4 / 3**, and native HTTP counts **1 / 1 / 1 / 0**. The capture observers report **0 model generations**; no memory-benefit episode was scored.

**The authoritative outer job identity and terminal are still pending a separate readback.** This package preserves the original file status `capture_controls_passed`; file or archive existence is not used to manufacture a successful outer terminal. A later terminal record can be appended without rewriting this checkpoint.

## Exact source and execution scope

The tested source is commit `bbbcc63003a88d0396a9694222dc98dc8c0d59d6`, tree `fe00b2618f39e942ec6b1a8af2d63ec585e5f892`, with `codex-rs` tree `ed240f298fa2cbb104c65054596e64e7d1e9bca8`. All original phase receipts and RESULT show clean, identical before/after source identities; the rewrite patch is empty. The repeated 14 source pins match the source files retained with the initial attempt. This archive does not repeat all those source postimages.

The three controls that passed in continuation 02 were reused with byte-identical JUnit, receipts, logs, RESULT, and terminal evidence. **Zero new control tests** ran in continuation 03. Its four capture Rust executions passed with no selected failures or skips; all four JUnit UUIDs, exact case names, original logs, and receipt time windows were checked. Scoped fix and final format passed. Recorded binary before/after pins stayed identical; executable bytes themselves were not downloaded.

## Per-arm result and the four C exit codes

| Arm | A PID / exit | C PID / exit | A-exit to C-start gap | Source reads | Native HTTP | Nonce in HTTP body |
| --- | --- | --- | ---: | ---: | ---: | --- |
| Attach | 296752 / 0 | 297201 / 1 | 8.199 s | 4 | 1 | Yes |
| Reader-off | 297684 / 0 | 297743 / 1 | 8.114 s | 0 | 1 | No |
| Withhold | 298228 / 0 | 298245 / 1 | 8.157 s | 4 | 1 | No |
| Tombstone | 298753 / 0 | 298785 / 1 | 8.133 s | 3 | 0 | No HTTP body |

**All four C processes exited 1, as expected for these capture diagnostics.** Attach, reader-off, and withhold received the retained HTTP 409 response `capture-only; no model request issued`. Their journals contain a failed observed terminal, with `observation.terminal_observed=true`. The native RESULT's top-level `terminal_observed=false` records absence of successful completion; it does not mean no failed terminal was observed. Tombstone records `Reserve → Dispatch → AbortBeforeEffect`, `canonical-head-changed`, and no `Started` or `Observe` event. Prepared Dispatch metadata is not an observed HTTP request.

For every arm, A's raw stdin, sole ACK in stdout, snapshot digest, owner fields, PID, successful OS exit, and C's later distinct PID were cross-checked against INTENT/STARTED/EXIT and journal records. C receives the same fixed 105-byte public prompt; A's snapshot is not injected into C's stdin. A is a deterministic import process, while the parent harness and owner remain alive. This is process-path fixture evidence, not evidence of model learning.

Tombstone's original SERVER-to-STOPPED interval is **120.093767174 seconds**. The complete observation window covers C and records zero connections. Its archive has no HTTP directory, ATTEMPT, or provider-request file; native revocation and journal evidence support the recorded pre-effect rejection.

## HTTP bytes, mapping, and the reader-off/withhold distinction

For the three HTTP arms, the raw request's Content-Length and exact body bytes match the observer, ATTEMPT, mapping, and manifest pins. Each constructed mapped request's `/input` is the complete original native body UTF-8, with no discarded fields. The original response is the diagnostic 409 and the original OBSERVED record says `CAPTURED_WITHOUT_GENERATION`, `physical_model_calls=0`. These capture records establish the zero-generation observation; token-only output is not used to claim a generation event.

The mapping treats the native JSON as a single user-message string; **native role semantics are not preserved**. The constructed `provider-request.bin` is retained mapping evidence, not evidence that a model generation request was sent.

Reader-off and withhold both omit the fixture nonce but are **not equal** as raw bytes or parsed JSON. Their full bodies are each 26,576 bytes and differ in exactly three top-level fields: `client_metadata`, `input`, and `prompt_cache_key`. No dynamic field was removed or normalized. Reader-off's source-read delta is 0; withhold's is 4. These observations do not establish a fully memory-free baseline.

## Token-only admission was rejected

| Arm | Retained prompt tokens | Limit | Admission |
| --- | ---: | ---: | --- |
| Attach | 7,565 | 1,024 | REJECTED_INPUT_TOKEN_BUDGET |
| Reader-off | 7,007 | 1,024 | REJECTED_INPUT_TOKEN_BUDGET |
| Withhold | 7,029 | 1,024 | REJECTED_INPUT_TOKEN_BUDGET |
| Tombstone | No mapped request | 1,024 | Not executed |

Complete TOKEN_ONLY outputs, rendered prompts, integer tensors, and the 1,376-byte tokenizer-only script are retained. Tensor lengths equal the recorded counts, and each output is hash-bound to its original mapped request. The recorded preflight used no truncation and loaded no model weights. **This was post-capture tokenizer-only preflight, not generation-entry validation; all three available inputs failed the budget.** Recovery did not rerun the tokenizer.

## Qualification boundaries and preserved history

`observer_authenticated=false`, `production_authenticated=false`, `C_namespace_isolated=false`, `full_memory_off_demonstrated=false`, and `retention_off_implemented=false` remain explicit. Separate task roots and cleared child environments do not prove complete old file/tool/chat/cache closure. The native per-arm `model_generation_count` and `physical_provider_request_count` remain **null** in their unchanged original files; joined counts are separately bound to capture observer records. Private owner receipt/database bytes are not included: the review checks their retained public digests and exact ACK bindings and makes no production authentication claim.

The initial precompile failure and continuation 02's four worker-lookup failures remain original failures. Continuation 03 resumed only paths proven not to have started A/C; it did not replay prior build/V8 or the three passed controls. Four independently generated fixture nonces are not a paired memory-benefit cohort. Real scored benefit remains **0** and acceptance remains **HOLD**.

## Original archive and verification

`capture-bbbcc630-03.tar.xz`: **83,100 bytes**, SHA256 `147bd82bd791c0df8376fc14678a892313de3403884b54be2c176f112917beac`. Both binary chunks share a fixed file version and passed individual hashes. All **244 regular files** and **243 original member-manifest entries** were checked; unsafe paths, links, special files, and duplicate names were rejected. Original RESULT is **47,948 bytes**, SHA256 `e67f4e4220995704db06f27d86743021e4fa4308b6daf4cb6b150312fcffa6ca`.

[EVIDENCE.json](EVIDENCE.json) is the compact result index. [VERIFY.json](VERIFY.json) combines the artifact check and independent **447-check / 0-failure** process review, with exact pins for the full [ARTIFACT_VERIFICATION.json](ARTIFACT_VERIFICATION.json) and [INDEPENDENT_PROCESS_REVIEW.json](INDEPENDENT_PROCESS_REVIEW.json). Complete direct SDK responses, original chunk bytes, the original archive, all extracted originals, and the source-independent validation scripts are preserved in this recovery package. No original execution file was edited and no test, native job, model, tokenizer, start, or reconcile was executed by recovery.
