# Original Training completion observer — isolated test-only increment

Status: **HOLD; not formatted, compiled or executed**. The two additive postimages layer on the frozen eight-file Fresh T→B component (`8d5b1eeea4e63ae04bb77c91abc996a34cdeccfa`) and exact cc57 command test support. That component and the active source are unchanged. Every old byte remains a prefix of its corresponding after image. `prepare_increment.py` only constructs isolated text artifacts and hashes; it does not execute a Rust test or control main.

## Interface and custody

`original_ports::completed_candidate_training(&Arc<OriginalCellQ24TrainingBootstrapOwnerV1<...>>)` performs one synchronous observation and returns `Result<Option<OriginalCellQ24TrainingCommandReceiptV1>, OriginalCellQ24TrainingBootstrapErrorV1>`.

The function borrows the same actual Bootstrap. `Awaiting`, `Starting`, or a currently contended state mutex yields `None`. A poisoned state mutex remains an error; `Fenced` remains `Uncertain`. `Ready` only supplies an Arc to the already held original command owner and is never treated as completion. The Bootstrap state lock is released before any original Stage I/O.

The only new associated method is in `serving::command_test_support`, already mounted under `#[cfg(test)]`. A sibling cannot access the command owner's private Stage/context, so the observation is implemented in that existing descendant module. No production getter, visibility extension, writer/key extraction or reconstructed owner is added.

The method calls the original `SourceBoundCellQ24TrainingStageV1::read_candidate_material`. That existing model lane reads the actual native/Generator completion, requires original source capture and Candidate outcome, and rechecks original live source and both retained receipt and signature before returning. It then passes the exact original bytes to `wire::authenticate_receipt` with the original command context and current time. Only this successful path returns the existing opaque typed receipt.

## None, errors and limits

The exact Stage Busy/Pending/Missing variants already classified by the original command service yield `None`. Other errors are returned unchanged through the existing error conversions. In particular NoCandidate, source withdrawal, signature failures, poison and uncertain completion cannot authorize B or become NoUpdate. This helper is for polling *before the first completed Candidate observation*. A retained `Some` does not authorize another Execute, nor does it certify later source freshness. The actual pre-held Candidate and Training clients must still bind and read the same original cut and reject any subsequent divergence.

The helper creates no channel, consumes none of the three pre-held fixture clients, and does not call Execute, create/recover an owner or sign anything. It has no retry loop and no new timeout. The original Candidate read performs real synchronous source/owner I/O: the caller must use the fixture's existing bounded blocking lane and retain its original deadline and teardown. It must not run directly on an async executor worker or treat a dropped async wait as cancellation of already running I/O.

This test-only local observation is not a public transport path and does not solve the Bootstrap's four-public-connection capacity constraint. The combined Root/ten-owner fixture, all actual negative sequences and the public capacity/identity contract still require separate implementation and validation.

## Source anchors

The frozen references under `reference/` include command context/error/wire and model-lane definitions. The reviewed original Bootstrap and command service are in the fixed cc57 references of the provider v2 proposal. Original service classification is `cell_q24_training_command_service.rs::original_state`; original material read is `cell_q24_training_model_lane.rs::read_candidate_material` through the same SourceBound facade; actual before/after completion equality is enforced by `in_model_lane`. The normal staged fixture may instead simply await the existing Execute future and then use its original response.

Static type/visibility reasoning does not establish compilation. The combined crate must still verify generic bounds, private-module accessibility, all source guards and formatter output. No existing assertion or test body is changed by this increment.
