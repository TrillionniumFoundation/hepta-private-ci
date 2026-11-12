//! Before/after Evaluator reads surround the same original Trainer lane work.
//! A second lane visit only observes the original Model and T journals; there
//! is no remote callback while either Trainer owner mutex is held.
use super::super::super::model_command::wire;
use super::*;
use crate::CellQ24ModelProposalErrorV1;
use crate::CellQ24ModelProposalReceiptV1;
use crate::OriginalCellQ24TrainingStageErrorV1;
use codex_hepta_intelligence_eval::ProductEvaluationExecutionStoreErrorV1;
use std::sync::atomic::Ordering;

#[derive(Clone, Debug, Eq, PartialEq)]
pub(super) enum Observed {
    Missing,
    Pending,
    Completed(CellQ24ModelProposalReceiptV1),
}
fn observe(result: Result<CellQ24ModelProposalReceiptV1, Error>) -> Result<Observed, Error> {
    match result {
        Ok(receipt) => Ok(Observed::Completed(receipt)),
        Err(Error::Stage(OriginalCellQ24TrainingStageErrorV1::ModelProposal(
            CellQ24ModelProposalErrorV1::Pending,
        ))) => Ok(Observed::Pending),
        Err(Error::Stage(OriginalCellQ24TrainingStageErrorV1::ModelProposal(
            CellQ24ModelProposalErrorV1::Store(ProductEvaluationExecutionStoreErrorV1::Missing),
        ))) => Ok(Observed::Missing),
        Err(error) => Err(error),
    }
}
impl OriginalCellQ24ModelCommandHostV1 {
    pub(super) fn original_response(
        &self,
        request: &wire::Request,
    ) -> Result<wire::Outcome, Error> {
        let mut state = self.state.try_lock().map_err(|_| Error::Busy)?;
        if state.fenced {
            return Err(Error::CommitUncertain);
        }
        if request.action == wire::Action::Execute && state.execution_requested {
            return Ok(wire::Outcome::ReadbackRequired);
        }
        if request.action == wire::Action::Readback && state.model.is_none() {
            // Awaiting custody is not an actual read of an original Model file.
            return Ok(wire::Outcome::ReadbackRequired);
        }
        let result = (|| {
            let (original, context, before) = self.original_inputs(&mut state)?;
            request.require_context(&context, request.nonce)?;
            if matches!(context.require_qualified(), Err(Error::Ineligible)) {
                return Ok(wire::Outcome::Ineligible);
            }
            context.require_qualified()?;
            let current = context.authenticate(now()?)?;
            before.require_original_model_input(
                &context.training_cut,
                context.training.attestation(),
                current,
            )?;
            let observed = match request.action {
                wire::Action::Execute => {
                    if current
                        >= context
                            .material
                            .initial
                            .request
                            .envelope
                            .expiry_unix_seconds
                    {
                        return Err(Error::DeadlineExceeded);
                    }
                    // All original context/readback checks precede this shared
                    // bit. Once a writer may be initialized, no error resets it.
                    state.execution_requested = true;
                    if self.bootstrap.cancellation.load(Ordering::Acquire) {
                        return Err(Error::Cancelled);
                    }
                    let (file, witness) = state.custody.take().ok_or(Error::ReadbackRequired)?;
                    state.model = Some(
                        OriginalCellQ24TrainingCommandOwnerV1::create_original_model(
                            original.as_ref(),
                            file,
                            witness,
                            &context,
                            &before,
                        )?,
                    );
                    let model = state.model.as_mut().ok_or(Error::CommitUncertain)?;
                    observe(
                        OriginalCellQ24TrainingCommandOwnerV1::commit_original_model(
                            original.as_ref(),
                            model,
                            &context,
                            &before,
                        ),
                    )?
                }
                wire::Action::Readback => {
                    let model = state.model.as_mut().ok_or(Error::ReadbackRequired)?;
                    observe(OriginalCellQ24TrainingCommandOwnerV1::read_original_model(
                        original.as_ref(),
                        model,
                        &context,
                        &before,
                    ))?
                }
            };
            let (after, material, fresh) =
                self.current_after(&mut state, &original, &context, &before)?;
            if observed != after {
                return Err(Error::CommitUncertain);
            }
            match after {
                Observed::Completed(receipt) => {
                    let outcome = wire::encode_completed(&context, &receipt, material, fresh)?;
                    let wire::Outcome::Completed { record } = &outcome else {
                        return Err(Error::CommitUncertain);
                    };
                    let current = wire::decode_completed(&context, record, fresh)?;
                    if state.retained.as_ref().is_some_and(|old| old != &current) {
                        return Err(Error::CommitUncertain);
                    }
                    state.retained = Some(current);
                    Ok(outcome)
                }
                Observed::Missing | Observed::Pending if state.retained.is_some() => {
                    Err(Error::CommitUncertain)
                }
                Observed::Missing => Ok(wire::Outcome::Missing),
                Observed::Pending => Ok(wire::Outcome::Pending),
            }
        })();
        if result.is_err() && state.execution_requested {
            state.fenced = true;
        }
        result
    }

    pub(super) fn current_after(
        &self,
        state: &mut State,
        original: &Trainer,
        context: &Context,
        before: &OriginalCellEvaluationModelMaterialV1,
    ) -> Result<(Observed, codex_hepta_types::Digest32, u64), Error> {
        let started = now()?;
        let after = self.runtime.block_on(
            state
                .material
                .as_ref()
                .ok_or(Error::Unavailable)?
                .read_current(),
        )?;
        if after.binding() != before.binding()
            || after.original_evaluation() != before.original_evaluation()
            || after.original_evaluation() != &context.evaluation
        {
            return Err(Error::Binding(
                "unchanged original current Evaluation material",
            ));
        }
        // The Evaluator callback has returned. Re-enter only the original lane
        // to read the exact T and Model; never call recover or commit here.
        let model = state.model.as_mut().ok_or(Error::ReadbackRequired)?;
        let observed = observe(OriginalCellQ24TrainingCommandOwnerV1::read_original_model(
            original, model, context, &after,
        ))?;
        let fresh = context.authenticate(started)?;
        require_clock(started, fresh)?;
        before.authenticate_current(fresh)?;
        after.authenticate_current(fresh)?;
        let input = after.require_original_model_input(
            &context.training_cut,
            context.training.attestation(),
            fresh,
        )?;
        Ok((observed, input.material_digest(), fresh))
    }
}
