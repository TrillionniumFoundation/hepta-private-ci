//! Trusted launcher for one unused original Notes model thread.
//!
//! This connects only through the already running Agentd session ingress,
//! creates no human turn, performs no model request, grants no authority and
//! executes no Notes effect. The output is metadata for the Root launch
//! profile; the final runtime must independently resume and verify it.

use std::collections::BTreeMap;
use std::ffi::OsStr;
use std::path::PathBuf;

use codex_app_server_client::RemoteAppServerClient;
use codex_app_server_client::RemoteAppServerConnectArgs;
use codex_app_server_client::RemoteAppServerEndpoint;
use codex_hepta_agentd::AgentdClient;
use codex_hepta_agentd::AgentdTextSessionConfig;
use codex_hepta_agentd::NotesThreadSeedOptions;
use codex_hepta_agentd::NotesThreadSeedReceipt;
use codex_hepta_agentd::seed_original_notes_thread;
use codex_hepta_contracts::AgentId;
use serde::Serialize;

#[derive(Serialize)]
struct SeededInteraction {
    schema_version: u32,
    interaction: OriginalThreadInteraction,
}

#[derive(Serialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
enum OriginalThreadInteraction {
    OriginalThreadToolV1 {
        route: AgentdTextSessionConfig,
        seed: Box<NotesThreadSeedReceipt>,
    },
}

fn take(
    options: &mut BTreeMap<std::ffi::OsString, std::ffi::OsString>,
    key: &str,
) -> Result<std::ffi::OsString, Box<dyn std::error::Error>> {
    options
        .remove(OsStr::new(key))
        .ok_or_else(|| format!("missing required option {key}").into())
}

fn parse_options() -> Result<
    (PathBuf, AgentId, u64, PathBuf, PathBuf),
    Box<dyn std::error::Error>,
> {
    let mut args = std::env::args_os().skip(1);
    let mut options = BTreeMap::new();
    while let Some(option) = args.next() {
        let value = args.next().ok_or("missing option value")?;
        if options.insert(option, value).is_some() {
            return Err("duplicate option".into());
        }
    }
    let control_socket = PathBuf::from(take(&mut options, "--control-socket")?);
    let agent_id = take(&mut options, "--agent-id")?
        .into_string()
        .map_err(|_| "agent id must be UTF-8")?;
    let agent_id = AgentId::parse(agent_id)?;
    let spawn_generation = take(&mut options, "--spawn-generation")?
        .into_string()
        .map_err(|_| "spawn generation must be UTF-8")?
        .parse::<u64>()?;
    let codex_home = PathBuf::from(take(&mut options, "--codex-home")?);
    let cwd = PathBuf::from(take(&mut options, "--cwd")?);
    if !options.is_empty() {
        return Err("unknown option".into());
    }
    Ok((
        control_socket,
        agent_id,
        spawn_generation,
        codex_home,
        cwd,
    ))
}

#[tokio::main(flavor = "current_thread")]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let (control_socket, agent_id, spawn_generation, codex_home, cwd) = parse_options()?;
    let control = AgentdClient::new(control_socket.clone(), agent_id.clone(), spawn_generation)?;
    let ingress = control.session_ingress().await?;
    let client = RemoteAppServerClient::connect_with_bounded_events(
        RemoteAppServerConnectArgs {
            endpoint: RemoteAppServerEndpoint::UnixSocket {
                socket_path: ingress.socket_path.as_path().try_into()?,
            },
            client_name: "hepta-original-notes-thread-seed".into(),
            client_version: env!("CARGO_PKG_VERSION").into(),
            experimental_api: true,
            mcp_server_openai_form_elicitation: false,
            opt_out_notification_methods: vec![],
            channel_capacity: 8,
        },
        128,
    )
    .await?;
    let receipt = seed_original_notes_thread(
        &client,
        &codex_home,
        NotesThreadSeedOptions {
            cwd: Some(cwd),
            ..Default::default()
        },
    )
    .await?;
    let route = AgentdTextSessionConfig {
        control_socket,
        agent_id,
        spawn_generation,
        thread_id: receipt.thread_id.clone(),
        app_server_session_id: receipt.app_server_session_id.clone(),
        codex_home,
    };
    let output = SeededInteraction {
        schema_version: 1,
        interaction: OriginalThreadInteraction::OriginalThreadToolV1 {
            route,
            seed: Box::new(receipt),
        },
    };
    client.shutdown().await?;
    println!("{}", serde_json::to_string(&output)?);
    Ok(())
}
