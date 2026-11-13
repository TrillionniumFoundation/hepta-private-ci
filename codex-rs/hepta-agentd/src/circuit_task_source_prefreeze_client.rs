//! The same actual LedgerWriter is borrowed for the original Experience intake
//! and later moved with the same Source lane into the actual Material pair.
//! Errors after an append may represent a partial pair; they never authorize
//! fresh signatures, new ledger custody or a repeated task execution.

use std::sync::{Arc, Mutex};
use std::os::fd::OwnedFd;
use std::os::unix::net::UnixStream;
use std::time::{Duration, Instant};
use codex_hepta_learning_ledger::{LedgerWriter, SignedLearningEvidenceV1};
use codex_hepta_neuron::FileAnchorWitnessStore;
use crate::{AgentdIdentity, AgentdRootAuthorityPeer, CircuitTaskSourcePublicationV1,
    CircuitTaskSourceReadbackV1, OriginalCellQ24MaterialReceiptConfigV1,
    OriginalCircuitExperienceErrorV1, OriginalCircuitExperienceReceiptV1,
    OriginalCircuitExperienceRequestV1};
use super::{Error, OriginalCircuitPrefreezeSourceRequestV1, now};

/// Non-Clone client for one explicitly authorized, fixed original Source. It
/// exposes observations and the original intake, never a generic reader or
/// writer. The eventual Material transition consumes this exact client.
pub struct OriginalCircuitPrefreezeSourceV1 {
    source: CircuitTaskSourceReadbackV1<FileAnchorWitnessStore>,
    request: Arc<OriginalCircuitPrefreezeSourceRequestV1>,
    evidence: SignedLearningEvidenceV1,
    identity: AgentdIdentity,
    ledger: Arc<Mutex<LedgerWriter>>,
}

impl OriginalCircuitPrefreezeSourceV1 {
    /// Consume the real stream/pidfd and retain the already-open original
    /// ledger. Root separately requires its opaque protected registration.
    /// Neither these data nor the Generator signature can register that reader.
    /// Wait for the same Root task's single hint within the supplied common
    /// startup window before any Source request. The hint is scheduling only;
    /// the first observation still validates the actual current Source/Cell.
    pub fn from_original_stream(
        request: OriginalCircuitPrefreezeSourceRequestV1, evidence: SignedLearningEvidenceV1,
        identity: AgentdIdentity, ledger: Arc<Mutex<LedgerWriter>>,
        stream: UnixStream, root: AgentdRootAuthorityPeer, original_root_pidfd: OwnedFd,
        timeout: Duration, lifetime: Duration, startup_end: Instant,
    ) -> Result<Self, Error> {
        let verifier = {
            let original = ledger.try_lock().map_err(|_| Error::Unavailable)?;
            request.require_ledger(&original, &evidence, now()?)?;
            original.verifier().clone()
        };
        let request = Arc::new(request);
        let source = CircuitTaskSourceReadbackV1::from_original_prefreeze_root_stream(
            stream, root, original_root_pidfd, Arc::clone(&request), evidence.clone(), verifier,
            identity.clone(), timeout, lifetime, startup_end,
        )?;
        {
            let original = ledger.try_lock().map_err(|_| Error::Unavailable)?;
            request.require_ledger(&original, &evidence, now()?)?;
        }
        source.require_original_prefreeze_current()?;
        Ok(Self { source, request, evidence, identity, ledger })
    }

    /// First authorized observation; no Decision or freeze is needed. The full
    /// original RunStart, saved input and result come from Root's actual owner.
    pub fn read_original_publication(&self) -> Result<CircuitTaskSourcePublicationV1, Error> {
        let ledger = self.ledger.try_lock().map_err(|_| Error::Unavailable)?;
        self.request.require_ledger(&ledger, &self.evidence, now()?)?;
        let observed = CircuitTaskSourceReadbackV1::read_run_publication(
            &self.source, &self.identity, &self.request.source.scope.run_id,
        )?;
        self.request.require_ledger(&ledger, &self.evidence, now()?)?;
        self.source.require_original_prefreeze_current()?;
        Ok(observed)
    }

    /// Delegate unchanged to the original signed Generator/independent Observer
    /// intake. Its source checks and two actual appends retain their original
    /// partial-commit behavior. No new signer, outcome or retry is synthesized.
    pub fn append_original_experience_v2(&mut self, request: &OriginalCircuitExperienceRequestV1)
        -> Result<OriginalCircuitExperienceReceiptV1, OriginalCircuitExperienceErrorV1>
    {
        let mut ledger = self.ledger.try_lock().map_err(|_| Error::Unavailable)?;
        self.request.require_ledger(&ledger, &self.evidence, now()?)?;
        let receipt = crate::append_original_circuit_experience_v2(
            &self.source, &self.identity, &mut ledger, request,
        )?;
        self.request.require_ledger(&ledger, &self.evidence, now()?)?;
        self.source.require_original_prefreeze_current()?;
        Ok(receipt)
    }

    pub(crate) fn into_original_material_parts(
        self, material: &OriginalCellQ24MaterialReceiptConfigV1,
    ) -> Result<(CircuitTaskSourceReadbackV1<FileAnchorWitnessStore>, AgentdIdentity,
        Arc<Mutex<LedgerWriter>>), Error>
    {
        let observed = self.read_original_publication()?;
        crate::cell_q24_dataset::require_source(&self.identity, &observed, &material.initial.request)
            .map_err(|_| Error::InvalidBinding)?;
        material.original_source_loan_binding(now()?).map_err(|_| Error::InvalidBinding)?;
        if material.verifier.trust_digest() != self.request.evidence_trust_digest
            || material.experience_signer != self.request.experience_signer
            || material.dataset_signer != self.request.dataset_signer
            || material.initial.owners.experience != self.request.experience_signer.principal.principal_id
            || material.initial.owners.dataset != self.request.dataset_signer.principal.principal_id
        { return Err(Error::InvalidBinding); }
        {
            let ledger = self.ledger.try_lock().map_err(|_| Error::Unavailable)?;
            self.request.require_ledger(&ledger, &self.evidence, now()?)?;
        }
        self.source.require_original_prefreeze_current()?;
        // No channel, counter, deadline, ledger or witness is rebuilt here.
        Ok((self.source, self.identity, self.ledger))
    }
}
