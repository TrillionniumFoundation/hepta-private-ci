//! Live existing-authority checks for an installed generation owner.
//!
//! This module carries no issuer key and cannot issue a token. It retains the
//! original Artifact writer or the actual Root Initial client's concrete read
//! view, and the original consumed FinalUse authority. The protected Control
//! current remains independent. A supplied clock alone is no attestation claim.

use std::sync::Arc;
use std::sync::Mutex;

use codex_hepta_contracts::AuthorityClock;
use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_contracts::VerifiedUseTokenWitnessV1;
use codex_hepta_learning_artifacts::LearningArtifactOwnerService;
use codex_hepta_neuron::CellGenerationCurrentV1;
use codex_hepta_neuron::CellGenerationErrorV2;
use codex_hepta_neuron::CellGenerationOpenModeV1;
use codex_hepta_neuron::CellGenerationOwnerBindingV1;

use crate::AgentdError;
use crate::neuron_generation_current::NeuronGenerationCurrentOwnerV1;
use crate::neuron_generation_current::PublishedNeuronGenerationInitialV1;
use crate::neuron_generation_current::PublishedNeuronGenerationUpdateV1;
use crate::neuron_generation_update_selection::AgentdSelectedGenerationV1;

#[path = "neuron_generation_artifact_readback.rs"]
pub(crate) mod artifacts;
use artifacts::GenerationArtifactOwnerV1;

/// Existing concrete owners. The public constructor retains the original
/// writer; only the actual Root Initial client can create its read-only branch.
/// There is no default, permissive callback or serialization path.
#[derive(Clone)]
pub struct AgentdGenerationUpdateAuthoritiesV1 {
    pub(crate) artifacts: GenerationArtifactOwnerV1,
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
            artifacts: GenerationArtifactOwnerV1::Writer(artifacts),
            final_use,
            clock,
        })
    }

    pub(crate) fn now(&self) -> Result<u64, AgentdError> {
        self.clock.now_unix_ms().map_err(invalid)
    }
}

enum RetainedPublication {
    Update(PublishedNeuronGenerationUpdateV1),
    Initial(PublishedNeuronGenerationInitialV1),
}

impl RetainedPublication {
    fn target(&self) -> &CellGenerationOwnerBindingV1 {
        match self {
            Self::Update(record) => record.target(),
            Self::Initial(record) => record.target(),
        }
    }

    fn signed_grant(&self) -> &SignedFinalUseGrant {
        match self {
            Self::Update(record) => record.signed_grant(),
            Self::Initial(record) => record.signed_grant(),
        }
    }

    fn witness(&self) -> &VerifiedUseTokenWitnessV1 {
        match self {
            Self::Update(record) => record.witness(),
            Self::Initial(record) => record.witness(),
        }
    }
}

pub(crate) struct LiveGenerationCurrent {
    current: Arc<NeuronGenerationCurrentOwnerV1>,
    authorities: AgentdGenerationUpdateAuthoritiesV1,
    selected: Mutex<AgentdSelectedGenerationV1>,
    publication: RetainedPublication,
    expected: FinalUseBinding,
}

impl LiveGenerationCurrent {
    #[cfg(target_os = "linux")]
    pub(crate) fn original_historical_successor_current(
        &self,
        original_a: &crate::root_historical_task_read_client::OriginalHistoricalTaskReadReceiptV1,
    ) -> Result<Arc<NeuronGenerationCurrentOwnerV1>, AgentdError> {
        if !matches!(&self.publication, RetainedPublication::Update(_)) {
            return Err(invalid("original published successor required"));
        }
        self.check_current(self.publication.target())
            .map_err(invalid)?;
        NeuronGenerationCurrentOwnerV1::require_original_root_historical_receipt(
            &self.current,
            original_a,
        )?;
        self.check_current(self.publication.target())
            .map_err(invalid)?;
        Ok(Arc::clone(&self.current))
    }

    #[cfg(target_os = "linux")]
    pub(crate) fn original_initial_source_current(
        &self,
        session: &crate::AgentdRootAuthoritySession,
        identity: &crate::AgentdIdentity,
    ) -> Result<Arc<NeuronGenerationCurrentOwnerV1>, AgentdError> {
        if !matches!(&self.publication, RetainedPublication::Initial(_)) {
            return Err(invalid(
                "source capture requires original Initial publication",
            ));
        }
        self.check_current(self.publication.target())
            .map_err(invalid)?;
        self.current
            .require_original_initial_source_session(session, identity)?;
        self.check_current(self.publication.target())
            .map_err(invalid)?;
        Ok(Arc::clone(&self.current))
    }

    #[cfg(target_os = "linux")]
    pub(crate) fn read_initial_learning_trust(
        &self,
        session: &crate::AgentdRootAuthoritySession,
        identity: &crate::AgentdIdentity,
    ) -> Result<crate::OriginalRootInitialLearningTrustV1, AgentdError> {
        if !matches!(&self.publication, RetainedPublication::Initial(_)) {
            return Err(invalid("original Initial learning trust required"));
        }
        self.check_current(self.publication.target())
            .map_err(invalid)?;
        let trust = self
            .current
            .read_root_initial_learning_trust(session, identity)?;
        self.check_current(self.publication.target())
            .map_err(invalid)?;
        Ok(trust)
    }

    pub(crate) fn new(
        current: Arc<NeuronGenerationCurrentOwnerV1>,
        authorities: AgentdGenerationUpdateAuthoritiesV1,
        selected: AgentdSelectedGenerationV1,
        publication: PublishedNeuronGenerationUpdateV1,
        expected: FinalUseBinding,
    ) -> Result<Arc<Self>, AgentdError> {
        authorities.artifacts.writer()?;
        Self::from_publication(
            current,
            authorities,
            selected,
            RetainedPublication::Update(publication),
            expected,
        )
    }

    pub(crate) fn new_initial(
        current: Arc<NeuronGenerationCurrentOwnerV1>,
        authorities: AgentdGenerationUpdateAuthoritiesV1,
        selected: AgentdSelectedGenerationV1,
        publication: PublishedNeuronGenerationInitialV1,
        expected: FinalUseBinding,
    ) -> Result<Arc<Self>, AgentdError> {
        Self::from_publication(
            current,
            authorities,
            selected,
            RetainedPublication::Initial(publication),
            expected,
        )
    }

    fn from_publication(
        current: Arc<NeuronGenerationCurrentOwnerV1>,
        authorities: AgentdGenerationUpdateAuthoritiesV1,
        selected: AgentdSelectedGenerationV1,
        publication: RetainedPublication,
        expected: FinalUseBinding,
    ) -> Result<Arc<Self>, AgentdError> {
        if publication.signed_grant().grant.binding != expected {
            return Err(invalid(
                "published grant differs from the original operation",
            ));
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
        let artifacts = crate::q24_owner_watch!("live.artifact_mutex", self
            .authorities
            .artifacts
            .lock_initial(), |e: &crate::AgentdError| match e {crate::AgentdError::Invalid(s) if s=="Unavailable"=>"invalid_unavailable",crate::AgentdError::Invalid(_)=>"invalid_other",crate::AgentdError::Io(_)=>"io",crate::AgentdError::Json(_)=>"json",_=>"other_category"})
            .map_err(|_| CellGenerationErrorV2::Unavailable)?;
        let mut selected = crate::q24_owner_watch!("live.selected_mutex", self
            .selected
            .lock())
            .map_err(|_| CellGenerationErrorV2::Unavailable)?;
        crate::q24_owner_watch!("live.revalidate_and_clock", artifacts
            .readback()
            .revalidate_owner(
                &self.current,
                &mut selected,
                crate::q24_owner_watch!("live.clock", self.authorities
                    .clock
                    .now_unix_ms())
                    .map_err(|_| CellGenerationErrorV2::Unavailable)?,
            ), |e: &crate::AgentdError| match e {crate::AgentdError::Invalid(s) if s=="Unavailable"=>"invalid_unavailable",crate::AgentdError::Invalid(_)=>"invalid_other",crate::AgentdError::Io(_)=>"io",crate::AgentdError::Json(_)=>"json",_=>"other_category"})
            .map_err(|_| CellGenerationErrorV2::Unavailable)?;
        crate::q24_owner_watch!("live.final_use", self.authorities
            .final_use
            .verify_retained_use(
                self.publication.signed_grant(),
                &self.expected,
                self.publication.witness(),
            ), |q24_err: &codex_hepta_contracts::FinalUseError| match q24_err {codex_hepta_contracts::FinalUseError::InvalidGrant=>"InvalidGrant",codex_hepta_contracts::FinalUseError::InvalidTrust=>"InvalidTrust",codex_hepta_contracts::FinalUseError::AntiRollbackViolation=>"AntiRollbackViolation",codex_hepta_contracts::FinalUseError::InvalidSignature=>"InvalidSignature",codex_hepta_contracts::FinalUseError::BindingMismatch=>"BindingMismatch",codex_hepta_contracts::FinalUseError::EpochMismatch=>"EpochMismatch",codex_hepta_contracts::FinalUseError::StaleRevocationHead=>"StaleRevocationHead",codex_hepta_contracts::FinalUseError::Revoked=>"Revoked",codex_hepta_contracts::FinalUseError::NotYetValid=>"NotYetValid",codex_hepta_contracts::FinalUseError::Expired=>"Expired",codex_hepta_contracts::FinalUseError::AlreadyClaimed=>"AlreadyClaimed",codex_hepta_contracts::FinalUseError::CapacityExceeded=>"CapacityExceeded",codex_hepta_contracts::FinalUseError::DispatchInProgress=>"DispatchInProgress",codex_hepta_contracts::FinalUseError::Unavailable=>"Unavailable",codex_hepta_contracts::FinalUseError::UnsafeStateDirectory=>"UnsafeStateDirectory",codex_hepta_contracts::FinalUseError::StateLocked=>"StateLocked", _=>"other_category"})
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
        crate::q24_owner_watch!("live.control", self.current.check_current(binding), |q24_err: &codex_hepta_neuron::CellGenerationErrorV2| match q24_err {codex_hepta_neuron::CellGenerationErrorV2::Unavailable=>"Unavailable",codex_hepta_neuron::CellGenerationErrorV2::InvalidBinding=>"InvalidBinding",codex_hepta_neuron::CellGenerationErrorV2::Pending=>"Pending",codex_hepta_neuron::CellGenerationErrorV2::Capacity=>"Capacity", _=>"other_category"})?;
        crate::q24_owner_watch!("live.authorities", self.check_live(), |q24_err: &codex_hepta_neuron::CellGenerationErrorV2| match q24_err {codex_hepta_neuron::CellGenerationErrorV2::Unavailable=>"Unavailable",codex_hepta_neuron::CellGenerationErrorV2::InvalidBinding=>"InvalidBinding",codex_hepta_neuron::CellGenerationErrorV2::Pending=>"Pending",codex_hepta_neuron::CellGenerationErrorV2::Capacity=>"Capacity", _=>"other_category"})?;
        // CURRENT/authority I/O cannot make an earlier Control sample fresh.
        crate::q24_owner_watch!("live.control", self.current.check_current(binding), |q24_err: &codex_hepta_neuron::CellGenerationErrorV2| match q24_err {codex_hepta_neuron::CellGenerationErrorV2::Unavailable=>"Unavailable",codex_hepta_neuron::CellGenerationErrorV2::InvalidBinding=>"InvalidBinding",codex_hepta_neuron::CellGenerationErrorV2::Pending=>"Pending",codex_hepta_neuron::CellGenerationErrorV2::Capacity=>"Capacity", _=>"other_category"})
    }
}

fn invalid(error: impl std::fmt::Display) -> AgentdError {
    AgentdError::Invalid(error.to_string())
}
