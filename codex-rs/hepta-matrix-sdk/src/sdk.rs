//! Public Matrix transport boundary. Session/sync ownership stays in the
//! existing private implementation; only this facade exposes physical sending.

use codex_hepta_matrix_protocol::MatrixEventId;
use codex_hepta_matrix_store::MatrixDurableStore;
use codex_hepta_matrix_store::OutboxRecord;
use codex_hepta_paths::HeptaAgentLayout;
use matrix_sdk::config::RequestConfig;
use matrix_sdk::ruma::OwnedRoomId;
use matrix_sdk::ruma::OwnedTransactionId;
use tokio_util::sync::CancellationToken;

use crate::MatrixIngress;
use crate::MatrixOutboundIdentity;
use crate::MatrixOutboundTransport;
use crate::MatrixRawSendSeal;
use crate::MatrixSdkPaths;
use crate::MatrixSendFuture;
use crate::MatrixSession;
use crate::MatrixSidecarConfig;
use crate::MatrixTransportError;
use crate::content::ROOM_MESSAGE_EVENT_TYPE;
use crate::content::outbound_message_content;

// Retain the existing session persistence, durable sync and error classifiers
// byte-for-byte. This module and its Client type cannot escape the facade.
mod implementation {
    include!("sdk_implementation.rs");

    pub(super) fn classify_send_error(error: &MatrixSdkTransportError) -> MatrixTransportError {
        classify_sdk_send_error(error)
    }
}

pub use implementation::MatrixSdkError;
pub use implementation::MatrixSyncExit;

/// Per-Agent SDK client without a public raw-client/ungoverned-send escape.
pub struct MatrixSdkClient {
    inner: implementation::MatrixSdkClient,
}

impl MatrixSdkClient {
    pub async fn restore(
        layout: &HeptaAgentLayout,
        config: MatrixSidecarConfig,
        session: MatrixSession,
        store_passphrase: Option<&str>,
    ) -> Result<Self, MatrixSdkError> {
        implementation::MatrixSdkClient::restore(layout, config, session, store_passphrase)
            .await
            .map(|inner| Self { inner })
    }

    pub async fn login_password(
        layout: &HeptaAgentLayout,
        config: MatrixSidecarConfig,
        password: &str,
        store_passphrase: Option<&str>,
        device_display_name: Option<&str>,
    ) -> Result<(Self, MatrixSession), MatrixSdkError> {
        let (inner, session) = implementation::MatrixSdkClient::login_password(
            layout,
            config,
            password,
            store_passphrase,
            device_display_name,
        )
        .await?;
        Ok((Self { inner }, session))
    }

    pub async fn login_or_restore(
        layout: &HeptaAgentLayout,
        config: MatrixSidecarConfig,
        password: &str,
        store_passphrase: Option<&str>,
        device_display_name: Option<&str>,
    ) -> Result<(Self, MatrixSession), MatrixSdkError> {
        let (inner, session) = implementation::MatrixSdkClient::login_or_restore(
            layout,
            config,
            password,
            store_passphrase,
            device_display_name,
        )
        .await?;
        Ok((Self { inner }, session))
    }

    pub fn config(&self) -> &MatrixSidecarConfig {
        self.inner.config()
    }

    pub fn paths(&self) -> &MatrixSdkPaths {
        self.inner.paths()
    }

    pub async fn sync_durable_until_cancelled(
        &self,
        store: &MatrixDurableStore,
        ingress: &MatrixIngress,
        cancel: &CancellationToken,
    ) -> Result<MatrixSyncExit, MatrixSdkError> {
        self.inner
            .sync_durable_until_cancelled(store, ingress, cancel)
            .await
    }

    pub async fn sync_durable_once(
        &self,
        store: &MatrixDurableStore,
        ingress: &MatrixIngress,
    ) -> Result<(), MatrixSdkError> {
        self.inner.sync_durable_once(store, ingress).await
    }
}

impl MatrixOutboundTransport for MatrixSdkClient {
    fn identity(&self) -> Result<MatrixOutboundIdentity, MatrixTransportError> {
        self.inner.identity()
    }

    fn send<'a>(
        &'a self,
        record: &'a OutboxRecord,
        _seal: MatrixRawSendSeal,
    ) -> MatrixSendFuture<'a> {
        // Only the module-private authorized adapter can construct the seal.
        // This body is lazy: all physical work begins when the final gate polls
        // the future after another live authority/session/deadline check.
        Box::pin(async move {
            let config = self.config();
            if !config.binding.allowed_rooms.contains(&record.room_id)
                || record.binding_revision != config.binding.revision
                || record.generation != config.matrix_generation
            {
                return Err(MatrixTransportError::Permanent);
            }
            let body = std::str::from_utf8(&record.payload)
                .map_err(|_| MatrixTransportError::Permanent)?;
            let room_id = OwnedRoomId::try_from(record.room_id.as_str())
                .map_err(|_| MatrixTransportError::Permanent)?;
            let room = self
                .inner
                .client()
                .get_room(&room_id)
                .ok_or(MatrixTransportError::Retryable)?;
            let txn_id = OwnedTransactionId::from(record.stable_txn_id.as_str());
            let content = outbound_message_content(body, record.replaces_event_id.as_ref());
            let response = room
                .send_raw(ROOM_MESSAGE_EVENT_TYPE, content)
                .with_transaction_id(&txn_id)
                // The durable owner, not hidden SDK backoff, admits retries.
                .with_request_config(RequestConfig::new().disable_retry())
                .await
                .map_err(|error| implementation::classify_send_error(&error))?;
            let event_id = MatrixEventId::parse(response.response.event_id.as_str())
                .map_err(|_| MatrixTransportError::ResponseLost)?;
            #[cfg(feature = "qualification-failpoints")]
            if crate::qualification::consume_post_send_pre_mark_ack_drop(
                self.paths().root(),
                record,
                &event_id,
            )
            .map_err(|_| MatrixTransportError::ResponseLost)?
            {
                return Err(MatrixTransportError::ResponseLost);
            }
            Ok(event_id)
        })
    }
}
