//! Operator control uses the existing supervisor protocol and daemon writer.
//! It never creates signing keys, writes release state, or retries a mutation.

use std::io::Read;
use std::path::Path;
use std::path::PathBuf;

use anyhow::Context;
use anyhow::Result;
use anyhow::bail;
use anyhow::ensure;
use codex_hepta_contracts::AgentId;
use codex_hepta_supervisor::SignedIntentStatus;
use codex_hepta_supervisor::SupervisordClient;
use codex_hepta_supervisor::SupervisordMethod;
use codex_hepta_supervisor::SupervisordMutationAccepted;
use codex_hepta_supervisor::SupervisordPayload;
use codex_hepta_supervisor::SupervisordRequest;
use codex_hepta_supervisor::read_signed_intent;
use serde_json::json;

const MAX_SUBMISSION_BYTES: u64 = 64 * 1024;
const USAGE: &str = "usage: hepta-supervisor-intent-recovery inspect <run-root> | abort <run-root> <intent-sha256> | inspect-production <absolute-socket> <agent-id> | submit-production <absolute-socket> <absolute-method-json> --submit";

#[tokio::main(flavor = "current_thread")]
async fn main() -> Result<()> {
    let mut args = std::env::args_os().skip(1);
    let command = args
        .next()
        .and_then(|value| value.into_string().ok())
        .context(USAGE)?;
    if matches!(command.as_str(), "--help" | "-h") {
        ensure!(args.next().is_none(), "{USAGE}");
        println!("{USAGE}");
        return Ok(());
    }
    let root_or_socket = PathBuf::from(args.next().context(USAGE)?);

    match command.as_str() {
        "inspect" => {
            ensure!(args.next().is_none(), "inspect accepts only <run-root>");
            let intent = read_signed_intent(&root_or_socket)?
                .context("no signed supervisor intent exists at this run root")?;
            println!("{}", serde_json::to_string_pretty(&intent)?);
        }
        "abort" => {
            bail!(
                "unsigned abort directives cannot resolve an ambiguous signed effect; use supervisord's independently signed recovery ceremony"
            )
        }
        "inspect-production" => {
            let agent = args
                .next()
                .and_then(|value| value.into_string().ok())
                .context("inspect-production requires <agent-id>")?;
            ensure!(args.next().is_none(), "{USAGE}");
            let agent = AgentId::parse(agent).map_err(anyhow::Error::msg)?;
            let client = SupervisordClient::new(root_or_socket)?;
            let first = observe(&client, &agent).await?;
            let second = observe(&client, &agent).await?;
            ensure!(
                first == second,
                "supervisor observations changed; obtain fresh evidence before signing"
            );
            // This is a consistency-checked observation, not an atomic read or
            // a grant. The daemon revalidates the submitted CAS and signature.
            println!("{}", serde_json::to_string_pretty(&second)?);
        }
        "submit-production" => {
            let path = PathBuf::from(args.next().context("submission file is required")?);
            ensure!(
                args.next().as_deref() == Some(std::ffi::OsStr::new("--submit"))
                    && args.next().is_none(),
                "explicit --submit is required; {USAGE}"
            );
            let method = read_production_method(&path)?;
            let client = SupervisordClient::new(root_or_socket)?;
            let response = submit(&client, method).await.context(
                "no confirmed response; outcome may be unknown: inspect durable state before retrying",
            )?;
            println!("{}", serde_json::to_string_pretty(&response)?);
        }
        _ => bail!("unknown command; {USAGE}"),
    }
    Ok(())
}

async fn observe(client: &SupervisordClient, agent: &AgentId) -> Result<serde_json::Value> {
    let snapshot = client.snapshot(agent.clone()).await?;
    let mutation = client.production_mutation_status(agent.clone()).await?;
    let selection = client.release_selection(agent.clone()).await?;
    Ok(json!({
        "snapshot": snapshot,
        "production_mutation": mutation,
        "release_selection": selection
    }))
}

fn read_production_method(path: &Path) -> Result<SupervisordMethod> {
    ensure!(path.is_absolute(), "submission path must be absolute");
    let metadata = std::fs::symlink_metadata(path)?;
    ensure!(
        metadata.file_type().is_file(),
        "submission must be a non-symlink regular file"
    );
    let mut options = std::fs::OpenOptions::new();
    options.read(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC | libc::O_NONBLOCK);
    }
    let file = options.open(path)?;
    let opened = file.metadata()?;
    ensure!(
        opened.file_type().is_file(),
        "opened submission is not a regular file"
    );
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        // SAFETY: geteuid has no arguments or memory-safety preconditions.
        let owner = unsafe { libc::geteuid() };
        ensure!(
            opened.uid() == owner && opened.mode() & 0o022 == 0,
            "submission must be owned by the effective user and not writable by others"
        );
        ensure!(
            opened.dev() == metadata.dev() && opened.ino() == metadata.ino(),
            "submission identity changed during open"
        );
    }
    let mut bytes = Vec::new();
    file.take(MAX_SUBMISSION_BYTES + 1)
        .read_to_end(&mut bytes)?;
    ensure!(
        bytes.len() as u64 <= MAX_SUBMISSION_BYTES,
        "submission exceeds frame budget"
    );
    let method: SupervisordMethod =
        serde_json::from_slice(&bytes).context("invalid typed supervisor method JSON")?;
    ensure!(
        matches!(
            &method,
            SupervisordMethod::SignedUpgrade { .. }
                | SupervisordMethod::SignedRollback { .. }
                | SupervisordMethod::ResolveProductionRecovery { .. }
        ),
        "production submission accepts only signed_upgrade, signed_rollback, or resolve_production_recovery"
    );
    SupervisordRequest::new(1, method.clone())
        .validate()
        .map_err(|_| anyhow::anyhow!("invalid supervisor CAS fence"))?;
    Ok(method)
}

fn accepted(response: SupervisordMutationAccepted) -> Result<serde_json::Value> {
    let payload = SupervisordPayload::MutationAccepted {
        operation: response.operation,
        accepted_state_digest: response.accepted_state_digest,
        agent: response.agent,
        production_receipt: response.production_receipt,
    };
    serde_json::to_value(payload).context("serialize canonical mutation acceptance")
}

async fn submit(
    client: &SupervisordClient,
    method: SupervisordMethod,
) -> Result<serde_json::Value> {
    match method {
        SupervisordMethod::SignedUpgrade {
            fence,
            grant,
            h7_envelope,
        } => accepted(client.signed_upgrade(fence, grant, h7_envelope).await?),
        SupervisordMethod::SignedRollback {
            fence,
            grant,
            h7_envelope,
        } => accepted(client.signed_rollback(fence, grant, h7_envelope).await?),
        SupervisordMethod::ResolveProductionRecovery { fence, decision } => {
            let digest = decision.digest().clone();
            let state = client.resolve_production_recovery(fence, decision).await?;
            Ok(json!({
                "operation": "resolve_production_recovery",
                "decision_sha256": digest,
                "durable_state": state
            }))
        }
        _ => bail!("unsigned or read-only method is not a production submission"),
    }
}
