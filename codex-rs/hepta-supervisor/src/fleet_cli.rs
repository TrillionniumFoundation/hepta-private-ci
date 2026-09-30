use std::ffi::OsString;
use std::path::PathBuf;
use std::time::Duration;

use anyhow::Context;
use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::ReleaseId;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use codex_hepta_paths::HeptaFleetRoot;
use codex_hepta_supervisor::DurableMutationPhaseV1;
use codex_hepta_supervisor::MAX_SUPERVISORD_ROSTER;
use codex_hepta_supervisor::SupervisorError;
use codex_hepta_supervisor::SupervisordClient;
use codex_hepta_supervisor::SupervisordControlFence;
use codex_hepta_supervisor::SupervisordMethod;
use codex_hepta_supervisor::with_offline_fleet_registry;
use serde_json::Value;
use serde_json::json;

#[path = "fleet_cli_configuration.rs"]
mod configuration;

const USAGE: &str = "hepta-fleetctl --fleet-root ABSOLUTE_PATH COMMAND [ARGS]
  init
  register|register-live AGENT_ID ABSOLUTE_WORKSPACE
  install-release RELEASE_ID ABSOLUTE_AGENTD [--matrixd PATH]
      [--agentd-arg ARG]... [--matrixd-arg ARG]...
  allow-release|revoke-release|allow-release-live AGENT_ID RELEASE_ID
  retire|retirement-status AGENT_ID
  health | roster | snapshot AGENT_ID
  start|upgrade AGENT_ID RELEASE_ID REQUEST_ID
  drain|stop|kill|restart|rollback AGENT_ID REQUEST_ID
  mutation-status|reconcile-mutation AGENT_ID REQUEST_ID
Release installation and offline administration require an offline Supervisor.
The -live commands and retirement use the running control owner.
Mutation request IDs must be nonzero and unique. After a lost response, query
mutation-status with the same ID; an uncertain process effect is never retried.";

struct Arguments {
    remaining: std::vec::IntoIter<OsString>,
}

impl Arguments {
    fn next(&mut self, label: &str) -> anyhow::Result<OsString> {
        self.remaining
            .next()
            .with_context(|| format!("missing {label}\n{USAGE}"))
    }

    fn text(&mut self, label: &str) -> anyhow::Result<String> {
        self.next(label)?
            .into_string()
            .map_err(|_| anyhow::anyhow!("{label} must be UTF-8"))
    }

    fn finished(&mut self) -> anyhow::Result<()> {
        anyhow::ensure!(
            self.remaining.next().is_none(),
            "unexpected argument\n{USAGE}"
        );
        Ok(())
    }

    fn agent(&mut self) -> anyhow::Result<AgentId> {
        Ok(AgentId::parse(self.text("AGENT_ID")?)?)
    }

    fn request_id(&mut self) -> anyhow::Result<u64> {
        let id = self.text("REQUEST_ID")?.parse::<u64>()?;
        anyhow::ensure!(id != 0, "REQUEST_ID must be nonzero");
        self.finished()?;
        Ok(id)
    }
}

pub(super) async fn run(args: impl Iterator<Item = OsString>) -> anyhow::Result<()> {
    let mut args = Arguments {
        remaining: args.collect::<Vec<_>>().into_iter(),
    };
    let first = args.text("--fleet-root")?;
    if first == "--help" || first == "-h" {
        args.finished()?;
        println!("{USAGE}");
        return Ok(());
    }
    anyhow::ensure!(first == "--fleet-root", "{USAGE}");
    let root = HeptaFleetRoot::parse(PathBuf::from(args.next("ABSOLUTE_PATH")?))?;
    let command = args.text("COMMAND")?;
    let result = match command.as_str() {
        "init" => {
            args.finished()?;
            let registry = FleetRegistry::initialize(root.clone())?;
            with_offline_fleet_registry(root, |registry| registry.load())?;
            json!({"fleetRoot": registry.layout().fleet_root().as_path()})
        }
        "register" => {
            let agent = args.agent()?;
            let workspace = PathBuf::from(args.next("ABSOLUTE_WORKSPACE")?);
            args.finished()?;
            let manifest = AgentManifest::new(
                agent,
                WorkspaceBinding::new(workspace, &root)?,
                ResourceBudget::local_default(),
            )?;
            let record = with_offline_fleet_registry(root, |registry| registry.register(manifest))?;
            json!({"manifest": record.manifest, "lifecycle": record.lifecycle})
        }
        "install-release" => {
            let release = ReleaseId::parse(args.text("RELEASE_ID")?)?;
            let agentd = PathBuf::from(args.next("ABSOLUTE_AGENTD")?);
            let mut matrixd = None;
            let mut agentd_args = Vec::new();
            let mut matrixd_args = Vec::new();
            while let Some(flag) = args.remaining.next() {
                if flag == "--matrixd" {
                    anyhow::ensure!(matrixd.is_none(), "duplicate --matrixd");
                    matrixd = Some(PathBuf::from(args.next("matrixd path")?));
                } else if flag == "--agentd-arg" {
                    agentd_args.push(args.text("agentd argument")?);
                } else if flag == "--matrixd-arg" {
                    matrixd_args.push(args.text("matrixd argument")?);
                } else {
                    anyhow::bail!("unknown install-release argument {flag:?}");
                }
            }
            let release = with_offline_fleet_registry(root, |registry| {
                registry.install_release_bundle(
                    release,
                    &agentd,
                    agentd_args,
                    matrixd.as_deref(),
                    matrixd_args,
                )
            })?;
            json!({"releaseId": release.release_id, "matrixCompanion": release.matrixd.is_some()})
        }
        "allow-release" | "revoke-release" => {
            let agent = args.agent()?;
            let release = ReleaseId::parse(args.text("RELEASE_ID")?)?;
            args.finished()?;
            with_offline_fleet_registry(root, |registry| {
                if command == "allow-release" {
                    registry.allow_release(&agent, &release)
                } else {
                    registry.revoke_release(&agent, &release)
                }
            })?;
            json!({"agentId": agent, "releaseId": release, "operation": command})
        }
        "register-live" | "allow-release-live" | "retire" | "retirement-status" | "health"
        | "roster" | "snapshot" | "mutation-status" | "reconcile-mutation" | "start"
        | "upgrade" | "drain" | "stop" | "kill" | "restart" | "rollback" => {
            control(&root, &command, &mut args).await?
        }
        _ => anyhow::bail!("unknown command {command}\n{USAGE}"),
    };
    println!("{}", serde_json::to_string_pretty(&result)?);
    Ok(())
}

async fn control(
    root: &HeptaFleetRoot,
    command: &str,
    args: &mut Arguments,
) -> anyhow::Result<Value> {
    let client = SupervisordClient::new(root.layout().supervisor_socket().to_path_buf())?
        .with_timeout(Duration::from_secs(10))?;
    match command {
        "register-live" => {
            let agent = args.agent()?;
            let workspace = PathBuf::from(args.next("ABSOLUTE_WORKSPACE")?);
            args.finished()?;
            let manifest = AgentManifest::new(
                agent,
                WorkspaceBinding::new(workspace, root)?,
                ResourceBudget::local_default(),
            )?;
            let deadline = tokio::time::Instant::now() + Duration::from_secs(10);
            let result = loop {
                let result =
                    tokio::time::timeout_at(deadline, client.register_agent(manifest.clone()))
                        .await
                        .context("owner remained busy before registration")?;
                if !matches!(result, Err(SupervisorError::NotAdmittedBusy)) {
                    break result;
                }
                tokio::time::sleep(Duration::from_millis(25)).await;
            };
            let agent = match result {
                Ok(agent) => agent,
                Err(error) => loop {
                    // Query the exact local durable manifest and owner slot;
                    // never repeat a registration after an uncertain response.
                    if let Ok(registry) = FleetRegistry::open_existing(root.clone()) {
                        if registry
                            .load_agent(&manifest.agent_id)
                            .is_ok_and(|record| record.manifest == manifest)
                        {
                            if let Ok(Ok(agent)) = tokio::time::timeout_at(
                                deadline,
                                client.snapshot(manifest.agent_id.clone()),
                            )
                            .await
                            {
                                break agent;
                            }
                        }
                    }
                    if tokio::time::Instant::now() >= deadline {
                        return Err(error.into());
                    }
                    tokio::time::sleep(Duration::from_millis(25)).await;
                },
            };
            Ok(serde_json::to_value(agent)?)
        }
        "allow-release-live" => {
            let agent = args.agent()?;
            let release = ReleaseId::parse(args.text("RELEASE_ID")?)?;
            args.finished()?;
            configuration::allow(root, &client, agent, release).await
        }
        "retire" => {
            let agent = args.agent()?;
            args.finished()?;
            configuration::retire(root, &client, agent).await
        }
        "retirement-status" => {
            let agent = args.agent()?;
            args.finished()?;
            Ok(
                json!({"agentId": agent, "archivedRoot": client.retired_agent_status(agent.clone()).await?}),
            )
        }
        "health" => {
            args.finished()?;
            Ok(serde_json::to_value(client.health().await?)?)
        }
        "roster" => {
            args.finished()?;
            Ok(serde_json::to_value(
                client.roster(MAX_SUPERVISORD_ROSTER).await?,
            )?)
        }
        "snapshot" => {
            let agent = args.agent()?;
            args.finished()?;
            Ok(serde_json::to_value(client.snapshot(agent).await?)?)
        }
        "mutation-status" => {
            let agent = args.agent()?;
            let request_id = args.request_id()?;
            Ok(
                json!({"requestId": request_id, "status": client.ordinary_mutation_status(agent, request_id).await?}),
            )
        }
        "reconcile-mutation" => {
            let agent = args.agent()?;
            let request_id = args.request_id()?;
            let fence = client.snapshot(agent.clone()).await?.control_fence;
            Ok(
                json!({"requestId": request_id, "status": client.reconcile_ordinary_mutation(fence, request_id).await?}),
            )
        }
        "start" | "upgrade" | "drain" | "stop" | "kill" | "restart" | "rollback" => {
            let agent = args.agent()?;
            let release = if matches!(command, "start" | "upgrade") {
                Some(ReleaseId::parse(args.text("RELEASE_ID")?)?)
            } else {
                None
            };
            let request_id = args.request_id()?;
            let admission_deadline = tokio::time::Instant::now() + Duration::from_secs(10);
            let fence = admission_fence(&client, &agent, request_id, admission_deadline).await?;
            let mut method = match command {
                "start" => SupervisordMethod::Start {
                    fence,
                    release_id: release.context("missing release")?,
                },
                "upgrade" => SupervisordMethod::Upgrade {
                    fence,
                    release_id: release.context("missing release")?,
                },
                "drain" => SupervisordMethod::Drain { fence },
                "stop" => SupervisordMethod::Stop { fence },
                "kill" => SupervisordMethod::Kill { fence },
                "restart" => SupervisordMethod::Restart { fence },
                "rollback" => SupervisordMethod::Rollback { fence },
                _ => unreachable!(),
            };
            eprintln!(
                "mutation requestId={request_id}; query mutation-status after an uncertain response"
            );
            let admission = loop {
                let outcome = tokio::time::timeout_at(
                    admission_deadline,
                    client.execute_mutation_with_request_id(request_id, method.clone()),
                )
                .await
                .map_err(|_| SupervisorError::Invalid("mutation admission timed out".to_string()))
                .and_then(std::convert::identity);
                if !matches!(outcome, Err(SupervisorError::NotAdmittedBusy)) {
                    break outcome;
                }
                // Only this explicit pre-owner rejection proves no effect. A
                // timeout, lost response, or owner error must go to status reads.
                // Retain the request ID and refresh its generation fence before
                // a bounded re-admission, never replay an admitted operation.
                let refreshed = snapshot_fence(&client, &agent, admission_deadline).await?;
                match &mut method {
                    SupervisordMethod::Start { fence, .. }
                    | SupervisordMethod::Upgrade { fence, .. }
                    | SupervisordMethod::Drain { fence }
                    | SupervisordMethod::Stop { fence }
                    | SupervisordMethod::Kill { fence }
                    | SupervisordMethod::Restart { fence }
                    | SupervisordMethod::Rollback { fence } => *fence = refreshed,
                    _ => unreachable!("ordinary mutation selected above"),
                }
                tokio::time::sleep(Duration::from_millis(25)).await;
            };
            let accepted = match admission {
                Ok(accepted) => accepted,
                Err(error) => {
                    // Resolve an uncertain response using reads of the exact
                    // durable request. Never resend the physical mutation.
                    let deadline = tokio::time::Instant::now() + Duration::from_secs(10);
                    loop {
                        match tokio::time::timeout_at(
                            deadline,
                            client.ordinary_mutation_status(agent.clone(), request_id),
                        )
                        .await
                        {
                            Ok(Ok(Some(status))) => {
                                anyhow::ensure!(
                                    status.request_id == request_id
                                        && status.agent_id == agent
                                        && status.operation.to_string() == command,
                                    "durable response identity mismatch after {error}"
                                );
                                match status.phase {
                                    DurableMutationPhaseV1::Committed => {
                                        let snapshot = tokio::time::timeout_at(
                                            deadline,
                                            client.snapshot(agent.clone()),
                                        )
                                        .await
                                        .context(
                                            "durable outcome committed; snapshot deadline expired",
                                        )??;
                                        return Ok(
                                            json!({"requestId": request_id, "recovered": true, "status": status, "agent": snapshot}),
                                        );
                                    }
                                    DurableMutationPhaseV1::Ambiguous
                                    | DurableMutationPhaseV1::RequiresOperator => {
                                        anyhow::bail!(
                                            "mutation requestId={request_id} remains {:?}; inspect mutation-status before operator recovery: {error}",
                                            status.phase
                                        );
                                    }
                                    DurableMutationPhaseV1::Prepared
                                    | DurableMutationPhaseV1::EffectStarted => {}
                                }
                            }
                            Ok(Ok(None) | Err(_)) => {}
                            Err(_) => return Err(error.into()),
                        }
                        if tokio::time::Instant::now() >= deadline {
                            return Err(error.into());
                        }
                        tokio::time::sleep(Duration::from_millis(25)).await;
                    }
                }
            };
            Ok(json!({
                "requestId": request_id,
                "operation": accepted.operation,
                "acceptedStateDigest": accepted.accepted_state_digest,
                "agent": accepted.agent,
                "productionReceipt": accepted.production_receipt
            }))
        }
        _ => anyhow::bail!("unknown control command {command}"),
    }
}

async fn admission_fence(
    client: &SupervisordClient,
    agent: &AgentId,
    request_id: u64,
    deadline: tokio::time::Instant,
) -> anyhow::Result<SupervisordControlFence> {
    loop {
        let observation = tokio::time::timeout_at(deadline, async {
            if client
                .ordinary_mutation_status(agent.clone(), request_id)
                .await?
                .is_some()
            {
                return Err(SupervisorError::Invalid(
                    "REQUEST_ID is already recorded; query mutation-status instead of replaying it"
                        .into(),
                ));
            }
            Ok(client.snapshot(agent.clone()).await?.control_fence)
        })
        .await
        .context("owner remained busy before admission")?;
        match observation {
            Err(SupervisorError::NotAdmittedBusy) => {
                tokio::time::sleep(Duration::from_millis(25)).await
            }
            outcome => return Ok(outcome?),
        }
    }
}

async fn snapshot_fence(
    client: &SupervisordClient,
    agent: &AgentId,
    deadline: tokio::time::Instant,
) -> anyhow::Result<SupervisordControlFence> {
    loop {
        match tokio::time::timeout_at(deadline, client.snapshot(agent.clone())).await? {
            Ok(snapshot) => return Ok(snapshot.control_fence),
            Err(error) => {
                if tokio::time::Instant::now() >= deadline {
                    return Err(error.into());
                }
                tokio::time::sleep(Duration::from_millis(25)).await;
            }
        }
    }
}
