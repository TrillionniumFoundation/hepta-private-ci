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
