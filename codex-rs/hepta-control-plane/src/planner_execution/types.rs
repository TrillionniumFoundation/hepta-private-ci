use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::Digest32;

use crate::GrantRequestSetV1;
use crate::GrantRequestV1;
use crate::PlannerBodyKindV1;
use crate::PlannerStoreError;
use crate::PlannerStoreV1;

const MAX_EXECUTION_REQUESTS: usize = 64;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum AuthorityDispositionV1 {
    Denied,
    Indeterminate,
}

impl AuthorityDispositionV1 {
    const fn tag(self) -> u8 {
        match self {
            Self::Denied => 0,
            Self::Indeterminate => 1,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SignedAuthorityObservationV1 {
    pub request_digest: Digest32,
    pub disposition: AuthorityDispositionV1,
    pub observation_digest: Digest32,
    pub issuer_identity_digest: Digest32,
    pub signature_digest: Digest32,
    pub canonical_body: Vec<u8>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct VerifiedExecutionGrantV1 {
    pub request_digest: Digest32,
    pub final_payload_digest: Digest32,
    pub grant_digest: Digest32,
    pub issuer_identity_digest: Digest32,
    pub signature_digest: Digest32,
    pub authority_epoch: u64,
    pub expires_at_micros: u64,
    pub canonical_body: Vec<u8>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum IndependentAuthorityDecisionV1 {
    Observation(SignedAuthorityObservationV1),
    Granted(VerifiedExecutionGrantV1),
}

pub trait IndependentPlannerAuthorityV1 {
    fn authorize(
        &mut self,
        request: &GrantRequestV1,
        request_digest: Digest32,
        now_micros: u64,
    ) -> Result<IndependentAuthorityDecisionV1, String>;
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum TerminalDispositionV1 {
    Succeeded,
    Failed,
    Indeterminate,
}

impl TerminalDispositionV1 {
    const fn tag(self) -> u8 {
        match self {
            Self::Succeeded => 0,
            Self::Failed => 1,
            Self::Indeterminate => 2,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SignedTerminalObservationV1 {
    pub request_digest: Digest32,
    pub grant_digest: Digest32,
    pub final_payload_digest: Digest32,
    pub disposition: TerminalDispositionV1,
    pub terminal_digest: Digest32,
    pub executor_identity_digest: Digest32,
    pub signature_digest: Digest32,
    pub canonical_body: Vec<u8>,
}

pub trait PlannerEffectExecutorV1 {
    fn execute(
        &mut self,
        request: &GrantRequestV1,
        grant: &VerifiedExecutionGrantV1,
        now_micros: u64,
    ) -> Result<SignedTerminalObservationV1, String>;
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum IndeterminateStageV1 {
    Authority,
    Effect,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PlannerIndeterminateV1 {
    pub stage: IndeterminateStageV1,
    pub request_digest: Digest32,
    pub grant_digest: Option<Digest32>,
    pub final_payload_digest: Digest32,
    pub observation_digest: Digest32,
    pub expires_at_micros: u64,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ReconciliationDispositionV1 {
    Succeeded,
    Failed,
    StillIndeterminate,
}

impl ReconciliationDispositionV1 {
    const fn tag(self) -> u8 {
        match self {
            Self::Succeeded => 0,
            Self::Failed => 1,
            Self::StillIndeterminate => 2,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SignedReconciliationReceiptV1 {
    pub request_digest: Digest32,
    pub observed_digest: Digest32,
    pub disposition: ReconciliationDispositionV1,
    pub reconciliation_digest: Digest32,
    pub reconciler_identity_digest: Digest32,
    pub signature_digest: Digest32,
    pub canonical_body: Vec<u8>,
}

pub trait PlannerTerminalReconcilerV1 {
    fn reconcile(
        &mut self,
        pending: &PlannerIndeterminateV1,
        now_micros: u64,
    ) -> Result<SignedReconciliationReceiptV1, String>;
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum PlannerRequestOutcomeV1 {
    Succeeded {
        request_digest: Digest32,
        grant_digest: Digest32,
        terminal_digest: Digest32,
    },
    Denied {
        request_digest: Digest32,
        terminal_digest: Digest32,
    },
    Failed {
        request_digest: Digest32,
        grant_digest: Digest32,
        terminal_digest: Digest32,
    },
    Indeterminate(PlannerIndeterminateV1),
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PlannerExecutionBatchV1 {
    pub plan_receipt_digest: Digest32,
    pub request_set_digest: Digest32,
    pub outcomes: Vec<PlannerRequestOutcomeV1>,
    pub complete: bool,
    pub partial_execution: bool,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum PlannerExecutionError {
    EmptyRequestSet,
    RequestLimitExceeded,
    RequestExpired,
    DecisionBodyMissing,
    AuthorityViolation,
    EmptyEvidence(&'static str),
    EvidenceDigestMismatch(&'static str),
    AuthorityBindingMismatch,
    GrantBindingMismatch,
    GrantExpired,
    TerminalBindingMismatch,
    ReconciliationBindingMismatch,
    PortFailure {
        stage: &'static str,
        message: String,
    },
    Store(PlannerStoreError),
}

impl fmt::Display for PlannerExecutionError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for PlannerExecutionError {}

impl From<PlannerStoreError> for PlannerExecutionError {
    fn from(error: PlannerStoreError) -> Self {
        Self::Store(error)
    }
}

pub struct PlannerExecutionCoordinatorV1<'a, A, E, R> {
    store: &'a mut PlannerStoreV1,
    authority: A,
    executor: E,
    reconciler: R,
}
