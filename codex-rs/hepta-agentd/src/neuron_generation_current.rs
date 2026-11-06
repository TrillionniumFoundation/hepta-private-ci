//! Task-boundary replacement through the existing protected Control store.
//! The old terminal journal remains exclusively held across one publication
//! CAS. This owner records control facts only, never state, prefix or outbox.

use std::sync::Arc;

use codex_hepta_contracts::AuthorityClock;
use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::RootAuthorityDirectory;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_contracts::claim_final_use;
use codex_hepta_contracts::dispatch_final_use_with_witness;
use codex_hepta_learning_artifacts::LearningArtifactOwnerService;
use codex_hepta_neuron::AnchorWitnessStore;
use codex_hepta_neuron::CellGenerationCurrentV1;
use codex_hepta_neuron::CellGenerationErrorV2;
use codex_hepta_neuron::CellGenerationJournalV2;
use codex_hepta_neuron::CellGenerationOpenModeV1;
use codex_hepta_neuron::CellGenerationOwnerBindingV1;
use codex_hepta_neuron::CellGenerationScopeV2;
use codex_hepta_types::StableId;

use crate::AgentdError;
use crate::neuron_generation_update_selection::AgentdSelectedGenerationV1;

#[path = "neuron_generation_current_store.rs"]
mod store;
#[path = "neuron_generation_current_types.rs"]
mod types;

use types::CurrentHead;
pub use types::NeuronGenerationUpdateReadbackV1;
pub use types::PreparedNeuronGenerationUpdateV1;
use types::Published;
pub use types::PublishedNeuronGenerationUpdateV1;
use types::UpdateIntent;
use types::invalid;
use types::scope_digest;

/// Concrete root custody. Construction requires the existing validated root
/// directory; there is no generic production store, permissive default, root
/// discovery, signing key or automatic initialization on reopen. The trusted
/// host must retain this owner independently of Agent-writable state.
pub struct NeuronGenerationCurrentOwnerV1 {
    store: store::CurrentStore,
}

pub struct NeuronGenerationUpdatePublicationV1<'a> {
    pub artifacts: &'a mut LearningArtifactOwnerService,
    pub authority: &'a FinalUseAuthority,
    pub signed: &'a SignedFinalUseGrant,
    pub clock: &'a dyn AuthorityClock,
}

impl NeuronGenerationCurrentOwnerV1 {
    pub fn initialize(
        root: Arc<RootAuthorityDirectory>,
        initial: CellGenerationOwnerBindingV1,
    ) -> Result<Self, AgentdError> {
        initial.digest().map_err(invalid)?;
        let store = store::CurrentStore::initialize(
            root,
            CurrentHead {
                schema_version: 1,
                current: initial,
                prepared: None,
                published: None,
            },
        )?;
        Ok(Self { store })
    }

    pub fn open(
        root: Arc<RootAuthorityDirectory>,
        scope: &CellGenerationScopeV2,
    ) -> Result<Self, AgentdError> {
        let store = store::CurrentStore::open(root, scope)?;
        store.load()?;
        Ok(Self { store })
    }

    pub fn prepare<W: AnchorWitnessStore>(
        &self,
        old: &CellGenerationJournalV2<W>,
        operation_id: String,
        target: CellGenerationOwnerBindingV1,
        selected: &AgentdSelectedGenerationV1,
    ) -> Result<PreparedNeuronGenerationUpdateV1, AgentdError> {
        StableId::new(&operation_id).map_err(invalid)?;
        let previous = old
            .owner_binding()
            .ok_or_else(|| invalid("unguarded generation update"))?
            .clone();
        let observation = old.observe_generation().map_err(invalid)?;
        if !observation.is_terminal() || !old.is_drained().map_err(invalid)? {
            return Err(invalid("generation update requires STOP, ACK and drain"));
        }
        target.digest().map_err(invalid)?;
        if scope_digest(previous.scope())? != scope_digest(target.scope())?
            || previous.scope().run_id == target.scope().run_id
            || previous.task_digest() == target.task_digest()
            || previous.manifest_digest() == target.manifest_digest()
            || previous.generation().checked_add(1) != Some(target.generation())
            || previous.writer_epoch().checked_add(1) != Some(target.writer_epoch())
            || selected.manifest().digest().map_err(invalid)? != target.manifest_digest()
        {
            return Err(invalid("generation replacement binding differs"));
        }
        let intent = UpdateIntent {
            operation_id,
            supersedes: None,
            previous,
            previous_checkpoint: observation.owner_checkpoint().into_array(),
            previous_observation: observation.digest().map_err(invalid)?,
            genesis_checkpoint: target.genesis_checkpoint().into_array(),
            target,
            selection: selected.observation().digest().into_array(),
        };
        let mut head = self.store.load()?;
        if head.current != intent.previous {
            return Err(invalid("generation predecessor is not current"));
        }
        match &head.prepared {
            Some(existing) if existing == &intent => {}
            Some(_) => return Err(invalid("another generation update remains pending")),
            None => {
                let expected = head.clone();
                head.prepared = Some(intent.clone());
                self.store.replace(&expected, &head)?;
            }
        }
        if self.store.load()? != head {
            return Err(invalid("generation preparation readback differs"));
        }
        Ok(PreparedNeuronGenerationUpdateV1 {
            binding: intent.binding()?,
            digest: intent.digest()?,
            head: Some(head),
            intent,
        })
    }

    /// Explicit operator recovery of the same prepared files and selection.
    /// A distinct operation binding requires a new independent signature. This
    /// does not infer NotApplied, reset an epoch, refund a nonce or publish.
    pub fn prepare_forward_recovery<WOld: AnchorWitnessStore, WNew: AnchorWitnessStore>(
        &self,
        original: &PreparedNeuronGenerationUpdateV1,
        old: &CellGenerationJournalV2<WOld>,
        new: &CellGenerationJournalV2<WNew>,
        new_operation_id: String,
    ) -> Result<PreparedNeuronGenerationUpdateV1, AgentdError> {
        StableId::new(&new_operation_id).map_err(invalid)?;
        if new_operation_id == original.intent.operation_id {
            return Err(invalid(
                "forward recovery requires a new operation identity",
            ));
        }
        self.require_prepared_journals(original, old, new)?;
        let expected = original
            .head
            .as_ref()
            .ok_or_else(|| invalid("published update cannot be prepared again"))?;
        let mut intent = original.intent.clone();
        intent.operation_id = new_operation_id;
        intent.supersedes = Some(original.digest.into_array());
        let mut head = expected.clone();
        head.prepared = Some(intent.clone());
        self.store.replace(expected, &head)?;
        if self.store.load()? != head {
            return Err(invalid("forward preparation remains uncertain"));
        }
        Ok(PreparedNeuronGenerationUpdateV1 {
            binding: intent.binding()?,
            digest: intent.digest()?,
            head: Some(head),
            intent,
        })
    }

    pub fn publish<WOld: AnchorWitnessStore, WNew: AnchorWitnessStore>(
        &self,
        prepared: &PreparedNeuronGenerationUpdateV1,
        old: &CellGenerationJournalV2<WOld>,
        new: &CellGenerationJournalV2<WNew>,
        selected: &mut AgentdSelectedGenerationV1,
        publication: NeuronGenerationUpdatePublicationV1<'_>,
    ) -> Result<PublishedNeuronGenerationUpdateV1, AgentdError> {
        publication
            .authority
            .current_external_frontier()
            .map_err(invalid)?;
        selected.revalidate(
            publication.artifacts,
            publication.clock.now_unix_ms().map_err(invalid)?,
        )?;
        if selected.observation().digest().as_array() != &prepared.intent.selection {
            return Err(invalid(
                "generation selection differs from prepared operation",
            ));
        }
        if let NeuronGenerationUpdateReadbackV1::Published(published) =
            self.read_operation(prepared)?
        {
            if new.owner_binding() != Some(published.target()) {
                return Err(invalid("published generation readback differs"));
            }
            new.require_current().map_err(invalid)?;
            return Ok(published);
        }
        self.require_prepared_journals(prepared, old, new)?;
        let token = claim_final_use(publication.authority, publication.signed, &prepared.binding)
            .map_err(invalid)?;
        // Only this bounded synchronous original-authority entry changes the
        // current writer. Lost acknowledgement never manufactures a new nonce.
        let (result, _) = dispatch_final_use_with_witness(
            publication.authority,
            token,
            &prepared.binding,
            |witness| {
                selected.revalidate(
                    publication.artifacts,
                    publication.clock.now_unix_ms().map_err(invalid)?,
                )?;
                self.require_prepared_journals(prepared, old, new)?;
                let next = CurrentHead {
                    schema_version: 1,
                    current: prepared.intent.target.clone(),
                    prepared: None,
                    published: Some(Published {
                        intent: prepared.intent.clone(),
                        witness: witness.clone(),
                        signed: publication.signed.clone(),
                        signed_grant_digest: signed_grant_digest(publication.signed)?.into_array(),
                    }),
                };
                let expected = prepared
                    .head
                    .as_ref()
                    .ok_or_else(|| invalid("published operation cannot dispatch again"))?;
                self.store.replace(expected, &next)?;
                match self.read_operation(prepared)? {
                    NeuronGenerationUpdateReadbackV1::Published(published) => Ok(published),
                    NeuronGenerationUpdateReadbackV1::Prepared => {
                        Err(invalid("generation publication remains uncertain"))
                    }
                }
            },
        )
        .map_err(invalid)?;
        result
    }

    /// Reconstruct only an exact retained Control record after process loss.
    /// This read neither claims a grant nor writes a frontier. A published
    /// record is recoverable without reopening the retired predecessor.
    pub fn recover_operation(
        &self,
        operation_id: &str,
        expected_intent: codex_hepta_types::Digest32,
    ) -> Result<PreparedNeuronGenerationUpdateV1, AgentdError> {
        StableId::new(operation_id).map_err(invalid)?;
        let head = self.store.load()?;
        if let Some(intent) = &head.prepared
            && intent.operation_id == operation_id
            && intent.digest()? == expected_intent
        {
            return Ok(PreparedNeuronGenerationUpdateV1 {
                intent: intent.clone(),
                binding: intent.binding()?,
                digest: expected_intent,
                head: Some(head),
            });
        }
        if let Some(record) = head.published
            && record.intent.operation_id == operation_id
            && record.intent.digest()? == expected_intent
            && head.current == record.intent.target
        {
            record.witness.validate().map_err(invalid)?;
            if signed_grant_digest(&record.signed)?.as_array() != &record.signed_grant_digest
                || record.signed.grant.binding != record.intent.binding()?
            {
                return Err(invalid("retained generation grant differs"));
            }
            return Ok(PreparedNeuronGenerationUpdateV1 {
                binding: record.intent.binding()?,
                intent: record.intent,
                digest: expected_intent,
                head: None,
            });
        }
        Err(invalid("original generation update cannot be recovered"))
    }

    /// Inspect only the exact original operation. Missing/different state is
    /// an error, never NotApplied and never authority to retry a spent grant.
    pub fn read_operation(
        &self,
        prepared: &PreparedNeuronGenerationUpdateV1,
    ) -> Result<NeuronGenerationUpdateReadbackV1, AgentdError> {
        let head = self.store.load()?;
        if prepared.head.as_ref() == Some(&head) {
            return Ok(NeuronGenerationUpdateReadbackV1::Prepared);
        }
        if let Some(record) = head.published
            && record.intent == prepared.intent
            && head.current == prepared.intent.target
        {
            record.witness.validate().map_err(invalid)?;
            if signed_grant_digest(&record.signed)?.as_array() != &record.signed_grant_digest
                || record.signed.grant.binding != record.intent.binding()?
            {
                return Err(invalid("retained generation grant differs"));
            }
            return Ok(NeuronGenerationUpdateReadbackV1::Published(
                PublishedNeuronGenerationUpdateV1 {
                    record: Box::new(record),
                    digest: prepared.digest,
                },
            ));
        }
        Err(invalid("original generation update is unavailable"))
    }

    fn require_prepared_journals<WOld: AnchorWitnessStore, WNew: AnchorWitnessStore>(
        &self,
        prepared: &PreparedNeuronGenerationUpdateV1,
        old: &CellGenerationJournalV2<WOld>,
        new: &CellGenerationJournalV2<WNew>,
    ) -> Result<(), AgentdError> {
        let observation = old.observe_generation().map_err(invalid)?;
        let genesis = new.prepared_checkpoint().map_err(invalid)?;
        if old.owner_binding() != Some(&prepared.intent.previous)
            || !observation.is_terminal()
            || !old.is_drained().map_err(invalid)?
            || observation.owner_checkpoint().as_array() != &prepared.intent.previous_checkpoint
            || observation.digest().map_err(invalid)? != prepared.intent.previous_observation
            || genesis.binding() != &prepared.intent.target
            || genesis.checkpoint().as_array() != &prepared.intent.genesis_checkpoint
            || Some(self.store.load()?) != prepared.head
        {
            return Err(invalid(
                "generation files or Control cut changed before publication",
            ));
        }
        Ok(())
    }
}

impl CellGenerationCurrentV1 for NeuronGenerationCurrentOwnerV1 {
    fn check_open(
        &self,
        binding: &CellGenerationOwnerBindingV1,
    ) -> Result<CellGenerationOpenModeV1, CellGenerationErrorV2> {
        let head = self
            .store
            .load()
            .map_err(|_| CellGenerationErrorV2::Unavailable)?;
        if &head.current == binding {
            Ok(CellGenerationOpenModeV1::Active)
        } else if head
            .prepared
            .as_ref()
            .is_some_and(|intent| &intent.target == binding)
        {
            Ok(CellGenerationOpenModeV1::Preparing)
        } else {
            Err(CellGenerationErrorV2::InvalidBinding)
        }
    }

    fn check_current(
        &self,
        binding: &CellGenerationOwnerBindingV1,
    ) -> Result<(), CellGenerationErrorV2> {
        match self.check_open(binding)? {
            CellGenerationOpenModeV1::Active => Ok(()),
            CellGenerationOpenModeV1::Preparing => Err(CellGenerationErrorV2::Pending),
        }
    }
}

fn signed_grant_digest(
    signed: &SignedFinalUseGrant,
) -> Result<codex_hepta_types::Digest32, AgentdError> {
    let bytes = serde_json::to_vec(signed).map_err(invalid)?;
    Ok(codex_hepta_types::Digest32::of_parts(&[
        b"hepta.agentd.generation-update-signed-grant.v1\0",
        &bytes,
    ]))
}

#[cfg(test)]
#[path = "neuron_generation_current_tests.rs"]
mod tests;

#[cfg(test)]
#[path = "neuron_generation_update_test_support.rs"]
pub(crate) mod test_support;
