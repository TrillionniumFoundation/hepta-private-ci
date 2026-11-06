//! Initial publication through the existing protected Control and FinalUse
//! owners. Creation starts in Preparing, with no transient Active generation.

use std::sync::Arc;

use codex_hepta_contracts::RootAuthorityDirectory;
use codex_hepta_contracts::claim_final_use;
use codex_hepta_contracts::dispatch_final_use_with_witness;
use codex_hepta_neuron::AnchorWitnessStore;
use codex_hepta_neuron::CellGenerationJournalV2;
use codex_hepta_neuron::CellGenerationOwnerBindingV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use super::NeuronGenerationCurrentOwnerV1;
use super::NeuronGenerationUpdatePublicationV1;
use super::initial_types::InitialIntent;
use super::initial_types::InitialPublished;
use super::initial_types::InitialState;
use super::initial_types::NeuronGenerationInitialReadbackV1;
use super::initial_types::PreparedNeuronGenerationInitialV1;
use super::initial_types::PublishedNeuronGenerationInitialV1;
use super::signed_grant_digest;
use super::store::CurrentStore;
use super::types::CurrentHead;
use super::types::invalid;
use crate::AgentdError;
use crate::neuron_generation_update_selection::AgentdSelectedGenerationV1;

impl NeuronGenerationCurrentOwnerV1 {
    /// Create one initial operation using actual root custody. Existing state
    /// is never overwritten or treated as an empty namespace on recovery.
    pub fn prepare_initial(
        root: Arc<RootAuthorityDirectory>,
        operation_id: String,
        target: CellGenerationOwnerBindingV1,
        selected: &AgentdSelectedGenerationV1,
    ) -> Result<(Self, PreparedNeuronGenerationInitialV1), AgentdError> {
        let (head, prepared) = initial_head_and_prepared(operation_id, target, selected)?;
        let owner = Self { store: CurrentStore::initialize(root, head.clone())? };
        if owner.store.load()? != head {
            return Err(invalid("initial generation preparation readback differs"));
        }
        Ok((owner, prepared))
    }

    pub fn publish_initial<W: AnchorWitnessStore>(
        &self,
        prepared: &PreparedNeuronGenerationInitialV1,
        new: &CellGenerationJournalV2<W>,
        selected: &mut AgentdSelectedGenerationV1,
        publication: NeuronGenerationUpdatePublicationV1<'_>,
    ) -> Result<PublishedNeuronGenerationInitialV1, AgentdError> {
        publication.authority.current_external_frontier().map_err(invalid)?;
        selected.revalidate(
            publication.artifacts,
            publication.clock.now_unix_ms().map_err(invalid)?,
        )?;
        if selected.observation().digest().as_array() != &prepared.intent.selection
            || selected.manifest().digest().map_err(invalid)?
                != prepared.intent.target.manifest_digest()
        {
            return Err(invalid("initial selection differs from prepared operation"));
        }
        if let NeuronGenerationInitialReadbackV1::Published(published) =
            self.read_initial_operation(prepared)?
        {
            if new.owner_binding() != Some(published.target()) {
                return Err(invalid("published initial generation readback differs"));
            }
            new.require_current().map_err(invalid)?;
            return Ok(published);
        }
        self.require_initial_genesis(prepared, new)?;
        let token = claim_final_use(publication.authority, publication.signed, &prepared.binding)
            .map_err(invalid)?;
        let (result, _) = dispatch_final_use_with_witness(
            publication.authority,
            token,
            &prepared.binding,
            |witness| {
                selected.revalidate(
                    publication.artifacts,
                    publication.clock.now_unix_ms().map_err(invalid)?,
                )?;
                self.require_initial_genesis(prepared, new)?;
                let next = CurrentHead {
                    schema_version: 1,
                    current: prepared.intent.target.clone(),
                    prepared: None,
                    published: None,
                    initial: Some(InitialState::Published(Box::new(InitialPublished {
                        intent: prepared.intent.clone(),
                        witness: witness.clone(),
                        signed: publication.signed.clone(),
                        signed_grant_digest: signed_grant_digest(publication.signed)?.into_array(),
                    }))),
                };
                let expected = prepared.head.as_ref()
                    .ok_or_else(|| invalid("published initial operation cannot dispatch again"))?;
                self.store.replace(expected, &next)?;
                match self.read_initial_operation(prepared)? {
                    NeuronGenerationInitialReadbackV1::Published(published) => Ok(published),
                    NeuronGenerationInitialReadbackV1::Prepared => {
                        Err(invalid("initial generation publication remains uncertain"))
                    }
                }
            },
        ).map_err(invalid)?;
        result
    }

    /// Inspect only the retained original operation, without claiming or
    /// replaying a grant. Absence never means that publication was not applied.
    pub fn read_initial_operation(
        &self,
        prepared: &PreparedNeuronGenerationInitialV1,
    ) -> Result<NeuronGenerationInitialReadbackV1, AgentdError> {
        let head = self.store.load()?;
        if prepared.head.as_ref() == Some(&head) {
            return Ok(NeuronGenerationInitialReadbackV1::Prepared);
        }
        if let Some(InitialState::Published(record)) = head.initial
            && record.intent == prepared.intent
            && head.current == prepared.intent.target
        {
            record.validate()?;
            return Ok(NeuronGenerationInitialReadbackV1::Published(
                PublishedNeuronGenerationInitialV1 {
                    record,
                    digest: prepared.digest,
                },
            ));
        }
        Err(invalid("original initial generation operation is unavailable"))
    }

    pub fn recover_initial_operation(
        &self,
        operation_id: &str,
        expected_intent: Digest32,
    ) -> Result<PreparedNeuronGenerationInitialV1, AgentdError> {
        StableId::new(operation_id).map_err(invalid)?;
        let head = self.store.load()?;
        match &head.initial {
            Some(InitialState::Prepared(intent))
                if intent.operation_id == operation_id && intent.digest()? == expected_intent =>
            {
                Ok(PreparedNeuronGenerationInitialV1 {
                    intent: intent.as_ref().clone(), binding: intent.binding()?,
                    digest: expected_intent, head: Some(head),
                })
            }
            Some(InitialState::Published(record))
                if record.intent.operation_id == operation_id
                    && record.intent.digest()? == expected_intent =>
            {
                record.validate()?;
                Ok(PreparedNeuronGenerationInitialV1 {
                    binding: record.intent.binding()?, intent: record.intent.clone(),
                    digest: expected_intent, head: None,
                })
            }
            _ => Err(invalid("original initial generation operation cannot be recovered")),
        }
    }

    /// A new operator operation binds the same retained selection and actual
    /// empty file. It requires a new external signature; no nonce is refunded.
    pub fn prepare_initial_forward_recovery<W: AnchorWitnessStore>(
        &self,
        original: &PreparedNeuronGenerationInitialV1,
        new: &CellGenerationJournalV2<W>,
        new_operation_id: String,
    ) -> Result<PreparedNeuronGenerationInitialV1, AgentdError> {
        StableId::new(&new_operation_id).map_err(invalid)?;
        if new_operation_id == original.intent.operation_id {
            return Err(invalid("initial forward recovery requires a new operation identity"));
        }
        self.require_initial_genesis(original, new)?;
        let expected = original.head.as_ref()
            .ok_or_else(|| invalid("published initial operation cannot be prepared again"))?;
        let mut intent = original.intent.clone();
        intent.operation_id = new_operation_id;
        intent.supersedes = Some(original.digest.into_array());
        let mut head = expected.clone();
        head.initial = Some(InitialState::Prepared(Box::new(intent.clone())));
        self.store.replace(expected, &head)?;
        if self.store.load()? != head {
            return Err(invalid("initial forward preparation remains uncertain"));
        }
        Ok(PreparedNeuronGenerationInitialV1 {
            binding: intent.binding()?, digest: intent.digest()?,
            head: Some(head), intent,
        })
    }

    fn require_initial_genesis<W: AnchorWitnessStore>(
        &self,
        prepared: &PreparedNeuronGenerationInitialV1,
        new: &CellGenerationJournalV2<W>,
    ) -> Result<(), AgentdError> {
        let genesis = new.prepared_checkpoint().map_err(invalid)?;
        if genesis.binding() != &prepared.intent.target
            || genesis.checkpoint().as_array() != &prepared.intent.genesis_checkpoint
            || Some(self.store.load()?) != prepared.head
        {
            return Err(invalid("initial genesis or Control cut changed before publication"));
        }
        Ok(())
    }
}

/// Shared only inside this Control module and its private file-owner fixtures.
/// Production initialization always passes this head to the concrete root CAS.
pub(super) fn initial_head_and_prepared(
    operation_id: String,
    target: CellGenerationOwnerBindingV1,
    selected: &AgentdSelectedGenerationV1,
) -> Result<(CurrentHead, PreparedNeuronGenerationInitialV1), AgentdError> {
    target.digest().map_err(invalid)?;
    if selected.manifest().digest().map_err(invalid)? != target.manifest_digest() {
        return Err(invalid("initial generation selection differs"));
    }
    let intent = InitialIntent {
        operation_id, supersedes: None,
        genesis_checkpoint: target.genesis_checkpoint().into_array(),
        target: target.clone(), selection: selected.observation().digest().into_array(),
    };
    let head = CurrentHead {
        schema_version: 1, current: target, prepared: None, published: None,
        initial: Some(InitialState::Prepared(Box::new(intent.clone()))),
    };
    head.validate_initial()?;
    let prepared = PreparedNeuronGenerationInitialV1 {
        binding: intent.binding()?, digest: intent.digest()?,
        head: Some(head.clone()), intent,
    };
    Ok((head, prepared))
}
