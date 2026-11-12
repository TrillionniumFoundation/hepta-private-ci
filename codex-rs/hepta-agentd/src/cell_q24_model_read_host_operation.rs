//! Native half of one bounded Model read on its original admitted channel.
//! The same State guard owns the whole continuation. E network exchanges stay
//! outside the original Trainer lane; a dropped or malformed transfer fences it.
use super::*;
use super::super::super::model_command::wire;
use crate::CellQ24ModelProposalReceiptV1;
use base64::Engine;
use base64::engine::general_purpose::STANDARD_NO_PAD;
use codex_hepta_types::Digest32;
use std::sync::MutexGuard;

pub(super) struct OriginalModelReadHostOperation<'a> {
    host: &'a OriginalCellQ24ModelCommandHostV1,
    state: MutexGuard<'a, State>,
    original: Arc<Trainer>,
    context: Context,
    evaluation: Option<OriginalCellEvaluationModelReadV1<'static>>,
    observed: CellQ24ModelProposalReceiptV1,
    model: OriginalCellQ24ModelCommandReceiptV1,
    record: String,
    body: Vec<u8>,
    digest: Digest32,
    transfer: u64,
    next_page: u32,
    started: u64,
    completed: bool,
}

impl OriginalCellQ24ModelCommandHostV1 {
    pub(super) fn begin_original_read(
        &self,
        request: &wire::Request,
    ) -> Result<OriginalModelReadHostOperation<'_>, Error> {
        let execute = match request.action {
            wire::Action::BeginOriginalRead => false,
            wire::Action::BeginOriginalExecute => true,
            _ => return Err(Error::Binding("original Model Begin")),
        };
        let mut state = self.state.try_lock().map_err(|_| Error::Busy)?;
        if state.fenced { return Err(Error::CommitUncertain); }
        if execute && (state.execution_requested || state.model.is_some())
            || !execute && state.model.is_none()
        {
            return Err(Error::ReadbackRequired);
        }
        // This is the Model host's state lock, never the native Training lane.
        // Every native call below returns and drops its permit before E or
        // the next peer request can run.
        state.fenced = true;
        let inputs = self.original_inputs(&mut state)?;
        let evaluation = self.runtime.block_on(
            OriginalCellEvaluationModelMaterialClientV1::begin_owned_model_read(
                Arc::clone(&inputs.material),
            ),
        )?;
        let before = OriginalCellEvaluationModelReadV1::material(&evaluation);
        let context = self.original_context(&mut state, &inputs, before)?;
        context.require_qualified()?;
        request.require_context(&context, request.nonce)?;
        let body = before.original_model_transfer_body().to_vec();
        let pages = body.len().div_ceil(wire::MATERIAL_PAGE_BYTES);
        if body.is_empty() || body.len() > wire::MATERIAL_MAX_BYTES
            || request.nonce.checked_add(pages as u64 + 1).is_none_or(|last| last > 128)
        {
            return Err(Error::Binding("bounded original Model full material transfer"));
        }
        let digest = Digest32::of_bytes(&body);
        let observed = if execute {
            // Use the same existing Execute brand and original custody. A
            // failed or cancelled attempt never receives another Execute.
            state.execution_requested = true;
            let fresh = context.authenticate(inputs.started)?;
            if fresh >= context.material.initial.request.envelope.expiry_unix_seconds {
                return Err(Error::DeadlineExceeded);
            }
            if self.bootstrap.cancellation.load(Ordering::Acquire) {
                return Err(Error::Cancelled);
            }
            before.authenticate_current(fresh)?;
            before.require_original_model_input(
                &context.training_cut, context.training.attestation(), fresh,
            )?;
            let (file, witness) = state.custody.take().ok_or(Error::ReadbackRequired)?;
            state.model = Some(
                OriginalCellQ24TrainingCommandOwnerV1::create_original_model(
                    inputs.original.as_ref(), file, witness, &context, before,
                )?,
            );
            // create_original_model has released its original Training lane.
            let fresh = context.authenticate(fresh)?;
            if fresh >= context.material.initial.request.envelope.expiry_unix_seconds {
                return Err(Error::DeadlineExceeded);
            }
            if self.bootstrap.cancellation.load(Ordering::Acquire) {
                return Err(Error::Cancelled);
            }
            before.authenticate_current(fresh)?;
            effect::observe(
                OriginalCellQ24TrainingCommandOwnerV1::commit_original_model(
                    inputs.original.as_ref(),
                    state.model.as_mut().ok_or(Error::ReadbackRequired)?,
                    &context, before,
                ),
            )?
        } else {
            effect::observe(
                OriginalCellQ24TrainingCommandOwnerV1::read_original_model(
                    inputs.original.as_ref(),
                    state.model.as_mut().ok_or(Error::ReadbackRequired)?,
                    &context, before,
                ),
            )?
        };
        let effect::Observed::Completed(observed) = observed else {
            return Err(match observed {
                effect::Observed::Missing => Error::Missing,
                _ => Error::Pending,
            });
        };
        let fresh = context.authenticate(
            evaluation.require_original_operation_current(inputs.started)?,
        )?;
        before.authenticate_current(fresh)?;
        let input = before.require_original_model_input(
            &context.training_cut, context.training.attestation(), fresh,
        )?;
        let wire::Outcome::Completed { record } = wire::encode_completed(
            &context, &observed, input.material_digest(), fresh,
        )? else { return Err(Error::CommitUncertain); };
        let model = wire::decode_completed(&context, &record, fresh)?;
        if state.retained.as_ref().is_some_and(|previous| previous != &model) {
            return Err(Error::CommitUncertain);
        }
        Ok(OriginalModelReadHostOperation {
            host: self, state, original: inputs.original, context,
            evaluation: Some(evaluation), observed, model, record, body, digest,
            transfer: request.nonce, next_page: 0, started: inputs.started,
            completed: false,
        })
    }
}

impl OriginalModelReadHostOperation<'_> {
    fn require_current(&self) -> Result<u64, Error> {
        let evaluation = self.evaluation.as_ref().ok_or(Error::CommitUncertain)?;
        let current = evaluation.require_original_operation_current(self.started)?;
        let fresh = self.context.authenticate(current)?;
        evaluation.material().authenticate_current(fresh)?;
        Ok(fresh)
    }

    pub(super) fn started(&self) -> Result<wire::Outcome, Error> {
        self.require_current()?;
        Ok(wire::Outcome::OriginalReadStarted {
            transfer: self.transfer,
            record: self.record.clone(),
            total: self.body.len(),
            digest: self.digest.to_string(),
        })
    }

    pub(super) fn page(&mut self, request: &wire::Request) -> Result<wire::Outcome, Error> {
        self.require_current()?;
        request.require_context(&self.context, request.nonce)?;
        let wire::Action::ReadOriginalPage { transfer, index } = request.action else {
            return Err(Error::Binding("original Model material Page"));
        };
        let pages = self.body.len().div_ceil(wire::MATERIAL_PAGE_BYTES);
        if transfer != self.transfer || index != self.next_page || index as usize >= pages
            || request.nonce != self.transfer + 1 + u64::from(index)
        {
            return Err(Error::Binding("same original Model transfer and ordered Page"));
        }
        let offset = index as usize * wire::MATERIAL_PAGE_BYTES;
        let end = (offset + wire::MATERIAL_PAGE_BYTES).min(self.body.len());
        let bytes = STANDARD_NO_PAD.encode(&self.body[offset..end]);
        self.next_page += 1;
        self.require_current()?;
        Ok(wire::Outcome::OriginalReadPage {
            transfer, index, offset, total: self.body.len(),
            digest: self.digest.to_string(), bytes,
        })
    }

    pub(super) fn finish(mut self, request: &wire::Request) -> Result<wire::Outcome, Error> {
        self.require_current()?;
        request.require_context(&self.context, request.nonce)?;
        let wire::Action::FinishOriginalRead { transfer } = request.action else {
            return Err(Error::Binding("original Model Finish"));
        };
        let pages = self.body.len().div_ceil(wire::MATERIAL_PAGE_BYTES);
        if transfer != self.transfer || self.next_page as usize != pages
            || request.nonce != self.transfer + 1 + pages as u64
        {
            return Err(Error::Binding("same complete original Model transfer"));
        }
        // The native Version/Selector work happened between these exact E
        // Begin/Finish reads. No owner is recreated and no channel is replaced.
        let after = self.host.runtime.block_on(
            OriginalCellEvaluationModelReadV1::finish(
                self.evaluation.take().ok_or(Error::CommitUncertain)?,
            ),
        )?;
        if after.original_model_transfer_body() != self.body.as_slice()
            || after.original_evaluation() != &self.context.evaluation
        {
            return Err(Error::CommitUncertain);
        }
        let native = effect::observe(
            OriginalCellQ24TrainingCommandOwnerV1::read_original_model(
                self.original.as_ref(),
                self.state.model.as_mut().ok_or(Error::ReadbackRequired)?,
                &self.context,
                &after,
            ),
        )?;
        let effect::Observed::Completed(native) = native else {
            return Err(Error::CommitUncertain);
        };
        let fresh = self.context.authenticate(self.started)?;
        after.authenticate_current(fresh)?;
        let input = after.require_original_model_input(
            &self.context.training_cut, self.context.training.attestation(), fresh,
        )?;
        let wire::Outcome::Completed { record } = wire::encode_completed(
            &self.context, &native, input.material_digest(), fresh,
        )? else { return Err(Error::CommitUncertain); };
        let current = wire::decode_completed(&self.context, &record, fresh)?;
        if native != self.observed || current != self.model
            || self.state.retained.as_ref().is_some_and(|previous| previous != &current)
        {
            return Err(Error::CommitUncertain);
        }
        // A last pure check covers all E/retention windows after native I/O
        // and decoding. Only this successful end clears the once-held fence.
        let final_at = self.context.authenticate(fresh)?;
        after.authenticate_current(final_at)?;
        self.state.retained = Some(current);
        self.state.fenced = false;
        self.completed = true;
        Ok(wire::Outcome::OriginalReadFinished {
            transfer, record, total: self.body.len(), digest: self.digest.to_string(),
        })
    }
}

impl Drop for OriginalModelReadHostOperation<'_> {
    fn drop(&mut self) {
        if !self.completed { self.state.fenced = true; }
    }
}
