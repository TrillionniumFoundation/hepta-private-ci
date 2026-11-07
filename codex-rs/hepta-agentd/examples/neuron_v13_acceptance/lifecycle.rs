use std::fs::File;
use std::fs::OpenOptions;
use std::future::Future;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::OpenOptionsExt;
use std::path::Path;
use std::time::Duration;

use anyhow::Context;
use anyhow::Result;
use anyhow::ensure;
use codex_arg0::Arg0DispatchPaths;
use codex_hepta_agentd::AgentdClient;
use codex_hepta_agentd::AgentdConfig;
use codex_hepta_agentd::AgentdError;
use codex_hepta_agentd::AgentdIdentity;
use codex_hepta_agentd::V13GenerationOwnerFilesV1;
use codex_hepta_agentd::V13GenerationOwnerModeV1;
use codex_hepta_agentd::run_with_shutdown;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_fleet::FleetRegistry;
use tokio::time::sleep;
use tokio::time::timeout;
use tokio_util::sync::CancellationToken;

pub(super) enum ShutdownExpectation {
    Drained,
    UnacknowledgedOutput,
}

pub(super) struct Session<T> {
    pub value: T,
    pub shutdown_error: Option<String>,
}

pub(super) fn owner_files(
    root: &Path,
    mode: V13GenerationOwnerModeV1,
    retained: &[File],
) -> Result<V13GenerationOwnerFilesV1> {
    let open = |name: &str, append: bool| {
        let mut options = OpenOptions::new();
        options
            .read(true)
            .write(true)
            .append(append)
            .custom_flags(libc::O_NOFOLLOW | libc::O_NONBLOCK);
        if matches!(mode, V13GenerationOwnerModeV1::InitializeEmpty) {
            options.create_new(true).mode(0o600);
        }
        options.open(root.join(name))
    };
    let files = V13GenerationOwnerFilesV1 {
        journal: open("cell.journal", /*append*/ false)?,
        witness: open("independent.witness", /*append*/ false)?,
        control: open("control.journal", /*append*/ true)?,
    };
    for owner in [&files.journal, &files.witness, &files.control] {
        let actual = owner.metadata()?;
        for input in retained {
            let input = input.metadata()?;
            ensure!(
                (actual.dev(), actual.ino()) != (input.dev(), input.ino()),
                "owner aliases the pinned descriptor or historical publication"
            );
        }
    }
    if matches!(mode, V13GenerationOwnerModeV1::InitializeEmpty) {
        File::open(root)?.sync_all()?;
    }
    Ok(files)
}

pub(super) fn host_config(identity: &AgentdIdentity, spawn: u64) -> Result<AgentdConfig> {
    Ok(AgentdConfig::load(
        identity.fleet_root.clone(),
        identity.agent_id.clone(),
        spawn,
        identity.home_root.clone(),
        identity.run_root.clone(),
        identity.home_root.clone(),
        identity.workspace.clone(),
    )?)
}

/// Both sessions run the original App Server and Fleet gates. Only the first
/// intentionally leaves a verified outbox outstanding; its original bounded
/// drain error is retained, never relabelled as a successful retirement.
pub(super) async fn ordinary_session<T, F, Fut>(
    config: AgentdConfig,
    registry: &FleetRegistry,
    expected: ShutdownExpectation,
    work: F,
) -> Result<Session<T>>
where
    F: FnOnce() -> Fut,
    Fut: Future<Output = Result<T>>,
{
    let identity = config.identity().clone();
    let client = AgentdClient::new(
        identity.control_socket.clone(),
        identity.agent_id.clone(),
        identity.spawn_generation,
    )?;
    let stop = CancellationToken::new();
    let shutdown = stop.clone();
    let runtime = run_with_shutdown(config, Arg0DispatchPaths::default(), async move {
        shutdown.cancelled().await;
        Ok(())
    });
    let driver = async {
        let result = async {
            timeout(Duration::from_secs(30), async {
                loop {
                    if let Ok(health) = client.health().await
                        && health.promotion_ready
                        && !health.fenced
                    {
                        break;
                    }
                    sleep(Duration::from_millis(20)).await;
                }
            })
            .await
            .context("ordinary App Server did not establish promotion readiness")?;
            registry.compare_and_transition(
                &identity.agent_id,
                identity.spawn_generation,
                AgentLifecycle::Running,
            )?;
            timeout(Duration::from_secs(5), async {
                loop {
                    let health = client.health().await?;
                    if health.ready && !health.fenced {
                        return Ok::<_, anyhow::Error>(());
                    }
                    sleep(Duration::from_millis(20)).await;
                }
            })
            .await
            .context("ordinary runtime did not observe Fleet promotion")??;
            work().await
        }
        .await;
        let draining = registry.compare_and_transition(
            &identity.agent_id,
            identity.spawn_generation + 1,
            AgentLifecycle::Draining,
        );
        stop.cancel();
        let value = result?;
        draining?;
        Ok::<T, anyhow::Error>(value)
    };
    let (runtime_result, result) = tokio::join!(runtime, driver);
    // The work must have proved the expected owner condition independently;
    // an unrelated startup, fence, worker or assertion error cannot qualify.
    let value = result?;
    let shutdown_error = match (expected, runtime_result) {
        (ShutdownExpectation::Drained, Ok(())) => None,
        (ShutdownExpectation::UnacknowledgedOutput, Err(AgentdError::Protocol(message)))
            if message
                == "agentd shutdown left 0 indeterminate run(s) and 1 generation service blocker(s); owner recovery is required" =>
        {
            Some(message)
        }
        (_, Err(error)) => {
            return Err(error).context("ordinary Agentd runtime/drain failed unexpectedly");
        }
        (ShutdownExpectation::UnacknowledgedOutput, Ok(())) => {
            anyhow::bail!("shutdown cleared an unacknowledged outbox")
        }
    };
    // RuntimeTasks has cancelled and joined before run returns. Stopped records
    // that host lifetime, not delivery, journal drain or module retirement.
    registry.compare_and_transition(
        &identity.agent_id,
        identity.spawn_generation + 2,
        AgentLifecycle::Stopped,
    )?;
    Ok(Session {
        value,
        shutdown_error,
    })
}
