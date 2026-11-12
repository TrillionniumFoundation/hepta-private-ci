//! Closed original initial-publication operations. These helpers reuse the
//! original initial intent and head validation; no update or arbitrary CAS is
//! accepted through the distinct Root initial-purpose lane.

use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_contracts::VerifiedUseTokenWitnessV1;

use super::initial_types::InitialPublished;
use super::initial_types::InitialState;
use super::*;

/// A description only. Reserving CURRENT still requires the original Root
/// store and prepare_initial; this value has no publication authority.
pub(crate) fn original_initial_description(
    operation: String,
    target: CellGenerationOwnerBindingV1,
    selected: &AgentdSelectedGenerationV1,
) -> Result<(CurrentHead, PreparedNeuronGenerationInitialV1), AgentdError> {
    initial::initial_head_and_prepared(operation, target, selected)
}

/// Return only a validated retained publication, or the exact preparation.
/// A forward operation, update, extra preparation or other target is refused.
pub(crate) fn original_initial_record(
    prepared: &CurrentHead,
    actual: &CurrentHead,
) -> Result<Option<(SignedFinalUseGrant, VerifiedUseTokenWitnessV1)>, AgentdError> {
    prepared.validate_initial()?;
    let Some(InitialState::Prepared(intent)) = &prepared.initial else {
        return Err(invalid("original initial preparation required"));
    };
    if intent.supersedes.is_some() {
        return Err(invalid("initial-purpose lane cannot forward an operation"));
    }
    if actual == prepared {
        return Ok(None);
    }
    actual.validate_initial()?;
    let Some(InitialState::Published(record)) = &actual.initial else {
        return Err(invalid("original initial publication required"));
    };
    let expected = CurrentHead {
        schema_version: 1,
        current: intent.target.clone(),
        prepared: None,
        published: None,
        initial: Some(InitialState::Published(Box::new(InitialPublished {
            intent: intent.as_ref().clone(),
            signed: record.signed.clone(),
            witness: record.witness.clone(),
            signed_grant_digest: signed_grant_digest(&record.signed)?.into_array(),
        }))),
    };
    if actual != &expected {
        return Err(invalid(
            "original initial operation or complete head differs",
        ));
    }
    record.validate()?;
    Ok(Some((record.signed.clone(), record.witness.clone())))
}

pub(crate) fn original_initial_next(
    prepared: &CurrentHead,
    signed: &SignedFinalUseGrant,
    witness: &VerifiedUseTokenWitnessV1,
) -> Result<CurrentHead, AgentdError> {
    prepared.validate_initial()?;
    let Some(InitialState::Prepared(intent)) = &prepared.initial else {
        return Err(invalid("original initial preparation required"));
    };
    let next = CurrentHead {
        schema_version: 1,
        current: intent.target.clone(),
        prepared: None,
        published: None,
        initial: Some(InitialState::Published(Box::new(InitialPublished {
            intent: intent.as_ref().clone(),
            signed: signed.clone(),
            witness: witness.clone(),
            signed_grant_digest: signed_grant_digest(signed)?.into_array(),
        }))),
    };
    original_initial_record(prepared, &next)?;
    Ok(next)
}

impl NeuronGenerationCurrentOwnerV1 {
    pub(crate) fn require_original_initial_source_session(
        &self,
        session: &crate::AgentdRootAuthoritySession,
        identity: &crate::AgentdIdentity,
    ) -> Result<(), AgentdError> {
        self.store
            .original_source_capture_client()?
            .require_source_capture_session(session, identity)
    }

    pub(crate) fn capture_original_initial_source(
        &self,
        closed: crate::circuit_task::OriginalCircuitSourceClosedV1,
    ) -> Result<(), AgentdError> {
        self.store
            .original_source_capture_client()?
            .capture_source_after_quiescence(closed)
    }

    pub(crate) fn original_broker_initial_publish(
        &self,
        expected: &CurrentHead,
        signed: &SignedFinalUseGrant,
        witness: &VerifiedUseTokenWitnessV1,
    ) -> Result<(), AgentdError> {
        if !self.store.is_original_host() {
            return Err(invalid("original Root initial CURRENT store required"));
        }
        let next = original_initial_next(expected, signed, witness)?;
        // Exact expected-state CAS remains the only mutation. The serving
        // owner brackets it with the sticky original readback checks; a CAS
        // acknowledgement error alone never invents a source-corruption fence.
        self.store.replace(expected, &next)
    }

    pub(crate) fn from_original_root_initial(
        original: Arc<crate::root_generation_initial_client::RootGenerationInitialClient>,
    ) -> Result<Self, AgentdError> {
        let store = store::CurrentStore::from_original_initial(original)?;
        store.load()?;
        Ok(Self { store })
    }

    pub(crate) fn revalidate_original_initial_artifacts(
        &self,
        artifacts: &crate::root_generation_initial_client::OriginalInitialArtifactReadbackV1,
        selected: &mut AgentdSelectedGenerationV1,
        now: u64,
    ) -> Result<(), AgentdError> {
        artifacts.revalidate(self.store.original_initial_client()?, selected, now)
    }
}

pub(crate) fn require_original_initial_contract(
    head: &CurrentHead,
    operation: &str,
    target: &CellGenerationOwnerBindingV1,
    intent_digest: codex_hepta_types::Digest32,
    selection: codex_hepta_types::Digest32,
    binding: &codex_hepta_contracts::FinalUseBinding,
) -> Result<(), AgentdError> {
    original_initial_record(head, head)?;
    let Some(InitialState::Prepared(intent)) = &head.initial else {
        return Err(invalid("original initial preparation required"));
    };
    if intent.operation_id != operation
        || &intent.target != target
        || intent.digest()? != intent_digest
        || intent.selection != selection.into_array()
        || &intent.binding()? != binding
    {
        return Err(invalid("original complete initial contract differs"));
    }
    Ok(())
}
