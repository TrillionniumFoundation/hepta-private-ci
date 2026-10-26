//! Trusted bootstrap of an unused original Core thread. This creates only
//! original thread metadata/catalog: no user message, model turn or authority.
use std::io::BufRead;
use std::io::Read;
use std::path::Path;
use std::path::PathBuf;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::time::Duration;

use codex_app_server_client::RemoteAppServerClient;
use codex_app_server_protocol::ClientRequest;
use codex_app_server_protocol::RequestId;
use codex_app_server_protocol::ThreadResumeParams;
use codex_app_server_protocol::ThreadResumeResponse;
use codex_app_server_protocol::ThreadStartParams;
use codex_app_server_protocol::ThreadStartResponse;
use codex_hepta_types::Digest32;
use codex_history::RolloutItem;
use codex_history::RolloutLine;
use serde::Deserialize;
use serde::Serialize;

use crate::AgentdError;
use crate::notes_literal_adapter::invalid;
use crate::original_notes_thread_tools;

const DEADLINE: Duration = Duration::from_secs(10);
const MAX_META_LINE: u64 = 1024 * 1024;
static NEXT_REQUEST: AtomicU64 = AtomicU64::new(1);

/// Existing actual Core/provider configuration is inherited when omitted. These
/// are trusted startup settings, never model tool arguments or human authority.
#[derive(Default)]
pub struct NotesThreadSeedOptions {
    pub model: Option<String>,
    pub model_provider: Option<String>,
    pub cwd: Option<PathBuf>,
    pub developer_instructions: Option<String>,
}

/// Observed original metadata only. Deserializing this DTO confers no grant;
/// the final original App Server must independently resume and compare it.
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct NotesThreadSeedReceipt {
    pub schema_version: u32,
    pub codex_home: PathBuf,
    pub thread_id: String,
    pub app_server_session_id: String,
    pub model: String,
    pub model_provider: String,
    pub rollout_path: PathBuf,
    pub catalog_sha256: String,
    pub session_meta_sha256: String,
}

fn request_id(action: &str) -> Result<RequestId, AgentdError> {
    let sequence = NEXT_REQUEST
        .fetch_update(Ordering::SeqCst, Ordering::SeqCst, |value| {
            value.checked_add(1)
        })
        .map_err(|_| invalid("original seed request counter exhausted"))?;
    Ok(RequestId::String(format!(
        "hepta.notes.seed.{}.{sequence}.{action}",
        std::process::id()
    )))
}

fn require_home(client: &RemoteAppServerClient, home: &Path) -> Result<(), AgentdError> {
    if !home.is_absolute() || home.to_str() != client.codex_home() || home.canonicalize()? != home {
        return Err(invalid(
            "original seed client is not the expected actual Core home",
        ));
    }
    Ok(())
}

/// The caller supplies an already connected real original App Server client,
/// with experimental_api=true, obtained from its held process/Agentd ingress.
/// A lost Start reply is unknown: this function never retries thread creation.
pub async fn seed_original_notes_thread(
    client: &RemoteAppServerClient,
    codex_home: &Path,
    options: NotesThreadSeedOptions,
) -> Result<NotesThreadSeedReceipt, AgentdError> {
    require_home(client, codex_home)?;
    let cwd = options
        .cwd
        .map(|path| {
            if !path.is_absolute() {
                return Err(invalid("original seed cwd must be absolute"));
            }
            path.into_os_string()
                .into_string()
                .map_err(|_| invalid("original seed cwd is not UTF-8"))
        })
        .transpose()?;
    let started: ThreadStartResponse = tokio::time::timeout(
        DEADLINE,
        client.request_typed(ClientRequest::ThreadStart {
            request_id: request_id("start")?,
            params: ThreadStartParams {
                model: options.model,
                model_provider: options.model_provider,
                cwd,
                developer_instructions: options.developer_instructions,
                allow_provider_model_fallback: false,
                ephemeral: Some(false),
                dynamic_tools: Some(original_notes_thread_tools()),
                ..Default::default()
            },
        }),
    )
    .await
    .map_err(|_| invalid("original thread Start acknowledgement unknown; do not retry creation"))?
    .map_err(|_| invalid("original thread Start failed; inspect its original owner"))?;
    if started.thread.ephemeral
        || started.thread.id.is_empty()
        || started.thread.session_id.is_empty()
        || started.model.is_empty()
        || started.model_provider.is_empty()
    {
        return Err(invalid(
            "original thread Start returned no persistent identity or actual model",
        ));
    }
    // An unused thread has a deferred rollout. Rejoin the SAME running Core
    // instance so its original store writer materializes SessionMeta/catalog.
    let resumed = resume(client, &started.thread.id).await?;
    if resumed.thread.id != started.thread.id
        || resumed.thread.session_id != started.thread.session_id
        || resumed.model != started.model
        || resumed.model_provider != started.model_provider
        || resumed.thread.ephemeral
    {
        return Err(invalid(
            "same-owner seed resume changed thread/session/model/provider",
        ));
    }
    let mut receipt = NotesThreadSeedReceipt {
        schema_version: 1,
        codex_home: codex_home.to_owned(),
        thread_id: resumed.thread.id,
        app_server_session_id: resumed.thread.session_id,
        model: resumed.model,
        model_provider: resumed.model_provider,
        rollout_path: resumed
            .thread
            .path
            .ok_or_else(|| invalid("original seed rollout was not materialized"))?,
        catalog_sha256: Digest32::of_bytes(&serde_json::to_vec(&original_notes_thread_tools())?)
            .to_string(),
        session_meta_sha256: String::new(),
    };
    receipt.session_meta_sha256 = observe_metadata(&receipt).await?;
    Ok(receipt)
}

/// Resume on the final actual Agentd/App Server without model/config/catalog
/// overrides and compare its real response plus persisted original metadata.
pub async fn verify_original_notes_thread_seed(
    client: &RemoteAppServerClient,
    receipt: &NotesThreadSeedReceipt,
) -> Result<(), AgentdError> {
    require_home(client, &receipt.codex_home)?;
    if receipt.schema_version != 1
        || receipt.thread_id.is_empty()
        || receipt.thread_id.len() > 128
        || receipt.app_server_session_id.is_empty()
        || receipt.app_server_session_id.len() > 256
    {
        return Err(invalid("original seed receipt shape mismatch"));
    }
    let actual = resume(client, &receipt.thread_id).await?;
    if actual.thread.ephemeral
        || actual.thread.id != receipt.thread_id
        || actual.thread.session_id != receipt.app_server_session_id
        || actual.model != receipt.model
        || actual.model_provider != receipt.model_provider
        || actual.thread.path.as_ref() != Some(&receipt.rollout_path)
        || observe_metadata(receipt).await? != receipt.session_meta_sha256
    {
        return Err(invalid(
            "final original thread/session/model/provider/catalog metadata differs from seed",
        ));
    }
    Ok(())
}

async fn resume(
    client: &RemoteAppServerClient,
    thread_id: &str,
) -> Result<ThreadResumeResponse, AgentdError> {
    tokio::time::timeout(
        DEADLINE,
        client.request_typed(ClientRequest::ThreadResume {
            request_id: request_id("resume")?,
            params: ThreadResumeParams {
                thread_id: thread_id.into(),
                exclude_turns: true,
                ..Default::default()
            },
        }),
    )
    .await
    .map_err(|_| invalid("original seed resume acknowledgement unknown"))?
    .map_err(|_| invalid("original seed resume failed; no replacement thread was created"))
}

async fn observe_metadata(receipt: &NotesThreadSeedReceipt) -> Result<String, AgentdError> {
    let expected = receipt.clone();
    tokio::time::timeout(
        DEADLINE,
        tokio::task::spawn_blocking(move || inspect_metadata(&expected)),
    )
    .await
    .map_err(|_| invalid("original seed metadata observation timed out"))?
    .map_err(|_| invalid("original seed metadata worker failed"))?
}

fn inspect_metadata(receipt: &NotesThreadSeedReceipt) -> Result<String, AgentdError> {
    let path = &receipt.rollout_path;
    if !path.is_absolute()
        || !path.starts_with(&receipt.codex_home)
        || path.canonicalize()? != *path
        || !std::fs::symlink_metadata(path)?.is_file()
    {
        return Err(invalid(
            "original seed metadata is not its actual in-home regular rollout",
        ));
    }
    let file = std::fs::File::open(path)?;
    let mut line = Vec::new();
    std::io::BufReader::new(file.take(MAX_META_LINE + 1)).read_until(b'\n', &mut line)?;
    if line.is_empty() || line.len() as u64 > MAX_META_LINE || !line.ends_with(b"\n") {
        return Err(invalid(
            "original seed SessionMeta line is absent or exceeds its bound",
        ));
    }
    let RolloutItem::SessionMeta(meta) = serde_json::from_slice::<RolloutLine>(&line)?.item else {
        return Err(invalid(
            "original seed rollout does not begin with SessionMeta",
        ));
    };
    let expected = original_notes_thread_tools();
    let catalog = meta
        .meta
        .dynamic_tools
        .ok_or_else(|| invalid("original seed catalog was not persisted"))?;
    if meta.meta.id.to_string() != receipt.thread_id
        || meta.meta.session_id.to_string() != receipt.app_server_session_id
        || meta.meta.model_provider.as_deref() != Some(receipt.model_provider.as_str())
        || catalog != expected
        || Digest32::of_bytes(&serde_json::to_vec(&catalog)?).to_string() != receipt.catalog_sha256
    {
        return Err(invalid(
            "original persisted thread/session/provider/catalog mismatch",
        ));
    }
    Ok(Digest32::of_bytes(&line).to_string())
}

#[cfg(test)]
#[path = "notes_thread_seed_tests.rs"]
mod tests;
