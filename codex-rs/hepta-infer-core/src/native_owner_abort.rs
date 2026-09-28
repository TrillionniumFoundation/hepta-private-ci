//! Negative outbox in the existing native control journal, not a second store.
use super::*;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct NativeOwnerBinding {
    pub run_id: String,
    pub generation: u64,
    pub expected_revision: u64,
    pub request_digest: String,
    pub context_digest: String,
    pub compilation_receipt_digest: String,
}

impl NativeOwnerBinding {
    pub(super) fn validate(&self) -> Result<(), Error> {
        validate_identity(&self.run_id, "owner run")?;
        if self.generation == 0 || self.expected_revision == 0 || self.expected_revision == u64::MAX
        {
            return Err(Error::InvalidIdentity("owner generation/revision"));
        }
        for digest in [
            &self.request_digest,
            &self.context_digest,
            &self.compilation_receipt_digest,
        ] {
            validate_digest(digest, "owner binding")?;
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct NativeOwnerAbort {
    pub binding: NativeOwnerBinding,
    pub reason: String,
    pub acknowledged_revision: Option<u64>,
}

pub(super) fn prepare_owner_abort(
    record: &mut NativeRunRecord,
    binding: NativeOwnerBinding,
    reason: String,
) -> Result<(), Error> {
    binding.validate()?;
    if binding.generation != record.request.worker_generation
        || reason.trim().is_empty()
        || reason.len() > 512
        || reason.contains('\0')
        || record.owner_abort.is_some()
        || record.turn_id.is_some()
        || record.observation.is_some()
        || record.dispatch_rejection.is_some()
        || record.cancel_requested
    {
        return Err(Error::InvalidTransition);
    }
    record.pre_dispatch_stop = Some(reason.clone());
    record.owner_abort = Some(NativeOwnerAbort {
        binding,
        reason,
        acknowledged_revision: None,
    });
    record.state = NativeReservationState::AbortPendingOwner;
    Ok(())
}

impl DurableInferenceControl {
    /// Reserved is the only state from which no live dispatch token is needed:
    /// no physical turn/start could have occurred. The owner decides whether a
    /// competing send permit exists; lack of an ACK retains local capacity.
    pub fn stop_native_with_owner(
        &mut self,
        request_id: &str,
        binding: NativeOwnerBinding,
        reason: String,
    ) -> Result<NativeRunRecord, Error> {
        self.commit_native(
            request_id,
            Event::PrepareOwnerAbort {
                request_id: request_id.to_string(),
                binding,
                reason,
            },
        )
    }

    /// Trusted-host journal port. Invoke only with the exact negative response
    /// returned by the authenticated Agentd client. These fields are an audit
    /// acknowledgement, not an authority grant or a provider terminal witness.
    pub fn acknowledge_native_owner_abort(
        &mut self,
        request_id: &str,
        binding: NativeOwnerBinding,
        reason: String,
        owner_revision: u64,
    ) -> Result<NativeRunRecord, Error> {
        let current = self
            .native
            .records
            .get(request_id)
            .ok_or(Error::RequestNotFound)?;
        if current.state == NativeReservationState::Released {
            return match &current.owner_abort {
                Some(notice)
                    if notice.binding == binding
                        && notice.reason == reason
                        && notice.acknowledged_revision == Some(owner_revision) =>
                {
                    Ok(current.clone())
                }
                _ => Err(Error::Conflict),
            };
        }
        self.commit_native(
            request_id,
            Event::AcknowledgeOwnerAbort {
                request_id: request_id.to_string(),
                binding,
                reason,
                owner_revision,
            },
        )
    }
}
