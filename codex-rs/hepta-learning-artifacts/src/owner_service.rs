#[path = "owner/durable_control.rs"]
mod durable_control;
#[path = "owner/durable_inputs.rs"]
mod durable_inputs;
#[path = "owner/durable_withdrawals.rs"]
mod durable_withdrawals;
#[path = "owner/operational_metrics.rs"]
mod operational_metrics;
#[path = "owner/operational_state.rs"]
mod operational_state;
#[path = "owner/publication_recovery.rs"]
mod publication_recovery;
#[path = "owner/request_identity.rs"]
mod request_identity;

include!("owner/service_preamble.rs");
include!("owner/service_open.rs");
include!("owner/service_access.rs");
include!("owner/service_drain.rs");
include!("owner/service_withdrawal.rs");
include!("owner/service_publish.rs");
include!("owner/service_publish_inner.rs");
include!("owner/service_errors.rs");

#[cfg(test)]
#[path = "owner_service_tests.rs"]
mod tests;

#[cfg(all(test, unix))]
#[path = "owner/withdrawal_service_tests.rs"]
mod withdrawal_tests;
