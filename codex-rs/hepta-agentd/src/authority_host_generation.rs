//! Fixed initial-generation assembly from the existing Root service owners.
//! No issuer, lease, consumer, grant or journal is created by binding inputs.

use std::sync::Arc;
use std::sync::Mutex;
use std::time::Instant;

use codex_hepta_contracts::AuthorityClock;
use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::HostAuthorityClock;
use codex_hepta_contracts::RootAuthorityDirectory;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_contracts::authority_lease::AuthorityLease;
use codex_hepta_contracts::authority_lease::AuthorityLeaseBinding;
use codex_hepta_contracts::authority_lease::AuthorityLeaseRegistry;
use codex_hepta_learning_artifacts::LearningArtifactOwnerService;
use codex_hepta_neuron::AnchorWitnessStore;
use codex_hepta_neuron::CellGenerationScopeV2;
use codex_hepta_types::Digest32;

use super::HostAuthorityService;
use crate::AgentdError;
use crate::DeploymentFinalUseIssuer;
use crate::OriginalRootInitialGenerationCustodyV1;
use crate::neuron_generation_current::NeuronGenerationCurrentOwnerV1;
use crate::neuron_generation_current::NeuronGenerationInitialReadbackV1;
use crate::neuron_generation_initial::prepare_agentd_generation_initial_v1;
use crate::neuron_generation_initial::validate_initial_target;
use crate::neuron_generation_update::AgentdGenerationUpdateRecoveryV1;
use crate::neuron_generation_update::AgentdGenerationUpdateRequestV1;
use crate::neuron_generation_update::AgentdGenerationUpdateTargetV1;
use crate::neuron_generation_update_live::AgentdGenerationUpdateAuthoritiesV1;
use crate::neuron_generation_update_selection::AgentdSelectedGenerationV1;

#[path = "authority_host_generation_request.rs"]
mod request;

/// Actual trusted-host inputs for one fresh original operation. The signed
/// grant must already exist at the same protected issuer. This is not serde
/// input, a lease registration, or a request to mint publication authority.
pub struct RootHostInitialGenerationInputsV1<W: AnchorWitnessStore> {
    pub artifacts: Arc<Mutex<LearningArtifactOwnerService>>,
    pub final_use: Arc<FinalUseAuthority>,
    pub selected: AgentdSelectedGenerationV1,
    pub target: AgentdGenerationUpdateTargetV1<W>,
    pub request: AgentdGenerationUpdateRequestV1,
    pub signed: SignedFinalUseGrant,
}

/// Open-only recovery inputs. The original signed publication comes from the
/// actual protected CURRENT record, not a caller's receipt or readiness flag.
pub struct RootHostInitialGenerationRecoveryV1<W: AnchorWitnessStore> {
    pub artifacts: Arc<Mutex<LearningArtifactOwnerService>>,
    pub final_use: Arc<FinalUseAuthority>,
    pub selected: AgentdSelectedGenerationV1,
    pub target: AgentdGenerationUpdateTargetV1<W>,
    pub recovery: AgentdGenerationUpdateRecoveryV1,
}

struct OriginalInitialIdentity {
    scope: CellGenerationScopeV2,
    recovery: AgentdGenerationUpdateRecoveryV1,
    binding: FinalUseBinding,
    signed: SignedFinalUseGrant,
}

/// Private fixed custody; no public getter exports these original owners.
pub(crate) struct OriginalHostInitialOperation {
    root: Arc<RootAuthorityDirectory>,
    registry: Arc<AuthorityLeaseRegistry>,
    issuer: Arc<DeploymentFinalUseIssuer>,
    clock: Arc<HostAuthorityClock>,
    authorities: AgentdGenerationUpdateAuthoritiesV1,
    identity: OriginalInitialIdentity,
    end: Instant,
}

#[derive(Clone, Copy)]
enum GrantObservation {
    BeforePublication,
    RetainedPublication,
}

impl HostAuthorityService {
    pub(crate) fn bind_original_initial_operation<W: AnchorWitnessStore>(
        &self,
        inputs: &RootHostInitialGenerationInputsV1<W>,
        end: Instant,
    ) -> Result<OriginalHostInitialOperation, AgentdError> {
        let binding = NeuronGenerationCurrentOwnerV1::original_initial_publication_binding(
            inputs.request.operation_id.clone(),
            validate_initial_target(&inputs.selected, &inputs.target)?,
            &inputs.selected,
        )?;
        let operation = self.original_initial_operation(
            OriginalInitialIdentity {
                scope: inputs.target.config.initial.scope.clone(),
                recovery: AgentdGenerationUpdateRecoveryV1 {
                    operation_id: inputs.request.operation_id.clone(),
                    intent_digest: Digest32::from_array(binding.request_sha256),
                },
                binding,
                signed: inputs.signed.clone(),
            },
            Arc::clone(&inputs.artifacts),
            Arc::clone(&inputs.final_use),
            end,
        )?;
        operation.require_original(GrantObservation::BeforePublication)?;
        Ok(operation)
    }

    pub(crate) fn recover_original_initial_operation<W: AnchorWitnessStore>(
        &self,
        inputs: RootHostInitialGenerationRecoveryV1<W>,
        end: Instant,
    ) -> Result<(OriginalHostInitialOperation, OriginalRootInitialGenerationCustodyV1<W>), AgentdError>
    {
        let root = Arc::clone(self.resident_store_root.as_ref().ok_or_else(|| {
            invalid("the original Root directory is required for generation recovery")
        })?);
        let current = Arc::new(NeuronGenerationCurrentOwnerV1::open(
            root,
            &inputs.target.config.initial.scope,
        )?);
        let prepared = current.recover_initial_operation(
            &inputs.recovery.operation_id,
            inputs.recovery.intent_digest,
        )?;
        let NeuronGenerationInitialReadbackV1::Published(published) =
            current.read_initial_operation(&prepared)?
        else {
            return Err(invalid("original generation is still pending; no preparation fallback"));
        };
        let operation = self.original_initial_operation(
            OriginalInitialIdentity {
                scope: inputs.target.config.initial.scope.clone(),
                recovery: inputs.recovery,
                binding: prepared.final_use_binding().clone(),
                signed: published.signed_grant().clone(),
            },
            inputs.artifacts,
            inputs.final_use,
            end,
        )?;
        operation.require_original(GrantObservation::RetainedPublication)?;
        let custody = OriginalRootInitialGenerationCustodyV1::recover_from_original_current(
            current,
            operation.authorities.clone(),
            inputs.selected,
            inputs.target,
            operation.recovery(),
        )?;
        operation.require_observed(
            &OriginalRootInitialGenerationCustodyV1::read_original_operation(&custody)?,
        )?;
        Ok((operation, custody))
    }

    fn original_initial_operation(
        &self,
        identity: OriginalInitialIdentity,
        artifacts: Arc<Mutex<LearningArtifactOwnerService>>,
        final_use: Arc<FinalUseAuthority>,
        end: Instant,
    ) -> Result<OriginalHostInitialOperation, AgentdError> {
        if identity.scope.agent_id != self.identity.agent_id.as_str()
            || identity.binding.subject_id != self.identity.agent_id.as_str()
            || identity.binding.destination_id != "agentd.cell-generation.initialize"
            || identity.signed.grant.binding != identity.binding
        {
            return Err(invalid("initial generation differs from the registered host operation"));
        }
        Ok(OriginalHostInitialOperation {
            root: Arc::clone(self.resident_store_root.as_ref().ok_or_else(|| {
                invalid("the original Root directory is required for generation preparation")
            })?),
            registry: Arc::clone(self.root_registry.as_ref().ok_or_else(|| {
                invalid("the original Root lease Registry is required")
            })?),
            issuer: Arc::clone(&self.issuer),
            clock: Arc::clone(&self.clock),
            authorities: AgentdGenerationUpdateAuthoritiesV1::new(
                artifacts,
                final_use,
                self.clock.clone(),
            )?,
            identity,
            end,
        })
    }
}

impl OriginalHostInitialOperation {
    pub(crate) fn publish<W: AnchorWitnessStore>(
        &self,
        inputs: RootHostInitialGenerationInputsV1<W>,
    ) -> Result<OriginalRootInitialGenerationCustodyV1<W>, AgentdError> {
        self.require_original(GrantObservation::BeforePublication)?;
        let prepared = prepare_agentd_generation_initial_v1(
            Arc::clone(&self.root),
            self.authorities.clone(),
            inputs.selected,
            inputs.target,
            inputs.request,
        )?;
        if prepared.final_use_binding() != &self.identity.binding
            || prepared.intent_digest() != self.identity.recovery.intent_digest
        {
            return Err(invalid("actual preparation differs from the original binding preview"));
        }
        let mut custody = OriginalRootInitialGenerationCustodyV1::from_original_prepared(
            prepared,
            self.identity.recovery.operation_id.clone(),
        )?;
        self.require_original(GrantObservation::BeforePublication)?;
        OriginalRootInitialGenerationCustodyV1::publish(&mut custody, &self.identity.signed)?;
        self.require_observed(
            &OriginalRootInitialGenerationCustodyV1::read_original_operation(&custody)?,
        )?;
        Ok(custody)
    }

    pub(crate) fn read_original(&self) -> Result<NeuronGenerationInitialReadbackV1, AgentdError> {
        self.require_original(GrantObservation::RetainedPublication)?;
        let current = NeuronGenerationCurrentOwnerV1::open(
            Arc::clone(&self.root),
            &self.identity.scope,
        )?;
        let prepared = current.recover_initial_operation(
            &self.identity.recovery.operation_id,
            self.identity.recovery.intent_digest,
        )?;
        if prepared.final_use_binding() != &self.identity.binding {
            return Err(invalid("original protected generation binding changed"));
        }
        let readback = current.read_initial_operation(&prepared)?;
        self.require_observed(&readback)?;
        Ok(readback)
    }

    pub(crate) fn recover<W: AnchorWitnessStore>(
        &self,
        selected: AgentdSelectedGenerationV1,
        target: AgentdGenerationUpdateTargetV1<W>,
    ) -> Result<OriginalRootInitialGenerationCustodyV1<W>, AgentdError> {
        self.require_original(GrantObservation::RetainedPublication)?;
        let current = Arc::new(NeuronGenerationCurrentOwnerV1::open(
            Arc::clone(&self.root),
            &self.identity.scope,
        )?);
        let custody = OriginalRootInitialGenerationCustodyV1::recover_from_original_current(
            current,
            self.authorities.clone(),
            selected,
            target,
            self.recovery(),
        )?;
        self.require_observed(
            &OriginalRootInitialGenerationCustodyV1::read_original_operation(&custody)?,
        )?;
        Ok(custody)
    }

    pub(crate) fn require_observed(
        &self,
        readback: &NeuronGenerationInitialReadbackV1,
    ) -> Result<(), AgentdError> {
        if let NeuronGenerationInitialReadbackV1::Published(published) = readback
            && (published.intent_digest() != self.identity.recovery.intent_digest
                || published.signed_grant() != &self.identity.signed)
        {
            return Err(invalid("the actual publication differs from this original operation"));
        }
        self.require_original(GrantObservation::RetainedPublication)
    }

    fn recovery(&self) -> AgentdGenerationUpdateRecoveryV1 {
        AgentdGenerationUpdateRecoveryV1 {
            operation_id: self.identity.recovery.operation_id.clone(),
            intent_digest: self.identity.recovery.intent_digest,
        }
    }

    fn require_original(&self, purpose: GrantObservation) -> Result<(), AgentdError> {
        self.require_before()?;
        let lease = self.read_original_lease()?;
        let observe = || match purpose {
            GrantObservation::BeforePublication =>
                self.issuer.verify_original_signed_grant(&self.identity.signed, self.end),
            GrantObservation::RetainedPublication =>
                self.issuer.observe_original_signed_grant(&self.identity.signed, self.end),
        };
        let head = observe()?;
        if head.revoked_grant_ids.contains(&self.identity.signed.grant.grant_id) {
            return Err(invalid("the original issuer revoked this generation grant"));
        }
        let before = self.authorities.final_use.current_external_frontier().map_err(invalid)?;
        let consumer = self.authorities.final_use.revocation_head().map_err(invalid)?;
        let after = self.authorities.final_use.current_external_frontier().map_err(invalid)?;
        if before != after || consumer != head || observe()? != head
            || self.read_original_lease()? != lease
        {
            return Err(invalid("the original issuer, lease and existing consumer are not current"));
        }
        // The two heads are stable observations, not a shared Registry/consumer
        // transaction. Post-publication refusal leaves the same operation
        // uncertain; no grant, consumer head, nonce or preparation is restored.
        self.require_before()
    }

    fn read_original_lease(&self) -> Result<AuthorityLease, AgentdError> {
        let binding = &self.identity.binding;
        let expected = AuthorityLeaseBinding {
            principal_id: binding.subject_id.clone(),
            operation_class: "runtime.agentd.production_operation".into(),
            destination_id: binding.destination_id.clone(),
            scope_sha256: binding.scope_sha256,
            payload_sha256: binding.payload_sha256,
        };
        // This guard covers this observation only. Never hold the Registry
        // across Artifact/FinalUse operations or call it an atomic publication.
        let lease = self.issuer.with_live_lease(|lease| {
            if lease.binding != expected
                || self.clock.now_unix_ms().map_err(std::io::Error::other)?
                    >= lease.expires_at_unix_ms
            {
                return Err(std::io::Error::other("original generation lease differs or expired"));
            }
            Ok(lease.clone())
        })?;
        let actual = self.registry.verifier().read_lease(&lease.lease_id).map_err(invalid)?;
        if actual.as_ref().map(|record| &record.lease) != Some(&lease) {
            return Err(invalid("original generation lease changed across Root owners"));
        }
        if self.clock.now_unix_ms().map_err(invalid)? >= lease.expires_at_unix_ms {
            return Err(invalid("original generation lease expired during readback"));
        }
        self.require_before()?;
        Ok(lease)
    }

    fn require_before(&self) -> Result<(), AgentdError> {
        if unsafe { libc::getuid() } != 0 || unsafe { libc::geteuid() } != 0
            || Instant::now() >= self.end
        {
            return Err(invalid("original Root generation scope ended"));
        }
        Ok(())
    }
}

#[path = "authority_host_generation_input_loader.rs"]
mod input_loader;
pub use input_loader::RootHostInitialGenerationFilesV1;
pub(crate) use input_loader::LoadPurpose as OriginalGenerationLoadPurpose;
pub(crate) use input_loader::LoadedOriginalGeneration as OriginalLoadedGeneration;

#[path = "authority_host_generation_task_input_loader.rs"]
mod task_input_loader;
pub use task_input_loader::RootHostQ24TaskFilesV1;
pub(crate) use task_input_loader::TaskFilePurpose as OriginalTaskFilePurpose;
pub(crate) use task_input_loader::OriginalTaskClockStatus;

fn invalid(error: impl std::fmt::Display) -> AgentdError {
    AgentdError::Invalid(error.to_string())
}
