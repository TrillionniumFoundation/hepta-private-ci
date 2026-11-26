use anyhow::Result;

use super::*;

fn fence() -> Result<SupervisordControlFence> {
    Ok(serde_json::from_value(serde_json::json!({
        "agent_id": "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12",
        "supervisor_epoch": "018f4f72-5f8f-4cc1-8f55-df9fb3aa2c12",
        "lifecycle": "stopped", "lifecycle_generation": 7,
        "spawn_generation": null, "runtime_generation": null,
        "current_release": "agentd-v1", "previous_release": null,
        "release_change_pending": false, "state_digest": "a".repeat(64)
    }))?)
}

#[test]
fn controller_protocol_start_cannot_choose_or_admit_a_release() -> Result<()> {
    let selected = fence()?;
    let request = SupervisorControllerRequest::new(
        41,
        SupervisorControllerMethod::Start {
            fence: selected.clone(),
        },
    )
    .owner_request()
    .expect("current admitted release");
    assert_eq!(
        request.method,
        SupervisordMethod::Start {
            fence: selected.clone(),
            release_id: selected.current_release.expect("current release")
        }
    );
    for extra in ["release_id", "gateway_pid", "uid", "manifest"] {
        let mut value = serde_json::to_value(SupervisorControllerRequest::new(
            42,
            SupervisorControllerMethod::Start { fence: fence()? },
        ))?;
        value["method"][extra] = serde_json::json!("foreign");
        assert!(serde_json::from_value::<SupervisorControllerRequest>(value).is_err());
    }
    for kind in [
        "upgrade",
        "signed_upgrade",
        "kill",
        "register_agent",
        "allow_installed_release",
        "health",
    ] {
        assert!(
            serde_json::from_value::<SupervisorControllerRequest>(serde_json::json!({
                "schema_version": 1, "request_id": 43, "method": {"type": kind}
            }))
            .is_err()
        );
    }
    Ok(())
}

#[test]
fn controller_protocol_requires_original_fence_receipt_and_schema() -> Result<()> {
    let mut selected = fence()?;
    selected.current_release = None;
    assert!(
        SupervisorControllerRequest::new(44, SupervisorControllerMethod::Start { fence: selected })
            .owner_request()
            .is_err()
    );
    let mut selected = fence()?;
    selected.release_change_pending = true;
    assert!(
        SupervisorControllerRequest::new(45, SupervisorControllerMethod::Start { fence: selected })
            .owner_request()
            .is_err()
    );
    assert!(
        SupervisorControllerRequest::new(0, SupervisorControllerMethod::Stop { fence: fence()? })
            .owner_request()
            .is_err()
    );
    assert!(
        SupervisorControllerRequest::new(
            46,
            SupervisorControllerMethod::Receipt {
                agent_id: fence()?.agent_id,
                mutation_request_id: 0
            }
        )
        .owner_request()
        .is_err()
    );
    let mut request = SupervisorControllerRequest::new(
        47,
        SupervisorControllerMethod::Restart { fence: fence()? },
    );
    request.schema_version = 2;
    assert!(request.owner_request().is_err());
    Ok(())
}
