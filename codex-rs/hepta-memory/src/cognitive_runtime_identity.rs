//! Owner-local comparison of installed runtime capabilities, not database contents.
//! App Server delegates here so adding a cognitive mode does not add a new
//! domain-specific match branch to the execution spine.

use std::sync::Arc;

use super::CognitiveRuntime;

impl PartialEq for CognitiveRuntime {
    fn eq(&self, other: &Self) -> bool {
        match (self, other) {
            (Self::Available(left), Self::Available(right)) => Arc::ptr_eq(left, right),
            (
                Self::AvailableFederated {
                    store: left_store,
                    federation: left_federation,
                },
                Self::AvailableFederated {
                    store: right_store,
                    federation: right_federation,
                },
            ) => {
                Arc::ptr_eq(left_store, right_store)
                    && Arc::ptr_eq(left_federation, right_federation)
            }
            (
                Self::AvailableFederatedV2 {
                    store: left_store,
                    consumer_agent_id: left_consumer_agent_id,
                    owner_layouts: left_owner_layouts,
                    omitted_owner_candidates: left_omitted_owner_candidates,
                    host_profile: left_host_profile,
                },
                Self::AvailableFederatedV2 {
                    store: right_store,
                    consumer_agent_id: right_consumer_agent_id,
                    owner_layouts: right_owner_layouts,
                    omitted_owner_candidates: right_omitted_owner_candidates,
                    host_profile: right_host_profile,
                },
            ) => {
                Arc::ptr_eq(left_store, right_store)
                    && left_consumer_agent_id == right_consumer_agent_id
                    && left_owner_layouts.as_slice() == right_owner_layouts.as_slice()
                    && left_omitted_owner_candidates == right_omitted_owner_candidates
                    && left_host_profile == right_host_profile
            }
            (Self::Unavailable(left), Self::Unavailable(right)) => left == right,
            (Self::Absent, Self::Absent) => true,
            _ => false,
        }
    }
}

impl Eq for CognitiveRuntime {}

#[cfg(test)]
#[path = "cognitive_runtime_identity_tests.rs"]
mod tests;
