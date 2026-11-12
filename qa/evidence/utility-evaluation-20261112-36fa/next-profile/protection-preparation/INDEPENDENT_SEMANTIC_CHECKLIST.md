# Ordinary evaluated NoUpdate: semantic fence checklist

Status: read-only source review of PREPARATION/HOLD commit `86dd56a930277e0d1aef3e475e35c2b5d60b43b7`, tree `383ab85c39ef9d848252ef5c25922d13d9fae6c6`. This note neither changes the preparation nor claims compilation, mutation execution, native maintenance, qualification, or a real A/T/E/S/C run. The sole non-Rust writer must freeze final literal markers from the actual formatted postimages, not this pre-format spelling.

All source paths below have prefix `codex-rs/hepta-agentd/src/`.

## 1. Two independent Selector Clone implementations

File `circuit_evaluated_selection_command.rs` contains two methods named `clone`. Each fence must bind to its actual enclosing impl, rather than accepting the first matching method or a body elsewhere in the file.

| Actual impl | Fields that must be retained |
| --- | --- |
| `impl Clone for OriginalCircuitSelectionCommandContextV1` | Same training snapshot, scope, verifier, full training evidence, and optional evaluated context cloned through `OriginalCircuitEvaluatedRetentionContextV1::clone_for_original_receipt`. |
| `impl Clone for OriginalCircuitSelectionCommandReceiptV1` | Same snapshot, receipt, full attestation, full training evidence, and optional evaluated context through that same exact helper. |

The helper in `circuit_evaluated_retention_context.rs` copies scope, verifier, original T receipt, original E receipt, and **the existing origin**. It does not create a channel or promote Readback to Fresh. The independent `into_original_receipt_readback` operation explicitly attenuates origin. `recover_from_original_evaluated_stream` applies this attenuation before context construction, authenticates any expected completed snapshot/signature, and binds the original stream with `execution_requested = true`.

Keep `authenticate_evaluated` checks for snapshot equality, scope equality, all three trust/scope/objective digests, full T evidence equality, and verification of both original predecessor signatures. Receipt `PartialEq` additionally retains the evaluated context binding comparison; do not drop this because the other receipt fields match. The binding includes both original signing bytes and signatures, not just receipt/head digests.

Minimum meaningful source mutations: independently remove or replace each impl's evaluated-field clone; promote origin inside the helper; bypass cold attenuation; remove one full-evidence equality or the optional evaluated binding from receipt equality. A test for one impl is not evidence for the other. When locating an impl/function in QA, use the actual masked executable span and reject a comment, string, nested function, or unrelated duplicate as a substitute.

## 2. Readiness retains two distinct typed purposes

### Entry and wire checks

`ReadProfile::legacy` rejects Evaluated. Preserve these original gates independently:

- `readiness::Request::new` and `require_context`: original legacy purpose and legacy NextUse mode, followed by the original request/context verification.
- `OriginalCircuitLearningReadOwnerV1::serve_completion_readiness`: timing validation, then `self.context.legacy()?` and NextUse. It cannot accept evaluated by replacing that expression with the shared mode accessor.
- New `serve_evaluated_completion_readiness`: explicitly Evaluated and NextUse before entering the shared channel loop.
- Retained Version read entry points are independently Selection-only: old `serve_original_retained_channel` calls `legacy()?`; new `serve_original_evaluated_retained_channel` explicitly requires Evaluated. They use the same pre-held channel, without a reconnect.

`Request::from_profile` and `require_profile` dispatch on the actual private enum. TrainingNoUpdate must call the old constructors/validator. Evaluated must check its separate readiness purpose and NextUse mode, then invoke `ReadProfile::require_request`. That evaluated request validation compares schema, operation, request ID, binding, prefix head, operation ID, and mode. Do not route either profile by receipt count alone, accept the other's purpose, or replace these equalities with a shared digest-only check.

`bind_original_evaluated_stage_channel` compares Material scope and trust/scope/objective digests before building the five-cut context from the opaque S receipt. Shared `bind_profile` authenticates the binding, requires NextUse, reconstructs and compares the exact initial and two-cut D snapshot, checks peer lifetime, revalidates the actual Material/D context, and rejects backward clocks or a changed binding before retaining the channel. No receipt can manufacture that channel.

### Read and reply sequencing

`OriginalCircuitCompletionReadinessClientV1::read_current` takes its channel **before** binding/request/transport work. After the authenticated reply and actual read decode, it checks peer lifetime and binding/clock again. It then checks the retained completed result. A changed Ready or Ready-to-NotReady transition returns before channel restoration. Only after all checks may it restore the same channel. Authenticated NotReady and an identical authenticated Ready may both retain the connection; the implementation is more precise than the brief “only NotReady” comment.

On the service side, `readiness_response` validates the typed request and binding before actual owner I/O and checks the binding/time again afterward. `read_original_readiness` reads actual task input, actual Selection, and actual Source publication. Only original `ReconciliationRequired` maps to NotReady, and it still requires a successful original C private snapshot. Other errors remain errors. A publication result is checked against `read_original`, then actual task input and Selection are re-read. NotReady is unresolved; it never means a definitive “C did not execute.”

Keep request IDs 1..=128, existing transport/timing bounds, bounded replies, unknown-field refusal, and no execute/sign/reconcile action in readiness.

Minimum source mutations: admit evaluated through the legacy gate; swap the two purpose literals while retaining old strings in comments; remove a request equality; alter NextUse to Selection; bypass D/Material equality; restore the channel before the retained-result check; accept Ready-to-NotReady; turn arbitrary Source errors into NotReady; delete either post-I/O input/Selection check. These are proposed mutation targets, not new executed cases.

## 3. Version custody, physical current reads, and publication admission

### Binding and observation

`OriginalVersionCut::from_original_evaluated` receives actual opaque T/E receipts and selects Fresh vs recovered construction from the original origin. `coordinator` checks the same evaluated snapshot/scope/verifier/T evidence. `authenticate` requires the original initial/D prefix and uses a distinct evaluated command domain with all full D/T/E signatures. `require_fresh` calls the original Material initial and D-context validators, checks clock order, and reauthenticates the binding for the requested access. This is not a pure cached receipt check; preserve the underlying original Material validation, including any actual file reads it performs.

`bind_original_predecessor`: lifetime -> actual D read/verify -> take the pre-held T connection -> bind/read T -> for the evaluated purpose, take the pre-held E connection -> bind E against actual D/T -> read E -> construct cut -> exact cold expected snapshot/signature comparison -> freshness -> retain the same clients/cut. It must not install a reader here.

`require_cut_current` reads and verifies actual D and compares it to the held original, then reads actual T or actual T/E according to the typed cut. `read_original` preserves:
1. lifetime and current cut;
2. Artifact before and first phase observation;
3. current cut again and last phase observation;
4. Artifact after/equality and first/last equality;
5. lifetime and full cut freshness.

The phase observation calls the held installed/recovered original owner. A physically published Control record in a merely Prepared phase remains CommitUncertain; it does not replay the C factory.

### Fresh and recovered read admission are different

Fresh publication does not set `final_use_outcome = Published` until **after** actual publication/factory install, reader construction, full `read_original`, and final NewWork freshness. Installed or reader Some alone is insufficient.

Recovered `read_original_recovery` takes any existing reader out of state, performs one full original read, constructs/reuses a local reader, performs another full original read, compares both and requires a real publication, then checks full freshness and host lifetime before reinstalling and notifying. These steps run under the original command state lock. No reader may be placed in state before those checks.

A later actual predecessor-bind failure in `command_response` clears the recovered reader under the same lock and returns Uncertain. This does not claim revocation of already handed-out read-only Arcs. Invalid external wire requests fail before that branch and must not be turned into a global revocation capability.

`serve_original_selection_channel` must require Published, an existing admitted reader, and `cut.require_fresh(now, Readback)` under the state lock **before** cloning that reader. It preserves the original peer/host lifetime; readiness does not renew a timeout. It then dispatches by the explicit Version purpose to the corresponding Selection-only service.

### One-shot effects

- `prepare_original`: Fresh plus atomic preparation admission -> NewWork/current/artifact checks -> take Awaiting phase -> completed A check -> take original T and, for evaluated, E -> consume the exact preparation inputs -> preserve original Prepared custody -> full original read/freshness. Failure never reconstructs the consumed phase.
- `publish_original_final_use`: Fresh, Requested outcome, already-consumed issuer slot, and exact FinalUse grant binding before the one-shot publication flag. Inside the blocking operation: cancellation/lifetime/state -> actual predecessors/current -> exact grant again -> NewWork freshness/cancellation -> take Prepared phase -> completed A/cancellation -> consuming publication -> original C install -> restore the same retained T/E -> read/validate -> only then Published.
- `RetainedVersionPreparedV1::publish(self, signed)` uses the actual concrete UFCS for each variant. Evaluated publication returns and retains both original clients. It does not clone preparation or obtain replacement custody.
- `run_original_c`: Fresh and one-shot runtime admission -> actual Installed state/read -> Published -> NewWork freshness -> take original C config -> original runtime. Recovery cannot start C; an already consumed config is not recreated.
- The cancellation fence signals cancellation on Drop; cancellation checks remain before consuming/effect edges. No claim is made that an already executed external effect is rolled back.

Minimum mutations: install the cold reader before the second read; remove cold bind-failure clearing; weaken Published to Installed/Some; clone before full freshness; remove an Artifact/current second read; replace client take with a retryable copy; clear a consumed flag on an error; move grant equality after phase consumption; skip cancellation before effect; permit Recovered to start C. Preserve the genuine Unknown/Uncertain results; do not map them to complete NoUpdate or Fraud.

## 4. Root gate and continuation boundaries

`ResidentOriginalStageOwnersV3::require_stage` delegates a candidate Selection/NextUse that is not legacy TrainingNoUpdate to `OriginalCellQ24CandidateStageOwnersV1::require_evaluated_retained_stage`. This is protocol selection only. `evaluated_prefix` still validates the full coordinator, exact evaluated NoUpdate, four-to-six cut shape, no legacy TNU receipt, a genuinely changed candidate, selected parent bundle, and exact next stage. Adopt remains outside this path.

`execute_evaluated_retained_stage` additionally requires Fresh, the actual held Root gate, and current gate validation before the effect lane. It sets the lane's failed latch before awaited work and clears it only after all final checks. It refreshes actual T/E pins, authenticates NewWork, performs stage-specific Version/S/C preparation, checks the Root gate and full material again before S/C effects, and checks the Root gate, actual publication, original S where applicable, current T/E, full signed returned receipt, material clock, and live deadline after the effect. A later failed gate produces CommitUncertain, not a fabricated success.

`EvaluatedContinuation::refresh` creates NewWork context only for the first Fresh handoff. Subsequent equality checks use recovered/read-only construction and compare all original D/T/E plus context binding. Initial channels are taken once. `bind_selector` and `bind_next_use` consume only those previously admitted channels and pass the original origin.

`prepare_retained_version` dispatches Prepare once, then resolves Busy/ReadbackRequired/CommitUncertain only by bounded original readback. `await_completed_c` polls read-only readiness under the held Root gate, then re-reads original S and T/E; it does not execute C or manufacture completion. Preserve the original 128-frame loops and existing deadlines, not a new retry window.

Minimum mutations: accept Adopt/legacy cut as evaluated; synthesize a gate; remove pre/post gate calls; clear the failed latch before final checks; replace readback with another Prepare; skip actual publication or actual S equality; reuse initial channels; promote later refresh/recovery to Fresh. These are source-level acceptance obligations, not a claim that all paths have run.

## Exact source pins

| File | Blob |
| --- | --- |
| `circuit_evaluated_selection_command.rs` | `c64626eb19dae7b01dd6c77e8d931abe36272e41` |
| `circuit_evaluated_retention_context.rs` | `023d44d19df5ae7eb6b566ba03d6b323d9e6eaef` |
| `circuit_learning_read_profile.rs` | `bec9a048b3a583811ea824dc8f02bafbed3b35da` |
| `circuit_learning_completion_readiness.rs` | `7bc9d61e1d069b8801d86a4bea0fcbcc2e478beb` |
| `circuit_learning_completion_readiness_service.rs` | `aebe684c36cab0a89c13e4f702e18e1b37a27f10` |
| `circuit_learning_read_service.rs` | `74be1cee263699d8e5ab793387290417f9444ad7` |
| `circuit_retained_version_context.rs` | `8e2157b1c5f4ac24fd601e2a7221cdb239ca324c` |
| `circuit_retained_version_state.rs` | `d5c9cac9bb551376adce36d04b167f6fa978791d` |
| `circuit_retained_version_effect.rs` | `ebc02be6cff65a205b1fa1fc171307a0e8a4c05c` |
| `circuit_retained_version_service.rs` | `34dc709c958cca632bb21189c78be2bb19c08fb7` |
| `circuit_retained_version_prepared.rs` | `b62728f79eeda3e17f4067bcaa3227c96da40e42` |
| `cell_q24_candidate_stage_retained.rs` | `6cb5e7fc0f274cbdbae9fe57140b48cca4983677` |
| `cell_q24_candidate_stage_retained_execute.rs` | `0e24b809a531f741ccecc13b8262e184aec1dfb1` |
| `authority_host_learning_resident_stages.rs` | `9128be835dbb0ca724591499ab0a7a34c9a9f3f2` |

## Evidence limits

This note supplies a bounded semantic checklist to the sole non-Rust writer. Existing assertions, original denied-caller injections, complete collector scope and exact caller equality must remain. Actual-span checks are needed where the original verifier cannot independently bind duplicate/generic methods or meaningful literals; a file-level substring retained in a comment is not an equivalent defense.

No gates were run for this note. The ten newly prepared Rust mechanism cases, the retained guard positive-primary/negative-retention runtime gap, the specific Material-freeze-versus-T/E expiry window, and the ordinary real-input requirements retain their already recorded limitations. A final source-fencing pass is still not a real deployment, independent evaluation, cost-contract settlement, or complete A/T/E/S/C acceptance.
