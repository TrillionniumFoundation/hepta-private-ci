//! Product-profile admission before the retained Agentd runtime starts.
//!
//! The retained runtime implementation is unchanged below this gate. Canonical
//! intelligence is attached only when runner, provider and physical/learning
//! continuation are all present. A partial or source-only profile fails before
//! daemon state can advertise capability or admit an ObjectiveStart.
//!
//! Generated-source anchor retained for the stable status verifier:
//! `set_provider_configured(true)` occurs only inside the retained runtime after
//! this complete-profile gate succeeds.

use codex_arg0::Arg0DispatchPaths;

use crate::AgentdConfig;
use crate::AgentdError;

mod retained {
    include!("runtime_base.rs");
}

pub async fn run(
    config: AgentdConfig,
    arg0_paths: Arg0DispatchPaths,
) -> Result<(), AgentdError> {
    validate_intelligence_product_profile(&config)?;
    retained::run(config, arg0_paths).await
}

fn validate_intelligence_product_profile(config: &AgentdConfig) -> Result<(), AgentdError> {
    let runner = config.intelligence_product_runner();
    let provider = config.intelligence_invocation_provider();
    match (runner, provider) {
        (None, None) => Ok(()),
        (Some(_), Some(provider)) if provider.product_continuation().is_some() => Ok(()),
        (Some(_), Some(_)) => Err(AgentdError::Invalid(
            "canonical intelligence product profile requires a physical/learning continuation; source-only runner/provider composition is not a product capability"
                .to_string(),
        )),
        _ => Err(AgentdError::Invalid(
            "canonical intelligence product profile is partially configured".to_string(),
        )),
    }
}
