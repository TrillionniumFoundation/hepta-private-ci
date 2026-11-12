# Static review of the bounded Q24 owner operation

Source reviewed: `57861bc757a217686d5974d46529aa5ac91ee812` (including `11fa8d83`). This is source review only; no Rust compile, native test, measured request-count result or whole-system acceptance is supplied by this review.

## Checks confirmed

- `cell_q24_learning_b_operation.rs` retains the actual original B readback only in `OriginalQ24StageOperationV1`. It is not retained on the aggregate. `finish_original_b_read` consumes that value and compares a fresh actual Root read. The stage `run`, publication receipt-read operation and Generation authentication save the operation result before invoking the final read, so an ordinary returned error does not skip that final attempt.
- `from_original_receipt_read` verifies the same `OriginalPreparedReadV1`, requires the real Root B owner and excludes the local B owner. Its `context: None` path has no checkpoint context. `run` requires `original_stage_context()` before dispatch, and restore/commit paths require that context. Current actual receipt-read callers use read operations; this review does not claim that the private model action enum itself is a distinct read-only Rust type.
- `in_original_prepared_lane` keeps the original permit, owner mutex, actual Prepared read and factory checks before/after work. It checks cancellation before entering, after locking, before work and after postchecks. `FenceAggregateOnDrop` is disarmed only for the complete outer `Ok`. Join failure, dropping the future and outer postcheck errors keep the aggregate cancelled.
- Generation installation validates both original roles and the actual selection, then validates the original receipt chain in that same lane. Although the owner pair is assigned before the receipt pass, a later error leaves the aggregate permanently cancelled. The successor notification occurs only after the complete operation returns successfully.
- Successor proof uses the actual same aggregate (`Arc::ptr_eq`/context ownership), actual Root CURRENT and original selection. Historical successor checks borrow the original Prepared read. Publication retains exact new-work, model, signed selection, final-use binding, Running admission and installation-slot checks. `connect_current_until` continues to use the original startup end.
- The server still rejects B sequence values above 32, and the work does not enlarge a frame or session deadline. The total number of requests for the full ordinary Adopt/NoUpdate path remains to be measured by the real fixture.

## Existing error-result nuance

`cell_q24_publication_material.rs::with_original_root_publication` stores `work()` as a nested result, performs its B/Prepared postchecks, and returns `Ok(value)` from the lane. A publication work error can therefore be returned after the outer lane was considered successful and its aggregate cancellation guard disarmed. The legacy publication branch uses the same pattern. This is not a newly introduced bypass, and the consumed publication driver and underlying owner refusal rules still apply, but the implementation must not be described as permanently cancelling the aggregate for every publication work error. No source change was made by this review.

## Verification limits

The local native attempt reported by the parent exited 255 while checking dependencies; no diagnostic establishes OOM or timeout, and it did not establish typecheck success. The independent Initial source checks on `98a54391` are a different source tree and are not evidence for this runtime refactor.
