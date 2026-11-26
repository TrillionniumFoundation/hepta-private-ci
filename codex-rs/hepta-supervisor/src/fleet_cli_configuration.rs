use std::time::Duration;

use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::ReleaseId;
use codex_hepta_paths::HeptaFleetRoot;
use codex_hepta_supervisor::SupervisorError;
use codex_hepta_supervisor::SupervisordClient;
use codex_hepta_supervisor::SupervisordControlFence;
use serde_json::Value;
use serde_json::json;
use tokio::time::Instant;

pub(super) async fn allow(
    root: &HeptaFleetRoot,
    client: &SupervisordClient,
    agent: AgentId,
    release: ReleaseId,
) -> anyhow::Result<Value> {
    let deadline = Instant::now() + Duration::from_secs(10);
    let mut rejection_reported = false;
    let outcome = loop {
        let fence = configuration_fence(client, &agent, deadline).await?;
        let outcome = tokio::time::timeout_at(
            deadline,
            client.allow_installed_release(fence, release.clone()),
        )
        .await
        .unwrap_or_else(|_| {
            Err(SupervisorError::Invalid(
                "configuration response deadline expired".into(),
            ))
        });
        match outcome {
            Err(
                error @ (SupervisorError::NotAdmittedBusy
                | SupervisorError::ConfigurationNotReady(_)),
            ) => {
                if !rejection_reported {
                    eprintln!("{error}");
                    rejection_reported = true;
                }
                anyhow::ensure!(
                    Instant::now() < deadline,
                    "configuration remained unadmitted"
                );
                tokio::time::sleep(Duration::from_millis(25)).await;
            }
            result => break result,
        }
    };
    match outcome {
        Ok(snapshot) => Ok(serde_json::to_value(snapshot)?),
        Err(error) => {
            let deadline = Instant::now() + Duration::from_secs(10);
            loop {
                // An uncertain configuration response is resolved by checking
                // its immutable allowance and the current owner projection.
                if FleetRegistry::open_existing(root.clone())
                    .and_then(|registry| registry.resolve_release(&agent, &release))
                    .is_ok()
                    && let Ok(Ok(snapshot)) =
                        tokio::time::timeout_at(deadline, client.snapshot(agent.clone())).await
                {
                    return Ok(serde_json::to_value(snapshot)?);
                }
                if Instant::now() >= deadline {
                    return Err(error.into());
                }
                tokio::time::sleep(Duration::from_millis(25)).await;
            }
        }
    }
}

pub(super) async fn retire(
    root: &HeptaFleetRoot,
    client: &SupervisordClient,
    agent: AgentId,
) -> anyhow::Result<Value> {
    let deadline = Instant::now() + Duration::from_secs(10);
    let mut rejection_reported = false;
    let outcome = loop {
        let fence = configuration_fence(client, &agent, deadline).await?;
        let outcome = tokio::time::timeout_at(deadline, client.retire_agent(fence))
            .await
            .unwrap_or_else(|_| {
                Err(SupervisorError::Invalid(
                    "retirement response deadline expired".into(),
                ))
            });
        match outcome {
            Err(
                error @ (SupervisorError::NotAdmittedBusy
                | SupervisorError::ConfigurationNotReady(_)),
            ) => {
                if !rejection_reported {
                    eprintln!("{error}");
                    rejection_reported = true;
                }
                anyhow::ensure!(Instant::now() < deadline, "retirement remained unadmitted");
                tokio::time::sleep(Duration::from_millis(25)).await;
            }
            result => break result,
        }
    };
    let archived = match outcome {
        Ok(archived) => archived,
        Err(error) => {
            let deadline = Instant::now() + Duration::from_secs(10);
            loop {
                // The archive's validated Agent identity is the durable result;
                // never repeat the rename after a lost configuration response.
                let durable = FleetRegistry::open_existing(root.clone())
                    .and_then(|registry| registry.retired_agent_path(&agent));
                if let Ok(Some(archive)) = durable
                    && let Ok(Ok(Some(owner_archive))) = tokio::time::timeout_at(
                        deadline,
                        client.retired_agent_status(agent.clone()),
                    )
                    .await
                {
                    anyhow::ensure!(
                        owner_archive == archive,
                        "retirement owner/archive mismatch"
                    );
                    break archive;
                }
                if Instant::now() >= deadline {
                    return Err(error.into());
                }
                tokio::time::sleep(Duration::from_millis(25)).await;
            }
        }
    };
    Ok(json!({"agentId": agent, "archivedRoot": archived}))
}

async fn configuration_fence(
    client: &SupervisordClient,
    agent: &AgentId,
    deadline: Instant,
) -> anyhow::Result<SupervisordControlFence> {
    loop {
        match tokio::time::timeout_at(deadline, client.snapshot(agent.clone())).await? {
            Err(error) => {
                if Instant::now() >= deadline {
                    return Err(error.into());
                }
                tokio::time::sleep(Duration::from_millis(25)).await;
            }
            outcome => return Ok(outcome?.control_fence),
        }
    }
}
