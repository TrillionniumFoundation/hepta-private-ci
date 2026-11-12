# Selection readback caller-registration audit

Status: source review only; no production Rust changes, no ref updates, no Cargo or desktop execution.

## Frozen inputs

- Repository: TrillionniumFoundation/hepta-private-ci
- Published failure source: e8b6fe2aa55b4fdcfe8d9c15ea830e16f0144bbd, tree b607ff5f50812c5e0f932d7dae18d4c74f1269cb
- Fixed upstream source: b29869e856d08db1bfb066116a9c443376ccc57d, tree 906546af39b07474f0b9d046a6e780b6d3342743
- Preparation v2 CALLERS: Git blob 317da5f28fbc1cf2556fa5935bb846dce8c7c2cb; 1,122,002 bytes; SHA-256 13b8b2d8d9fbe0768f0b8dd288ee8e147f5641a2affd99f7eed5b2647e107d74
- v2 contains 534 boundary rows and 390 protected rows. This report authorizes no additional caller by itself.

## Finding

All three Selection files really call the existing free function original_owner_command_channel_v1. They are not conservative receiver-analysis false positives. The missing registration is a source-contract omission at existing purpose-fixed read-only seams. No source evidence reviewed here calls for adding execution, signing, recovery, reconnection, or owner-authority capabilities.

The proposed Selection extension has six exact caller memberships in four existing boundaries. It preserves the original verifier semantics and every prior row. Two legacy readback files need protected rows and mutation QA at the same time; registering their names alone is insufficient.

| Existing boundary | Actual missing caller |
| --- | --- |
| learning_original_owner_command_channel | codex-rs/hepta-agentd/src/circuit_evaluated_selection_readback_owner.rs |
| learning_original_owner_command_channel | codex-rs/hepta-agentd/src/circuit_selection_command_readback.rs |
| learning_original_owner_command_channel | codex-rs/hepta-agentd/src/circuit_selection_command_readback_service.rs |
| learning_original_material_initial_context_check | codex-rs/hepta-agentd/src/circuit_selection_command_readback.rs |
| learning_original_material_dataset_context_check | codex-rs/hepta-agentd/src/circuit_selection_command_readback.rs |
| learning_original_circuit_selection_remote_readback | codex-rs/hepta-agentd/src/circuit_selection_command_readback_service.rs |

The final row is a separately identified source omission outside the four-boundary diagnostic. The service uses explicit UFCS readback_remote at line 79. Its existing declared caller list contains only circuit_selection_command_service.rs and circuit_selection_command_evidence.rs.

## 1. Evaluated Selector evidence readback

Source: codex-rs/hepta-agentd/src/circuit_evaluated_selection_readback_owner.rs
Git blob: c1e11662921a5b869d060dad3a9a2d53a53668fb (new between e8 and b298).

- from_original_receipt_owner (line 70) consumes OriginalCircuitSelectionReceiptOwnerV1 into a private Mutex and retains a PublishedCircuitCellOwnerV1, Arc<OriginalCellQ24TrainingCommandClientV1>, Arc<OriginalCellEvaluationCommandClientV1>, and opaque OriginalCircuitEvaluatedSelectionReceiptV1.
- Its caller is the original receipt owner's consuming into_evaluated_readback_owner factory in circuit_evaluated_selection_receipt.rs (line 335). The factory requires the Evaluated profile and equal original context binding, decision, and Selector actor. The inner factory rechecks scope, verifier trust/scope/objective, full Training evidence, and Selector actor.
- serve_readback (line 113) checks a nonzero exchange timeout <=500 ms, acquires a bounded connection permit, and opens the original process-pinned channel. It does not enlarge the existing evidence exchange budget.
- evidence_response (line 158) accepts only the established evidence wire. It checks schema, request sequence/range, initial binding, operation, actor, predecessor, receipt digest, and canonical nonzero correlation head.
- The only owner operation is explicit UFCS OriginalCircuitSelectionReceiptOwnerV1::readback_evaluated_selection. The actual owner, Cell, T client, and E client are held by this host, rather than supplied as per-request callbacks.
- The call reaches readback_source in circuit_selection_receipt_owner.rs. It reads the original journal, brackets it with current owner observations, and does not call attest_source or the original signing/creation route.
- OriginalCircuitEvaluatedRetentionContextV1::require_current (circuit_evaluated_retention_context.rs, line 259) reads actual T and E command clients and requires equality with both pinned opaque results, then authenticates again at the fresh time. It does not accept renewed signatures as equal.
- The evaluated Cell observation calls PublishedCircuitCellOwnerV1::read_learning_selection. circuit_feature_current_learning.rs calls task.require_current before and after the original selection lookup.
- Before response encoding, the host rechecks all original T/B/S predecessors, monotonic time, full snapshot/receipt/attestation equality and original binding. The owner lock is released before response construction.
- snapshot_head is correlation only. It does not select the server's original journal or supply a future observation.
- The current CALLERS protected row already pins factory, serving, request checks, original readback ordering and prohibited effect APIs. Keep it unchanged.
- The serve_readback boundary still has an empty product_callers list. This mechanism is not evidence that ordinary startup or a deployed new C consumer has been assembled.

The client Arc fields retain the supplied original connections. Exact original T/E result equality and the complete original context are revalidated on reads; this report does not invent an additional pointer-identity or deployment-custody claim.

## 2. Legacy purpose-fixed Selection connection

Source: codex-rs/hepta-agentd/src/circuit_selection_command_readback.rs
Git blob: 5a69cc5f3bbfbb58b4050cc1e51c552cacb7e75f (identical at e8 and b298).

- from_original_stream (line 42) authenticates the original material initial binding, requires peer.actor_id to equal the enrolled Selector, constructs the original process-pinned channel, checks its lifetime, then repeats initial-context and monotonic-time checks.
- bind_original_selection (line 86) consumes the existing connection. It accepts opaque D/T/S, builds the original context, requires the same initial cut, checks the original Dataset context and current time, authenticates the complete Selection, and requires exact full signatures/binding.
- OriginalCircuitSelectionCommandContextV1::authenticate (circuit_selection_command.rs, line 138) still requires exactly three receipts, TrainingNoUpdateV2, and next stage Selection. This legacy connection does not reinterpret an evaluated four-cut context.
- The return is the existing evidence-only client with private OriginalCommandEvidenceV1::Selection. There is no execution-client conversion, selectable role tag, or recovered/fresh promotion.
- OriginalSelectionReadbackV1::readback (line 168) takes its peer before awaiting. It pins the exact expected original Selection receipt and bounded request sequence.
- request (line 235) always sends Action::Readback with the distinct runtime.learning.original-circuit-selection.readback.v1 operation.
- After I/O it checks response correlation, peer lifetime, original Dataset context at a fresh time, monotonicity, exact context binding, completed original signatures, and equality with the retained Selection. Only complete success restores the peer.
- Missing/Pending are CommitUncertain; errors/cancellation do not restore a reusable peer or create work.
- The outer learning_iteration_command_evidence.rs path also takes its command slot before awaiting and restores it only after role/payload/actor/time authentication.
- Dataset-context checks authenticate the original opaque material at the current time; they are not a new Dataset network read. Actual Source/Cell currentness comes from the server's original T/Cell read chain.

There is no protected_file row for this file in the frozen v2 CALLERS. The preparation must add precise ordered checks and prohibit effect/reconnection paths.

## 3. Legacy Selection read-only service

Source: codex-rs/hepta-agentd/src/circuit_selection_command_readback_service.rs
Git blob: 6e849c4d06337f809bab785a8b934aca8f85e019 (identical at e8 and b298).

- The receiver is the actual OriginalCircuitSelectionCommandOwnerV1<W>. Its private factory consumes the original receipt owner and retains the exact live task client and Trainer evidence client.
- The command owner's private creation/recovery origin controls execution admission. The caller cannot pass a boolean to promote a recovered original owner.
- serve_original_selection_readback (line 25) reserves the host's bounded permit and opens the original process-pinned channel; the connection's existing absolute lifetime is not renewed per frame.
- original_selection_readback_response (line 68) first calls readonly::require_request. That function requires the distinct readback operation, Action::Readback, schema, bounded request sequence and exact original context.
- The private response handler calls only explicit UFCS OriginalCircuitSelectionReceiptOwnerV1::readback_remote with the same context.training, live and trainer. It does not enter command_response or original_response(true).
- The original remote owner read chain validates the actual task context, reads current Cell and Trainer, rereads original journal bytes and authenticates original signatures at the final time. Full completed receipt and signature windows remain fixed.
- Owner locks are dropped before encoding/writing. wire::encode_completed authenticates the exact one-receipt extension, retained baseline, Selector actor/time, Generator/Selector separation; context.authenticate runs again before response.
- Missing/Pending retain the original states; other current/signature failures become Uncertain, never a new Selection or TrainingNoUpdate inference.

There is no protected_file row for this file in frozen v2. Add source fencing for the original read-only route and its sequencing, without changing the production Rust.

## Original framing and source authority

learning_owner_command_channel.rs::original_owner_command_channel_v1 rejects same UID/effective UID, same/invalid PID, absent process start ticks, zero or >30-second timeout and zero or >300-second lifetime. It checks original boot/process identity before and after HostAuthorityPeerChannel::from_stream and retains the original pidfd. These are transport identity checks, not independent owner enrollment or task authorization by themselves; the typed contexts and original opaque/signature/current checks above supply the task binding.

The Selection review does not assert ordinary A/B/C qualification, complete deployment economics, sustained model availability, Root cold-recovery success, or scientific independence beyond the actual code checks.

## Diagnostic evidence and limits

The preceding four-boundary diagnostic was independently executed by ordinary_path against all 6,590 original Rust inputs plus seven additions and the frozen 25-file overlay. Its final report is Git blob 5a4653eba97c47ef8eef931db2b5bb5850a9ba84, raw log 248da39cdda1043874adcbb30a00bbefd0d5e358. It reported one boundary pass, three boundary failures and five protected-row passes, exit 1 without timeout, with original source inputs unchanged. It is a scoped diagnostic, not the original full gate.

The framer failure included the three Selection callers and three artifact callers. The initial/dataset failures each identified circuit_selection_command_readback.rs. Artifact callers are a separate review owned by ordinary_path and are not admitted by this report.

The extra remote-readback membership above is established by the exact source call, not by claiming it was in that four-boundary execution. Full 534-boundary/390-row diagnostic and the later original frozen-source full gates have separate execution identities and must retain any failures.

The forthcoming v3 is reviewable preparation only. It must preserve all v2 rows, unknown-caller injection tests, original verifier functions, and existing QA function bodies. Any actual scoped mutation checks must be recorded separately and must not be described as signed runtime behavior or a full closed-world source pass.
