use std::fs::OpenOptions;
use std::io::Write;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_matrix_protocol::MatrixEventId;
use codex_hepta_matrix_protocol::MatrixRoomId;
use codex_hepta_matrix_protocol::MatrixUserId;
use codex_hepta_matrix_store::MatrixDurableStore;
use codex_hepta_matrix_store::MatrixSyncCheckpoint;
use codex_hepta_matrix_store::OutboxRecord;
use codex_hepta_paths::HeptaAgentLayout;
use matrix_sdk::Client;
use matrix_sdk::Error as MatrixSdkTransportError;
use matrix_sdk::HttpError;
use matrix_sdk::config::SyncSettings;
use matrix_sdk::config::SyncToken;
use matrix_sdk::ruma::OwnedRoomId;
use matrix_sdk::ruma::OwnedTransactionId;
use matrix_sdk::ruma::UInt;
use matrix_sdk::ruma::api::client::filter::FilterDefinition;
use matrix_sdk::ruma::api::client::sync::sync_events::v3::Filter;
use matrix_sdk::ruma::events::AnySyncMessageLikeEvent;
use matrix_sdk::ruma::events::AnySyncTimelineEvent;
use matrix_sdk::ruma::events::SyncMessageLikeEvent;
use matrix_sdk::ruma::events::room::message::MessageType;
use matrix_sdk::ruma::events::room::message::OriginalSyncRoomMessageEvent;
use matrix_sdk::ruma::events::room::message::RoomMessageEventContent;
use matrix_sdk::store::StateStoreDataKey;
use serde_json::Value;
use tokio_util::sync::CancellationToken;
use url::Url;

use crate::IngressIgnoredReason;
use crate::MatrixIngress;
use crate::MatrixOutboundTransport;
use crate::MatrixSdkPaths;
use crate::MatrixSendFuture;
use crate::MatrixSession;
use crate::MatrixSidecarConfig;
use crate::MatrixSidecarConfigError;
use crate::MatrixTimelineEvent;
use crate::MatrixTransportError;

const MATRIX_ROOM_MESSAGE_EVENT_TYPE: &str = "m.room.message";
const MATRIX_ROOM_ENCRYPTED_EVENT_TYPE: &str = "m.room.encrypted";
// A Matrix companion must either reach its homeserver quickly or return to
// Supervisor for its bounded, generation-fenced retry schedule. Matrix SDK
// startup paths may otherwise consume several transport attempts and their
// individual timeouts before matrixd can bind its control socket.
const MATRIX_STARTUP_REQUEST_TIMEOUT: std::time::Duration = std::time::Duration::from_secs(5);
const MATRIX_SESSION_MAX_BYTES: u64 = 16 * 1024;

pub struct MatrixSdkClient {
    client: Client,
    config: MatrixSidecarConfig,
    paths: MatrixSdkPaths,
}

impl MatrixSdkClient {
    pub async fn restore(
        layout: &HeptaAgentLayout,
        config: MatrixSidecarConfig,
        session: MatrixSession,
        store_passphrase: Option<&str>,
    ) -> Result<Self, MatrixSdkError> {
        verify_session_identity(&config, &session)?;
        let sidecar = tokio::time::timeout(
            MATRIX_STARTUP_REQUEST_TIMEOUT,
            Self::build(layout, config, store_passphrase),
        )
        .await
        .map_err(|_| MatrixSdkError::Initialization)??;
        sidecar
            .client
            .restore_session(session.clone())
            .await
            .map_err(|_| MatrixSdkError::Authentication)?;
        persist_session(sidecar.paths.session(), &session)?;
        sidecar.verify_authenticated_identity()?;
        sidecar.enable_event_cache()?;
        Ok(sidecar)
    }

    pub async fn login_password(
        layout: &HeptaAgentLayout,
        config: MatrixSidecarConfig,
        password: &str,
        store_passphrase: Option<&str>,
        device_display_name: Option<&str>,
    ) -> Result<(Self, MatrixSession), MatrixSdkError> {
        let sidecar = tokio::time::timeout(
            MATRIX_STARTUP_REQUEST_TIMEOUT,
            Self::build(layout, config, store_passphrase),
        )
        .await
        .map_err(|_| MatrixSdkError::Initialization)??;
        let mut login = sidecar
            .client
            .matrix_auth()
            .login_username(sidecar.config.binding.expected_mxid.as_str(), password)
            .device_id(sidecar.config.binding.expected_device_id.as_str())
            .request_refresh_token();
        if let Some(display_name) = device_display_name {
            login = login.initial_device_display_name(display_name);
        }
        // `LoginBuilder::send` replaces the client's request config with the
        // SDK's own three-attempt policy (whose individual timeout defaults
        // to 30s).  Bound the whole startup login so an offline replacement
        // returns to Supervisor instead of occupying the health window.
        let response = tokio::time::timeout(MATRIX_STARTUP_REQUEST_TIMEOUT, login.send())
            .await
            .map_err(|_| MatrixSdkError::Authentication)?
            .map_err(|_| MatrixSdkError::Authentication)?;
        let session = MatrixSession::from(&response);
        verify_session_identity(&sidecar.config, &session)?;
        persist_session(sidecar.paths.session(), &session)?;
        sidecar.verify_authenticated_identity()?;
        sidecar.enable_event_cache()?;
        Ok((sidecar, session))
    }

    /// Restore the exact per-Agent Matrix session without contacting the
    /// homeserver when a previous login has already succeeded.  A failed
    /// local restore is isolated to that client instance; the fallback login
    /// builds a fresh client so a partially activated SDK session can never be
    /// reused after an error.
    pub async fn login_or_restore(
        layout: &HeptaAgentLayout,
        config: MatrixSidecarConfig,
        password: &str,
        store_passphrase: Option<&str>,
        device_display_name: Option<&str>,
    ) -> Result<(Self, MatrixSession), MatrixSdkError> {
        let sidecar = tokio::time::timeout(
            MATRIX_STARTUP_REQUEST_TIMEOUT,
            Self::build(layout, config.clone(), store_passphrase),
        )
        .await
        .map_err(|_| MatrixSdkError::Initialization)??;

        if let Some(session) = load_session(sidecar.paths.session())? {
            verify_session_identity(&sidecar.config, &session)?;
            let restore = tokio::time::timeout(
                MATRIX_STARTUP_REQUEST_TIMEOUT,
                sidecar.client.restore_session(session.clone()),
            )
            .await;
            if matches!(restore, Ok(Ok(()))) {
                sidecar.verify_authenticated_identity()?;
                sidecar.enable_event_cache()?;
                return Ok((sidecar, session));
            }
        }

        drop(sidecar);
        Self::login_password(
            layout,
            config,
            password,
            store_passphrase,
            device_display_name,
        )
        .await
    }

    async fn build(
        layout: &HeptaAgentLayout,
        config: MatrixSidecarConfig,
        store_passphrase: Option<&str>,
    ) -> Result<Self, MatrixSdkError> {
        let paths = MatrixSdkPaths::prepare(layout, &config)?;
        let client = Client::builder()
            .homeserver_url(config.binding.homeserver.as_str())
            .sqlite_store_with_cache_path(paths.state(), paths.cache(), store_passphrase)
            .handle_refresh_tokens()
            .build()
            .await
            .map_err(|_| MatrixSdkError::Initialization)?;
        // The SDK's own sync token is only an optimization for its normal
        // sync loop.  Hepta persists the authoritative cursor in its durable
        // inbox store and always supplies that cursor explicitly.  Clear a
        // stale SDK token before session activation so a process restart
        // cannot discard a replay whose `next_batch` happens to equal the
        // SDK token that was persisted before the prior inbox commit.
        client
            .state_store()
            .remove_kv_data(StateStoreDataKey::SyncToken)
            .await
            .map_err(|_| MatrixSdkError::Initialization)?;
        let save_session_path = paths.session().to_path_buf();
        let reload_session_path = paths.session().to_path_buf();
        client
            .set_session_callbacks(
                Box::new(move |_client| {
                    let session = load_session(&reload_session_path)
                        .map_err(|error| {
                            Box::new(error) as Box<dyn std::error::Error + Send + Sync>
                        })?
                        .ok_or_else(|| {
                            Box::new(MatrixSdkError::Authentication)
                                as Box<dyn std::error::Error + Send + Sync>
                        })?;
                    Ok(session.tokens)
                }),
                Box::new(move |client| {
                    let session = client.matrix_auth().session().ok_or_else(|| {
                        Box::new(MatrixSdkError::Authentication)
                            as Box<dyn std::error::Error + Send + Sync>
                    })?;
                    persist_session(&save_session_path, &session).map_err(|error| {
                        Box::new(error) as Box<dyn std::error::Error + Send + Sync>
                    })
                }),
            )
            .map_err(|_| MatrixSdkError::Initialization)?;
        verify_homeserver(&config, &client)?;
        Ok(Self {
            client,
            config,
            paths,
        })
    }

    pub fn client(&self) -> &Client {
        &self.client
    }

    pub fn config(&self) -> &MatrixSidecarConfig {
        &self.config
    }

    pub fn paths(&self) -> &MatrixSdkPaths {
        &self.paths
    }

    /// Run `/sync` using the Hepta durable cursor as the only ingress
    /// authority.
    ///
    /// matrix-sdk 0.18 persists its internal `next_batch` before awaiting
    /// application event handlers.  An ordinary handler can therefore lose a
    /// message if the process dies after the SDK cursor commit but before the
    /// Hepta inbox write.  This loop always supplies the Hepta cursor
    /// explicitly, normalizes the returned batch, and advances that cursor in
    /// the same SQLite transaction as all accepted inbox events.
    pub async fn sync_durable_until_cancelled(
        &self,
        store: &MatrixDurableStore,
        ingress: &MatrixIngress,
        cancel: &CancellationToken,
    ) -> Result<MatrixSyncExit, MatrixSdkError> {
        loop {
            if cancel.is_cancelled() {
                return Ok(MatrixSyncExit::Cancelled);
            }
            let checkpoint = store
                .sync_checkpoint(self.config.binding.revision, self.config.matrix_generation)
                .await
                .map_err(|_| MatrixSdkError::Store)?;
            let expected_next_batch = checkpoint
                .as_ref()
                .map(|checkpoint| checkpoint.next_batch.as_str());
            let token = hepta_sync_token(checkpoint.as_ref());
            let response = self
                .client
                .sync_once(bounded_sync_settings(&self.config)?.token(token))
                .await
                .map_err(|_| MatrixSdkError::Sync)?;
            let received_at_ms = system_time_ms()?;
            let events = normalized_sync_events(&response, ingress, received_at_ms)?;
            let commit = store
                .commit_sync_batch(
                    self.config.binding.revision,
                    self.config.matrix_generation,
                    expected_next_batch,
                    &response.next_batch,
                    &events,
                    received_at_ms,
                )
                .await
                .map_err(|_| MatrixSdkError::Store)?;
            ingress.record_sync_commit(&commit);
            if cancel.is_cancelled() {
                return Ok(MatrixSyncExit::Cancelled);
            }
        }
    }

    fn enable_event_cache(&self) -> Result<(), MatrixSdkError> {
        self.client
            .event_cache()
            .subscribe()
            .map_err(|_| MatrixSdkError::Initialization)
    }

    fn verify_authenticated_identity(&self) -> Result<(), MatrixSdkError> {
        let user_id = self
            .client
            .user_id()
            .ok_or(MatrixSdkError::Authentication)?;
        let device_id = self
            .client
            .device_id()
            .ok_or(MatrixSdkError::Authentication)?;
        if user_id.as_str() != self.config.binding.expected_mxid.as_str()
            || device_id.as_str() != self.config.binding.expected_device_id.as_str()
        {
            return Err(MatrixSdkError::IdentityMismatch);
        }
        verify_homeserver(&self.config, &self.client)
    }
}

fn hepta_sync_token(checkpoint: Option<&MatrixSyncCheckpoint>) -> SyncToken {
    checkpoint
        .map(|checkpoint| SyncToken::Specific(checkpoint.next_batch.clone()))
        .unwrap_or(SyncToken::NoToken)
}

impl MatrixOutboundTransport for MatrixSdkClient {
    fn send<'a>(&'a self, record: &'a OutboxRecord) -> MatrixSendFuture<'a> {
        Box::pin(async move {
            if !self.config.binding.allowed_rooms.contains(&record.room_id)
                || record.binding_revision != self.config.binding.revision
                || record.generation != self.config.matrix_generation
            {
                return Err(MatrixTransportError::Permanent);
            }
            let body = std::str::from_utf8(&record.payload)
                .map_err(|_| MatrixTransportError::Permanent)?;
            let room_id = OwnedRoomId::try_from(record.room_id.as_str())
                .map_err(|_| MatrixTransportError::Permanent)?;
            let room = self
                .client
                .get_room(&room_id)
                .ok_or(MatrixTransportError::Retryable)?;
            let txn_id = OwnedTransactionId::from(record.stable_txn_id.as_str());
            let content = outbound_message_content(body, record.replaces_event_id.as_ref());
            let response = room
                .send_raw(MATRIX_ROOM_MESSAGE_EVENT_TYPE, content)
                .with_transaction_id(&txn_id)
                .await
                .map_err(|error| classify_sdk_send_error(&error))?;
            let event_id = MatrixEventId::parse(response.response.event_id.as_str())
                .map_err(|_| MatrixTransportError::Permanent)?;
            #[cfg(feature = "qualification-failpoints")]
            if crate::qualification::consume_post_send_pre_mark_ack_drop(
                self.paths.root(),
                record,
                &event_id,
            )
            .map_err(|_| MatrixTransportError::Retryable)?
            {
                // Synapse has accepted the PUT and returned `event_id`, but
                // deliberately hide that acknowledgement from the durable
                // dispatcher. The next claim must reuse `stable_txn_id`.
                return Err(MatrixTransportError::Retryable);
            }
            Ok(event_id)
        })
    }
}

fn outbound_message_content(body: &str, replaces_event_id: Option<&MatrixEventId>) -> Value {
    if let Some(replaces_event_id) = replaces_event_id {
        serde_json::json!({
            "msgtype": "m.text",
            "body": body,
            "m.new_content": {
                "msgtype": "m.text",
                "body": body,
            },
            "m.relates_to": {
                "rel_type": "m.replace",
                "event_id": replaces_event_id.as_str(),
            },
        })
    } else {
        serde_json::json!({
            "msgtype": "m.text",
            "body": body,
        })
    }
}

fn classify_sdk_send_error(error: &MatrixSdkTransportError) -> MatrixTransportError {
    match error {
        MatrixSdkTransportError::Http(error) => classify_http_error(error),
        MatrixSdkTransportError::Timeout | MatrixSdkTransportError::ConcurrentRequestFailed => {
            MatrixTransportError::Retryable
        }
        _ => MatrixTransportError::Permanent,
    }
}

fn classify_http_error(error: &HttpError) -> MatrixTransportError {
    match error {
        HttpError::Reqwest(_) => MatrixTransportError::Retryable,
        HttpError::Api(_) => error
            .as_client_api_error()
            .map(|error| classify_http_status(error.status_code.as_u16()))
            .unwrap_or(MatrixTransportError::Permanent),
        HttpError::Cached(error) => classify_http_error(error),
        HttpError::IntoHttp(_) | HttpError::RefreshToken(_) => MatrixTransportError::Permanent,
        #[cfg(target_os = "android")]
        HttpError::VerifierBuilder(_) => MatrixTransportError::Permanent,
    }
}

fn classify_http_status(status: u16) -> MatrixTransportError {
    if status == 429 || (500..=599).contains(&status) {
        MatrixTransportError::Retryable
    } else {
        MatrixTransportError::Permanent
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum MatrixSyncExit {
    Cancelled,
    IngressFenced,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, thiserror::Error)]
pub enum MatrixSdkError {
    #[error("invalid Matrix sidecar configuration")]
    Configuration,
    #[error("Matrix SDK persistent store initialization failed")]
    Initialization,
    #[error("Matrix authentication failed")]
    Authentication,
    #[error("Matrix session identity differs from the exact binding")]
    IdentityMismatch,
    #[error("Matrix sync failed")]
    Sync,
    #[error("Matrix durable sync checkpoint failed")]
    Store,
    #[error("Matrix durable sync journal capacity is exhausted")]
    CapacityExhausted,
}

impl From<MatrixSidecarConfigError> for MatrixSdkError {
    fn from(_: MatrixSidecarConfigError) -> Self {
        Self::Configuration
    }
}

fn verify_session_identity(
    config: &MatrixSidecarConfig,
    session: &MatrixSession,
) -> Result<(), MatrixSdkError> {
    if session.meta.user_id.as_str() != config.binding.expected_mxid.as_str()
        || session.meta.device_id.as_str() != config.binding.expected_device_id.as_str()
    {
        return Err(MatrixSdkError::IdentityMismatch);
    }
    Ok(())
}

fn verify_homeserver(config: &MatrixSidecarConfig, client: &Client) -> Result<(), MatrixSdkError> {
    let expected = Url::parse(config.binding.homeserver.as_str())
        .map_err(|_| MatrixSdkError::Configuration)?;
    if client.homeserver() != expected {
        return Err(MatrixSdkError::IdentityMismatch);
    }
    Ok(())
}

fn load_session(path: &std::path::Path) -> Result<Option<MatrixSession>, MatrixSdkError> {
    let metadata = match std::fs::symlink_metadata(path) {
        Ok(metadata) => metadata,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(None),
        Err(_) => return Err(MatrixSdkError::Initialization),
    };
    if !metadata.file_type().is_file()
        || !session_file_is_single_link(&metadata)
        || metadata.len() == 0
        || metadata.len() > MATRIX_SESSION_MAX_BYTES
        || !session_file_mode_is_private(&metadata)
    {
        return Err(MatrixSdkError::Initialization);
    }
    serde_json::from_slice(&std::fs::read(path).map_err(|_| MatrixSdkError::Initialization)?)
        .map(Some)
        .map_err(|_| MatrixSdkError::Initialization)
}

fn persist_session(path: &std::path::Path, session: &MatrixSession) -> Result<(), MatrixSdkError> {
    let parent = path.parent().ok_or(MatrixSdkError::Initialization)?;
    let parent_metadata =
        std::fs::symlink_metadata(parent).map_err(|_| MatrixSdkError::Initialization)?;
    if !parent_metadata.file_type().is_dir() {
        return Err(MatrixSdkError::Initialization);
    }
    if let Ok(metadata) = std::fs::symlink_metadata(path) {
        if !metadata.file_type().is_file()
            || !session_file_is_single_link(&metadata)
            || !session_file_mode_is_private(&metadata)
        {
            return Err(MatrixSdkError::Initialization);
        }
    } else if path.exists() {
        return Err(MatrixSdkError::Initialization);
    }
    let bytes = serde_json::to_vec(session).map_err(|_| MatrixSdkError::Initialization)?;
    if bytes.is_empty() || bytes.len() as u64 > MATRIX_SESSION_MAX_BYTES {
        return Err(MatrixSdkError::Initialization);
    }
    let file_name = path
        .file_name()
        .and_then(|name| name.to_str())
        .ok_or(MatrixSdkError::Initialization)?;
    let temporary = parent.join(format!(
        ".{file_name}.{}-{}.tmp",
        std::process::id(),
        system_time_ms().map_err(|_| MatrixSdkError::Initialization)?
    ));
    let result = (|| -> Result<(), MatrixSdkError> {
        let mut options = OpenOptions::new();
        options.write(true).create_new(true);
        #[cfg(unix)]
        {
            use std::os::unix::fs::OpenOptionsExt;
            options.mode(0o600);
        }
        let mut output = options
            .open(&temporary)
            .map_err(|_| MatrixSdkError::Initialization)?;
        output
            .write_all(&bytes)
            .map_err(|_| MatrixSdkError::Initialization)?;
        output
            .sync_all()
            .map_err(|_| MatrixSdkError::Initialization)?;
        drop(output);
        std::fs::rename(&temporary, path).map_err(|_| MatrixSdkError::Initialization)?;
        std::fs::File::open(parent)
            .and_then(|directory| directory.sync_all())
            .map_err(|_| MatrixSdkError::Initialization)?;
        Ok(())
    })();
    if result.is_err() {
        let _ = std::fs::remove_file(&temporary);
    }
    result
}

#[cfg(unix)]
fn session_file_mode_is_private(metadata: &std::fs::Metadata) -> bool {
    use std::os::unix::fs::PermissionsExt;

    metadata.permissions().mode() & 0o777 == 0o600
}

#[cfg(unix)]
fn session_file_is_single_link(metadata: &std::fs::Metadata) -> bool {
    use std::os::unix::fs::MetadataExt;

    metadata.nlink() == 1
}

#[cfg(not(unix))]
fn session_file_is_single_link(_metadata: &std::fs::Metadata) -> bool {
    true
}

#[cfg(not(unix))]
fn session_file_mode_is_private(_metadata: &std::fs::Metadata) -> bool {
    true
}

fn bounded_sync_settings(config: &MatrixSidecarConfig) -> Result<SyncSettings, MatrixSdkError> {
    let mut definition = FilterDefinition::default();
    definition.room.rooms = Some(
        config
            .binding
            .allowed_rooms
            .iter()
            .map(|room_id| OwnedRoomId::try_from(room_id.as_str()))
            .collect::<Result<Vec<_>, _>>()
            .map_err(|_| MatrixSdkError::Configuration)?,
    );
    definition.room.timeline.limit = Some(UInt::from(config.sync_timeline_limit));
    definition.room.timeline.types = Some(bounded_timeline_event_types());
    Ok(SyncSettings::new()
        .timeout(config.sync_timeout)
        .filter(Filter::FilterDefinition(definition)))
}

fn bounded_timeline_event_types() -> Vec<String> {
    vec![
        MATRIX_ROOM_MESSAGE_EVENT_TYPE.to_string(),
        MATRIX_ROOM_ENCRYPTED_EVENT_TYPE.to_string(),
    ]
}

fn timeline_event_from_room_id(
    event: OriginalSyncRoomMessageEvent,
    room_id: &str,
) -> Result<MatrixTimelineEvent, MatrixSdkError> {
    let content = serde_json::to_value(&event.content).map_err(|_| MatrixSdkError::Sync)?;
    let payload = serde_json::to_vec(&content).map_err(|_| MatrixSdkError::Sync)?;
    let mentioned_user_ids = parse_mentioned_users(&content)?;
    Ok(MatrixTimelineEvent {
        event_id: MatrixEventId::parse(event.event_id.as_str())
            .map_err(|_| MatrixSdkError::Sync)?,
        room_id: MatrixRoomId::parse(room_id).map_err(|_| MatrixSdkError::Sync)?,
        sender: MatrixUserId::parse(event.sender.as_str()).map_err(|_| MatrixSdkError::Sync)?,
        event_type: MATRIX_ROOM_MESSAGE_EVENT_TYPE.to_string(),
        payload,
        mentioned_user_ids,
        origin_server_ts_ms: u64::from(event.origin_server_ts.get()),
        received_at_ms: system_time_ms()?,
    })
}

fn normalized_sync_events(
    response: &matrix_sdk::sync::SyncResponse,
    ingress: &MatrixIngress,
    received_at_ms: u64,
) -> Result<Vec<codex_hepta_matrix_store::InboxDraft>, MatrixSdkError> {
    let mut drafts = Vec::new();
    for (room_id, room) in &response.rooms.joined {
        for event in &room.timeline.events {
            let deserialized = match event.raw().deserialize() {
                Ok(event) => event,
                Err(_) => {
                    ingress.record_malformed_event();
                    continue;
                }
            };
            let event = match deserialized {
                AnySyncTimelineEvent::MessageLike(AnySyncMessageLikeEvent::RoomMessage(
                    SyncMessageLikeEvent::Original(event),
                )) => event,
                // The allowlist deliberately includes ciphertext so the SDK
                // can decrypt it. If it remains encrypted here, key recovery
                // is incomplete; never advance the Hepta checkpoint past it.
                AnySyncTimelineEvent::MessageLike(AnySyncMessageLikeEvent::RoomEncrypted(_)) => {
                    return Err(MatrixSdkError::Sync);
                }
                _ => {
                    ingress.record_ignored(IngressIgnoredReason::UnsupportedMessageType);
                    continue;
                }
            };
            if !is_text_message(&event.content) {
                ingress.record_ignored(IngressIgnoredReason::UnsupportedMessageType);
                continue;
            }
            let mut event = match timeline_event_from_room_id(event, room_id.as_str()) {
                Ok(event) => event,
                Err(_) => {
                    ingress.record_malformed_event();
                    continue;
                }
            };
            event.received_at_ms = received_at_ms;
            if let Ok(draft) = ingress.prepare(event) {
                drafts.push(draft);
            }
        }
    }
    Ok(drafts)
}

fn is_text_message(content: &RoomMessageEventContent) -> bool {
    matches!(&content.msgtype, MessageType::Text(_))
}

fn parse_mentioned_users(content: &Value) -> Result<Vec<MatrixUserId>, MatrixSdkError> {
    let Some(user_ids) = content
        .get("m.mentions")
        .and_then(|mentions| mentions.get("user_ids"))
    else {
        return Ok(Vec::new());
    };
    let user_ids = user_ids.as_array().ok_or(MatrixSdkError::Sync)?;
    user_ids
        .iter()
        .map(|value| {
            value
                .as_str()
                .ok_or(MatrixSdkError::Sync)
                .and_then(|value| MatrixUserId::parse(value).map_err(|_| MatrixSdkError::Sync))
        })
        .collect()
}

fn system_time_ms() -> Result<u64, MatrixSdkError> {
    let millis = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|_| MatrixSdkError::Sync)?
        .as_millis();
    u64::try_from(millis).map_err(|_| MatrixSdkError::Sync)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn send_status_classification_bounds_permanent_and_transient_errors() {
        fn assert_send_sync<T: Send + Sync>() {}

        assert_send_sync::<MatrixSdkClient>();
        assert_eq!(classify_http_status(403), MatrixTransportError::Permanent);
        assert_eq!(classify_http_status(404), MatrixTransportError::Permanent);
        assert_eq!(classify_http_status(429), MatrixTransportError::Retryable);
        assert_eq!(classify_http_status(500), MatrixTransportError::Retryable);
        assert_eq!(classify_http_status(503), MatrixTransportError::Retryable);
    }

    #[test]
    fn ingress_accepts_only_text_message_content() {
        assert!(is_text_message(&RoomMessageEventContent::text_plain(
            "hello"
        )));
        assert!(!is_text_message(&RoomMessageEventContent::notice_plain(
            "notice"
        )));
    }

    #[test]
    fn logical_stream_revision_uses_matrix_replace_content() {
        let root = MatrixEventId::parse("$root:example.test").expect("valid event id");
        let content = outbound_message_content("complete response", Some(&root));
        assert_eq!(content["body"], "complete response");
        assert_eq!(content["m.new_content"]["body"], "complete response");
        assert_eq!(content["m.relates_to"]["rel_type"], "m.replace");
        assert_eq!(content["m.relates_to"]["event_id"], root.as_str());
        let root_content = outbound_message_content("first response", None);
        assert!(root_content.get("m.relates_to").is_none());
    }

    #[test]
    fn missing_hepta_checkpoint_never_reuses_the_sdk_cursor() {
        assert!(matches!(hepta_sync_token(None), SyncToken::NoToken));
    }

    #[test]
    fn bounded_sync_keeps_ciphertext_needed_for_sdk_decryption() {
        assert_eq!(
            bounded_timeline_event_types(),
            vec![
                MATRIX_ROOM_MESSAGE_EVENT_TYPE.to_string(),
                MATRIX_ROOM_ENCRYPTED_EVENT_TYPE.to_string(),
            ]
        );
    }
}
