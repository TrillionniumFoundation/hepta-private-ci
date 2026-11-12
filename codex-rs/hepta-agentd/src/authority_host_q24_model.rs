//! Original Root reservation and a separately purpose-bound Q24 factory.
//! A profile is public data; only registered files and the live Root lane
//! construct a usable factory. No optimizer, signer or publication is granted.

use std::fs::File;
use std::io;
use std::os::fd::OwnedFd;
use std::path::Path;
use std::path::PathBuf;

use codex_hepta_contracts::HostAuthorityFrontierStore;
use codex_hepta_learning_artifacts::FrozenLearningScopeV2;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde::Serialize;

use super::HostAuthorityService;
use crate::HostAuthorityLearningProfileV1;
use crate::authority_host_config::HostAuthorityBindIdentity;
use crate::authority_host_config::HostAuthorityRegistration;
use crate::authority_host_config::HostAuthorityServiceConfig;

#[path = "authority_host_q24_model_profile.rs"]
mod profile;
pub(crate) use profile::FilePin;
pub use profile::HostAuthorityQ24ModelFactoryProfileV1;
pub(crate) use profile::LiveFactoryProfile;
pub(crate) use profile::Q24ModelFactoryBootstrap;
pub(crate) use profile::ReservedFactoryProfile;

#[path = "authority_host_q24_model_registration.rs"]
mod registration;
pub use registration::register_host_q24_model_factory;

#[path = "authority_host_q24_model_transport.rs"]
mod transport;
pub(crate) use transport::Command;
pub(crate) use transport::FactoryLease;
pub(crate) use transport::Reply;
pub(crate) use transport::Request;
pub(crate) use transport::Response;

#[path = "authority_host_q24_model_b_binding.rs"]
mod original_b;

pub(crate) const PURPOSE: &str = "runtime.learning.q24-model-proposal.factory.v1";
const OWNER: &str = "root-q24-model-proposal-factory-v1";
const DIRECTORY: &str = "q24-model-proposal-factory-v1";
pub(crate) const WITNESS_RECORDS: usize = 64;

/// Root0600 administration input. The witness lives in an explicitly pinned
/// separate protected directory; it is never inferred from the proposal file.
/// The host must preserve that original rollback domain across recovery.
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct HostAuthorityQ24ModelFactoryReservationV1 {
    pub schema_version: u32,
    pub witness_bind: HostAuthorityBindIdentity,
    pub witness_directory: PathBuf,
    pub local_policy_digest: String,
}

#[derive(Clone, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct FactoryRecord {
    pub(crate) profile: ReservedFactoryProfile,
    pub(crate) epoch: u64,
    pub(crate) material: Option<String>,
}

pub(crate) struct RegisteredQ24ModelFactory {
    pub(crate) profile: LiveFactoryProfile,
    learning: HostAuthorityLearningProfileV1,
    reservation: HostAuthorityQ24ModelFactoryReservationV1,
    store: HostAuthorityFrontierStore<FactoryRecord>,
    // Read-only descriptors remain at Root. Sole writable rights move once
    // into the offer; Root never retains a writable duplicate of either owner.
    journal_observer: File,
    witness_observer: File,
    files: Option<(File, File)>,
    original_b: Option<std::sync::Arc<crate::OriginalRootIndependentBEvaluationFilesV1>>,
    pub(crate) socket_path: PathBuf,
}

/// One sealed offer with actual owner files. Only the registered Root session
/// can construct it; sending consumes it, including on an uncertain send.
pub struct RootQ24ModelFactoryOfferV1 {
    pub(crate) bootstrap: File,
    pub(crate) journal: File,
    pub(crate) witness: File,
}
