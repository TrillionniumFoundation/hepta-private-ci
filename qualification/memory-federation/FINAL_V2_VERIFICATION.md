# memory.federation V2 current verification

- canonical convergence branch: `work/product-convergence-20260923`
- source candidate parent: `5fa16b2a05a365169419b49150d45ff3c9f911cd`
- frozen source candidate: `95b8d75ab67bc4aee31bf166ec794936d5018a05`
- frozen source tree: `cd50cd9c14adef5380e1d38a14367adc0546c7a7`
- PR base main at source freeze: `7ddbfac88525196e7a4b31387ceae194958275f5`
- status: `source_candidate_local_regressions_passed_pending_exact_and_merge_execution`
- claim boundary: read-only local product-composition candidate; `productionImplementation`, `productExecutionProved`, independent acceptance, activation, promotion and release remain false

## Candidate boundary

The frozen source candidate contains the implementation, tests, focused workflow and technical documentation for this convergence. Later commits may update only the metadata paths declared in `IMPLEMENTATION_MAP.json` unless the source candidate identity is regenerated.

The candidate adds or retains these source-level properties:

- exact query-bound and domain-separated V2 response/result integrity;
- live authority observation before transport and after I/O;
- one interruptible attempt per nonce with no engine-owned retry;
- bounded deterministic multi-owner product aggregation;
- active owner database generation resolved through the memory owner's validated pointer;
- active generation included in the V2 product generation binding;
- predecessor reader fencing before and after capability/data reads;
- missing active pointer fails closed after any recovered generation exists and cannot resurrect the legacy database;
- recovered-owner revoke, correction and forget regressions;
- incremental bounded discovery that preserves completed healthy results and exposes bad or unresolved owners as typed failure coverage;
- V2-only product attachment and batch final-use revalidation;
- a physical provider regression proving a rejecting final-use guard runs before HTTP dispatch;
- exact-head and deterministic current-main synthetic-merge jobs using locked Cargo state and focused strict lint.

The source candidate remains an in-process checked adapter over local owner stores. The Rust structs and response digest are not a registered authenticated cross-host wire protocol and do not authenticate a remote machine.

## Local evidence

`LOCAL_QUALIFICATION.md` records the focused local commands and their limitations. The important negative path was reproduced before the fix and then reversed by the candidate:

- before: recovered owner state could be revoked while legacy-path discovery and final-use revalidation still accepted predecessor evidence;
- after: current discovery follows the recovered owner, predecessor readers are rejected, recovered correction/forget state wins, and pointer loss fails closed rather than selecting the predecessor database.

A diagnostic one-second discovery horizon was also rejected after the existing 17-owner test completed only half of the healthy owners under shared-host contention. The candidate uses one bounded three-second product horizon with at most two seconds for incremental discovery, leaving a bounded remainder for admitted reads. Isolated hosted execution is the authoritative final check; the shared workstation measurements are not deployment performance evidence.

## Required hosted execution

The final metadata head must run `.github/workflows/memory-federation-v2-final-verify.yml` through `workflow_dispatch` or PR execution. Both jobs must pass:

### Exact head

- exact checkout identity;
- memory.federation map migration with zero diff;
- focused formatting;
- canonical federation contract tests;
- memory runtime and federation recovery/discovery tests;
- Memory extension attachment/final-use tests;
- Core physical HTTP final-use regression;
- Agentd and App Server composition check;
- strict `-D warnings` lint for the canonical/product crates with dependency lints isolated;
- clean patch state.

### Deterministic merge

- resolve `origin/main` at execution time;
- construct and attest the deterministic synthetic merge;
- execute the same map, format, test, composition, physical-send and strict-lint suite on that tree.

A queued job, source presence, a pass on an older SHA or a local-only result is not a hosted acceptance receipt. Run IDs and final conclusions are added only after both jobs complete on the final metadata head.

## Remaining repository-controlled gap

Product turn cancellation is safe through host future-drop propagation and cannot attach evidence after cancellation wins, but the product caller does not yet emit a canonical cancellation receipt identifying which federation phase was interrupted. This remains an observability gap; it does not authorize retry or stale attachment.

## External gates

This verification does not satisfy or waive:

- independent semantic and security acceptance;
- registered cross-host schemas and version negotiation;
- authenticated peer identity and credential/grant binding;
- coherent remote owner cut/frontier evidence;
- two-real-host disconnect, delay, cancellation, revocation and recovery tests;
- target-host p95/p99, peak memory, overload and backpressure qualification;
- operator acceptance, canary, promotion or release.

Those gates stay explicit. No production activation, automatic merge or release is asserted by this receipt.
