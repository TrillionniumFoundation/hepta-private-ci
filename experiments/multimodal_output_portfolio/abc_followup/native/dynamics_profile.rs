//! Analytically bounded homeostasis profiles; all acceptance gates stay intact.
use codex_hepta_neuron::{NeuronRuntimeConfigV1,SparseConfig};
use serde::Deserialize;

#[cfg(test)]
#[path="dynamics_profile_tests.rs"]
mod tests;

const Q:i64=1<<24;

#[derive(Clone,Copy,Debug,Default,Deserialize)]
#[serde(rename_all="snake_case")]
pub enum DynamicsProfile {
    #[default]
    Legacy,
    BoundedBalanced,
}

#[derive(Clone,Copy)]
pub enum DriveDomain {
    // Initial boundedcontext plus exactly two .25*tanh shared-state updates.
    HistoricalSemanticPrefix,
    // First8 tanh pixel-encoder and tanh token-embedding coordinates per slot.
    FutureEmittedState,
}

pub fn bound(domain:DriveDomain)->i64 {
    match domain {DriveDomain::HistoricalSemanticPrefix=>3*Q/2,DriveDomain::FutureEmittedState=>Q}
}

pub fn bind(native:&mut SparseConfig,config:&mut NeuronRuntimeConfigV1,
            profile:DynamicsProfile,domain:DriveDomain)->Result<(),Box<dyn std::error::Error>> {
    if matches!(profile,DynamicsProfile::BoundedBalanced) {
        if native.temporal_decay_q24!=Q/2 || native.threshold_rate_q24!=Q/8 || native.top_k!=4 {
            return Err("Analytic dynamics premise changed".into());
        }
        // |h_t| <= B/(1-.5)=2B; addQ margin for positive competition.
        let range=2*bound(domain)+Q;
        native.threshold_min_q24=-range;native.threshold_max_q24=range;
        native.target_activity_q24=Q*native.top_k as i64/native.width as i64;
    }
    config.native_config_digest=native.digest()?;
    Ok(())
}
