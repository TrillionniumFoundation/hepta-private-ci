//! The Root's independent B custodian. Input conversion cannot construct a
//! runtime, a role, a successful experiment or a publication capability.

#[path = "authority_host_q24_evaluation_source.rs"]
mod source;

#[path = "authority_host_q24_evaluation_files.rs"]
mod files;

#[path = "authority_host_q24_evaluation_admission.rs"]
mod admission;

#[path = "authority_host_q24_evaluation_protocol.rs"]
mod protocol;

#[path = "authority_host_q24_evaluation_record.rs"]
mod record;

#[path = "authority_host_q24_evaluation_deployment.rs"]
mod deployment;

#[path = "authority_host_q24_evaluation_provider.rs"]
mod provider;

#[path = "authority_host_q24_evaluation_outputs.rs"]
mod outputs;

#[path = "authority_host_q24_evaluation_execution.rs"]
mod execution;

#[path = "authority_host_q24_evaluation_host.rs"]
mod host;
pub(crate) use host::BoundRootIndependentBEvaluationV1;
pub(crate) use host::OriginalRootBEvaluationBorrowV1;
pub(crate) use host::OriginalRootIndependentBEvaluationFilesV1;
pub(crate) use host::PreparedRootIndependentBEvaluationV1;
pub use host::RootIndependentBEvaluationOfferV1;
pub(crate) use host::RootIndependentBEvaluationRuntimeV1;
pub(crate) use host::serve_optional_until;
