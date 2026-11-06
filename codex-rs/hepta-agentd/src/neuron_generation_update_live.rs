//! Live existing-authority checks for an installed generation owner.
//!
//! This module carries no issuer key and cannot issue a token. It retains the
//! concrete artifact writer and original consumed FinalUse authority, alongside
//! the independently protected Control current owner. The supplied clock keeps
//! the existing host time contract; its presence is no attestation claim.

use std::sync::Arc;
use std::sync::Mutex;

use codex_hepta_contracts::AuthorityClock;
use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_learning_artifacts::LearningArtifactOwnerService;
use codex_hepta_neuron::CellGenerationCurrentV1;
use codex_hepta_neuron::CellGenerationErrorV2;
use codex_hepta_neuron::CellGenerationOpenModeV1;
use codex_hepta_neuron::CellGenerationOwnerBindingV1;

use crate::AgentdError;
use crate::neuron_generation_current::NeuronGenerationCurrentOwnerV1;
use crate::neuron_generation_current::PublishedNeuronGenerationUpdateV1;
use crate::neuron_generation_update_selection::AgentdSelectedGenerationV1;

/// Existing concrete owners, supplied explicitly by the trusted host. There
/// is no default configuration, permissive callback or serialization path.
#[derive(Clone)]
pub struct AgentdGenerationUpdateAuthoritiesV1 {
    pub(crate) artifacts: Arc<Mutex<LearningArtifactOwnerService>>,
    pub(crate) final_use: Arc<FinalUseAuthority>,
    pub(crate) clock: Arc<dyn AuthorityClock>,
}

impl AgentdGenerationUpdateAuthoritiesV1 {
    pub fn new(
        artifacts: Arc<Mutex<LearningArtifactOwnerService>>,
        final_use: Arc<FinalUseAuthority>,
        clock: Arc<dyn AuthorityClock>,
    ) -> Result<Self, AgentdError> {
        clock.now_unix_ms().map_err(invalid)?;
        // Reject compatibility authorities with no independent rollback owner.
        // This is read-only and never claims a grant or repairs a frontier.
        final_use.current_external_frontier().map_err(invalid)?;
        Ok(Self {
            artifacts,
            final_use,
            clock,
        })
    }

    pub(crate) fn now(&self) -> Result<u64, AgentdError> {
        self.clock.now_unix_ms().map_err(invalid)
    }
}

pub(crate) struct LiveGenerationCurrent {
    current: Arc<NeuronGenerationCurrentOwnerV1>,
    authorities: AgentdGenerationUpdateAuthoritiesV1,
    selected: Mutex<AgentdSelectedGenerationV1>,
    publication: PublishedNeuronGenerationUpdateV1,
    expected: FinalUseBinding,
}

impl LiveGenerationCurrent {
    pub(crate) fn new(
        current: Arc<NeuronGenerationCurrentOwnerV1>,
        authorities: AgentdGenerationUpdateAuthoritiesV1,
        selected: AgentdSelectedGenerationV1,
        publication: PublishedNeuronGenerationUpdateV1,
        expected: FinalUseBinding,
    ) -> Result<Arc<Self>, AgentdError> {
        if publication.signed_grant().grant.binding != expected {
            return Err(invalid("published grant differs from the original operation"));
        }
        let guard = Arc::new(Self {
            current,
            authorities,
            selected: Mutex::new(selected),
            publication,
            expected,
        });
        guard
            .check_current(guard.publication.target())
            .map_err(invalid)?;
        Ok(guard)
    }

    fn check_live(&self) -> Result<(), CellGenerationErrorV2> {
        // Lock order is artifact owner -> selected payload -> FinalUse owner.
        // The update coordinator temporarily rebinds its terminal old journal
        // to the concrete Control floor before it holds this artifact lock.
        let artifacts = self
            .authorities
            .artifacts
            .lock()
            .map_err(|_| CellGenerationErrorV2::Unavailable)?;
        let mut selected = self
            .selected
            .lock()
            .map_err(|_| CellGenerationErrorV2::Unavailable)?;
        selected
            .revalidate(
                &artifacts,
                self.authorities
                    .clock
                    .now_unix_ms()
                    .map_err(|_| CellGenerationErrorV2::Unavailable)?,
            )
            .map_err(|_| CellGenerationErrorV2::Unavailable)?;
        self.authorities
            .final_use
            .verify_retained_use(
                self.publication.signed_grant(),
                &self.expected,
                self.publication.witness(),
            )
            .map_err(|_| CellGenerationErrorV2::Unavailable)?;
        Ok(())
    }
}

impl CellGenerationCurrentV1 for LiveGenerationCurrent {
    fn check_open(
        &self,
        binding: &CellGenerationOwnerBindingV1,
    ) -> Result<CellGenerationOpenModeV1, CellGenerationErrorV2> {
        self.check_current(binding)?;
        Ok(CellGenerationOpenModeV1::Active)
    }

    fn check_current(
        &self,
        binding: &CellGenerationOwnerBindingV1,
    ) -> Result<(), CellGenerationErrorV2> {
        if binding != self.publication.target() {
            return Err(CellGenerationErrorV2::InvalidBinding);
        }
        self.current.check_current(binding)?;
        self.check_live()?;
        // CURRENT/authority I/O cannot make an earlier Control sample fresh.
        self.current.check_current(binding)
    }
}

fn invalid(error: impl std::fmt::Display) -> AgentdError {
    AgentdError::Invalid(error.to_string())
}

