//! A missing cached read never turns an ambiguous mutation into a retry.
use super::*;
use crate::daemon_protocol::SupervisordRequest;
use crate::daemon_protocol::SupervisordResponse;
use tokio::net::UnixListener;

#[tokio::test]
async fn original_client_types_only_the_exact_cached_observation_absence() -> anyhow::Result<()> {
    let agent =
        AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12").map_err(anyhow::Error::msg)?;
    let fence = SupervisordControlFence {
        agent_id: agent.clone(),
        supervisor_epoch: crate::SupervisorEpoch::parse("00000000-0000-4000-8000-000000000001")
            .map_err(anyhow::Error::msg)?,
        lifecycle: codex_hepta_fleet::AgentLifecycle::Stopped,
        lifecycle_generation: 1,
        spawn_generation: None,
        runtime_generation: None,
        current_release: None,
        previous_release: None,
        release_change_pending: false,
        state_digest: crate::ControlStateDigest::parse("0".repeat(64))
            .map_err(anyhow::Error::msg)?,
    };
    for (method, message, expected_read_absence) in [
        (
            SupervisordMethod::Health,
            crate::daemon_protocol::OBSERVATION_UNAVAILABLE_MESSAGE,
            true,
        ),
        (
            SupervisordMethod::Snapshot { agent_id: agent },
            crate::daemon_protocol::OBSERVATION_UNAVAILABLE_MESSAGE,
            true,
        ),
        (
            SupervisordMethod::Start {
                fence,
                release_id: "actual-release".parse()?,
            },
            crate::daemon_protocol::OBSERVATION_UNAVAILABLE_MESSAGE,
            false,
        ),
        (
            SupervisordMethod::Health,
            "Agent control state is unavailable; refresh before retry",
            false,
        ),
    ] {
        let directory = tempfile::tempdir()?;
        let socket = directory.path().join("observation.sock");
        let listener = UnixListener::bind(&socket)?;
        let expected_method = method.clone();
        let server = tokio::spawn(async move {
            let (stream, _) = listener.accept().await?;
            let (reader, mut writer) = tokio::io::split(stream);
            let mut frame = Vec::new();
            BufReader::new(reader).read_until(b'\n', &mut frame).await?;
            let request: SupervisordRequest = serde_json::from_slice(&frame)?;
            assert_eq!(request.method, expected_method);
            let response = SupervisordResponse {
                schema_version: SUPERVISORD_CONTROL_SCHEMA_VERSION,
                request_id: request.request_id,
                payload: SupervisordPayload::Error {
                    code: "control_state_unavailable".into(),
                    message: message.into(),
                    actual: None,
                },
            };
            let mut frame = serde_json::to_vec(&response)?;
            frame.push(b'\n');
            writer.write_all(&frame).await?;
            writer.shutdown().await?;
            anyhow::Ok(())
        });
        let result = SupervisordClient::new(socket)?.send(method).await;
        server.await??;
        if expected_read_absence {
            assert!(matches!(
                result,
                Err(SupervisorError::ObservationUnavailable)
            ));
        } else {
            assert!(matches!(result, Err(SupervisorError::Invalid(_))));
        }
    }
    Ok(())
}
