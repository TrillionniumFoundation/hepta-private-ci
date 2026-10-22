#![forbid(unsafe_code)]

pub use codex_hepta_contracts::GovernanceMode;

mod admission;
mod authorization;
mod binding;
mod install;
mod provider_binding;
mod provider_error;
mod provider_lease;
mod provider_policy;
mod provider_request_host;
mod state;
mod terminal;

pub use install::install;
pub use install::install_with_mode;
pub use install::install_with_provider_request_enforcement;
pub use provider_request_host::ProviderRequestEnforcementHost;
pub use state::GovernanceState;

#[cfg(test)]
use binding::handler_outcome;
#[cfg(test)]
use install::HeptaGovernanceExtension;
#[cfg(test)]
use install::governance_state;

#[cfg(test)]
#[path = "tests.rs"]
mod tests;

#[cfg(test)]
#[path = "provider_policy_tests.rs"]
mod provider_policy_tests;
