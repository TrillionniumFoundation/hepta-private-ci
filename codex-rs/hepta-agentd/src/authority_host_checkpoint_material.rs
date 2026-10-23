//! Speculative image preparation and final admission for the original CAS.

use super::*;

pub(crate) enum MaterialIntent {
    Prepare(CognitiveRecoveryAnchor),
    Retained(CognitiveRecoveryAnchor),
}

impl HostCognitiveCheckpoint {
    /// Inspect the original complete predecessor without advancing it. Bad or
    /// stale requests still reach the original handler's definite refusal.
    pub(crate) fn material_intent(&self, raw: &[u8]) -> Result<Option<MaterialIntent>, AuthorityTrustError> {
        if raw.is_empty() || raw.len() > COGNITIVE_CHECKPOINT_FRAME_LIMIT {
            return Err(AuthorityTrustError::Invalid);
        }
        let request: CognitiveCheckpointRequest = serde_json::from_slice(raw)
            .map_err(|_| AuthorityTrustError::Invalid)?;
        if !matches!(request.command, CognitiveCheckpointCommand::PreparePublication | CognitiveCheckpointCommand::CommitPublication) {
            return Ok(None);
        }
        let _guard = self.exchange_lock.lock().map_err(|_| AuthorityTrustError::Unavailable)?;
        if self.closed.load(Ordering::Acquire) || !self.within_expiry()? {
            return Err(AuthorityTrustError::Unavailable);
        }
        let Some((epoch, sequence)) = request_sequence(&request.request_id) else {
            return Ok(None);
        };
        if request.schema_version != 1 || request.operation != OPERATION || epoch != self.registration.publisher_epoch {
            return Ok(None);
        }
        let current = self.load()?;
        let digest = Sha256Digest::for_bytes(raw);
        if let Some(last) = current.last_request.as_ref()
            && last.request_id == request.request_id
        {
            if last.request_sha256 != digest || last.command != request.command
                || request.expected.as_ref() != Some(&last.predecessor_token)
            {
                return Ok(None);
            }
            return Ok(Self::material_cut(request.command, &current).cloned().map(MaterialIntent::Retained));
        }
        if sequence <= current.last_mutation_sequence {
            return Ok(None);
        }
        let predecessor = token_for(&current)?;
        if request.expected.as_ref() != Some(&predecessor) {
            return Ok(None);
        }
        let Ok(next) = advance(&self.registration, &current, &request, digest, predecessor, sequence) else {
            return Ok(None);
        };
        Ok(Self::material_cut(request.command, &next).cloned().map(|cut| {
            match request.command {
                CognitiveCheckpointCommand::PreparePublication => MaterialIntent::Prepare(cut),
                _ => MaterialIntent::Retained(cut),
            }
        }))
    }

    fn material_cut(command: CognitiveCheckpointCommand, head: &CognitiveCheckpointHead) -> Option<&CognitiveRecoveryAnchor> {
        match command {
            CognitiveCheckpointCommand::PreparePublication => head.proposal.as_ref().map(|proposal| &proposal.cut),
            CognitiveCheckpointCommand::CommitPublication => Some(&head.last_current),
            _ => None,
        }
    }

    fn material_authorizes(
        &self,
        request: &CognitiveCheckpointRequest,
        raw: &[u8],
        next: &CognitiveCheckpointHead,
        evidence: PublicationMaterial<'_>,
    ) -> bool {
        match evidence {
            PublicationMaterial::MetadataProtocol => true,
            PublicationMaterial::Required(prepared) => {
                match Self::material_cut(request.command, next) {
                    None => true,
                    Some(cut) => prepared.is_some_and(|prepared| prepared.validate(raw, cut).is_ok()),
                }
            }
        }
    }

    pub(crate) fn retained_current_for_root(&self) -> Result<CognitiveCheckpointHead, AuthorityTrustError> {
        let _guard = self.exchange_lock.lock().map_err(|_| AuthorityTrustError::Unavailable)?;
        let head = self.load()?;
        if self.closed.load(Ordering::Acquire) || head.phase != CognitiveCheckpointPhase::Current || !self.within_expiry()? {
            return Err(AuthorityTrustError::Unavailable);
        }
        Ok(head)
    }
}
