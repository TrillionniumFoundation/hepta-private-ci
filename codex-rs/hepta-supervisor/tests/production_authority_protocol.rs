#![cfg(feature = "production-authority")]
#![allow(clippy::expect_used)]

use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_fleet::ReleaseId;
use codex_hepta_supervisor::ControlStateDigest;
use codex_hepta_supervisor::SupervisorEpoch;
use codex_hepta_supervisor::SupervisordControlFence;
use codex_hepta_supervisor::SupervisordMethod;
use codex_hepta_supervisor::SupervisordRequest;
use codex_hepta_supervisor::SupervisordRequestValidationError;

const AGENT_ID: &str = "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12";
const EPOCH: &str = "018f4f72-5f8f-4cc1-8f55-df9fb3aa2c12";
const DIGEST: &str = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";

fn fence() -> SupervisordControlFence {
    SupervisordControlFence {
        agent_id: AgentId::parse(AGENT_ID).expect("agent id"),
        supervisor_epoch: SupervisorEpoch::parse(EPOCH).expect("supervisor epoch"),
        lifecycle: AgentLifecycle::Running,
        lifecycle_generation: 7,
        spawn_generation: Some(5),
        runtime_generation: Some(7),
        current_release: Some(ReleaseId::parse("agentd-v1").expect("release")),
        previous_release: Some(ReleaseId::parse("agentd-v0").expect("release")),
        release_change_pending: false,
        state_digest: ControlStateDigest::parse(DIGEST).expect("state digest"),
    }
}

#[test]
fn production_build_rejects_unsigned_release_change_requests() {
    let upgrade = SupervisordRequest::new(
        1,
        SupervisordMethod::Upgrade {
            fence: fence(),
            release_id: ReleaseId::parse("agentd-v2").expect("release"),
        },
    );
    assert_eq!(
        upgrade.validate(),
        Err(SupervisordRequestValidationError::InvalidRequest)
    );

    let rollback = SupervisordRequest::new(2, SupervisordMethod::Rollback { fence: fence() });
    assert_eq!(
        rollback.validate(),
        Err(SupervisordRequestValidationError::InvalidRequest)
    );
}
