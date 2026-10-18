use super::*;
use codex_hepta_supervisor::SUPERVISORD_CONTROL_SCHEMA_VERSION;
use codex_hepta_supervisor::SupervisordMethod;
use codex_hepta_supervisor::SupervisordPayload;
use codex_hepta_supervisor::SupervisordRequest;
use codex_hepta_supervisor::SupervisordResponse;
use tokio::io::AsyncReadExt;
use tokio::io::AsyncWriteExt;
use tokio::net::UnixListener;

fn fixture() -> anyhow::Result<(SupervisordHealth, SupervisordAgentStatus, NativeChatBinding)> {
    let fence = serde_json::json!({
        "agent_id":"00000000-0000-4000-8000-000000000001",
        "supervisor_epoch":"00000000-0000-4000-8000-000000000002",
        "lifecycle":"running", "lifecycle_generation":11,
        "spawn_generation":10,"runtime_generation":11,
        "current_release":"linux-original-agent", "previous_release":null,
        "release_change_pending":false,"state_digest":"a".repeat(64)
    });
    let health = serde_json::from_value(serde_json::json!({
        "ready":true,"supervisor_epoch":fence["supervisor_epoch"],
        "process_id":std::process::id(),"registered_agents":1,"observed_faults":0
    }))?;
    let agent = serde_json::from_value(serde_json::json!({
        "agent_id":fence["agent_id"],"lifecycle":"running","lifecycle_generation":11,
        "active":true,"healthy":true,"process_id":101,
        "spawn_generation":10,"runtime_generation":11,
        "current_release":"linux-original-agent","previous_release":null,
        "release_change_pending":false,"control_fence":fence,
        "matrix":{"configured":false,"active":false,"healthy":false,"degraded":false,
            "process_id":null,"attached_agent_generation":null,"binding_revision":null,
            "restart_attempt":0,"last_error":null}
    }))?;
    Ok((
        health,
        agent,
        NativeChatBinding {
            agent_id: "00000000-0000-4000-8000-000000000001".into(),
            supervisor_process_id: std::process::id(),
            agent_process_id: 101,
            control_fence: fence,
        },
    ))
}

#[tokio::test]
async fn original_owner_reads_fence_before_and_after_real_snapshot() -> anyhow::Result<()> {
    let (health, agent, binding) = fixture()?;
    for replace_owner in [false, true] {
        let directory = tempfile::tempdir()?;
        let socket = directory.path().join("ctl");
        let listener = UnixListener::bind(&socket)?;
        let health = health.clone();
        let observed = agent.clone();
        let task = tokio::spawn(async move {
            for index in 0..3 {
                let (mut stream, _) = listener.accept().await?;
                let mut bytes = Vec::new();
                stream.read_to_end(&mut bytes).await?;
                let request: SupervisordRequest = serde_json::from_slice(&bytes)?;
                let payload = match request.method {
                    SupervisordMethod::Health => {
                        let mut current = health.clone();
                        if replace_owner && index == 2 {
                            current.process_id += 1;
                        }
                        SupervisordPayload::Health(current)
                    }
                    SupervisordMethod::Snapshot { agent_id } => {
                        assert_eq!(agent_id, observed.agent_id);
                        SupervisordPayload::Agent(observed.clone())
                    }
                    _ => anyhow::bail!("read-only protocol expected"),
                };
                let mut bytes = serde_json::to_vec(&SupervisordResponse {
                    schema_version: SUPERVISORD_CONTROL_SCHEMA_VERSION,
                    request_id: request.request_id,
                    payload,
                })?;
                bytes.push(b'\n');
                stream.write_all(&bytes).await?;
            }
            anyhow::Ok(())
        });
        use std::os::unix::fs::MetadataExt;
        let client =
            SupervisordClient::new(socket)?.with_owner_uid(std::fs::metadata("/proc/self")?.uid());
        assert_eq!(check(&client, &binding).await.is_ok(), !replace_owner);
        task.await??;
    }
    Ok(())
}

#[test]
fn changed_pid_spawn_release_or_full_fence_cannot_rebind_chat() -> anyhow::Result<()> {
    let (health, agent, binding) = fixture()?;
    let expected: SupervisordControlFence = serde_json::from_value(binding.control_fence.clone())?;
    validate(&health, &agent, &health, &binding, &expected)?;
    for change in 0..5 {
        let mut current = agent.clone();
        match change {
            0 => current.process_id = Some(102),
            1 => current.spawn_generation = Some(11),
            2 => current.current_release = None,
            3 => current.control_fence.lifecycle_generation += 1,
            4 => current.healthy = false,
            _ => unreachable!(),
        }
        assert!(validate(&health, &current, &health, &binding, &expected).is_err());
    }
    Ok(())
}
