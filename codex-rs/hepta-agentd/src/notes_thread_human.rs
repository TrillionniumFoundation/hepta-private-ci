//! Link the original Core turn to an original admitted AuthBus input. A Core
//! callback or catalog alone cannot assert a human principal or session.
use codex_app_server_protocol::ThreadItem;
use codex_app_server_protocol::UserInput;
use codex_hepta_evidence::AuthBusDeliveryState;
use codex_hepta_evidence::AuthBusRetainedDelivery;
use codex_hepta_types::Digest32;

use super::*;

/// Created only after original owner reads and Root's current human lookup.
/// The receipt is an ephemeral comparison value, never a reusable grant.
pub(crate) struct VerifiedHumanTurn {
    ingress: crate::AuthBusTextIngress,
    owner: crate::text_session::TextOwnerReceipt,
    route: AgentdTextSessionConfig,
    delivery_id: String,
}

impl VerifiedHumanTurn {
    pub(super) async fn from_original_input(
        adapter: &AgentdNotesLiteralAdapter,
        route: &AgentdTextSessionConfig,
        original: &ThreadItem,
        retained: AuthBusRetainedDelivery,
    ) -> Result<Self, AgentdError> {
        let ingress = original_ingress(route, original, retained)?;
        let owner = adapter.verify_original_human_text(&ingress, route).await?;
        let delivery_id = original_client_id(original)?.to_owned();
        Ok(Self {
            ingress,
            owner,
            route: route.clone(),
            delivery_id,
        })
    }

    pub(crate) fn ingress(&self) -> &crate::AuthBusTextIngress {
        &self.ingress
    }
    pub(crate) fn route(&self) -> &AgentdTextSessionConfig {
        &self.route
    }
    pub(crate) fn owner(&self) -> &crate::text_session::TextOwnerReceipt {
        &self.owner
    }
    pub(super) fn delivery_id(&self) -> &str {
        &self.delivery_id
    }
}

pub(super) fn original_client_id(original: &ThreadItem) -> Result<&str, AgentdError> {
    let ThreadItem::UserMessage {
        client_id: Some(id),
        ..
    } = original
    else {
        return Err(invalid("original turn has no retained AuthBus human input"));
    };
    let digest: Digest32 = id
        .strip_prefix("hepta.authbus:")
        .ok_or_else(|| invalid("direct turn/start is not a human AuthBus delivery"))?
        .parse()
        .map_err(|_| invalid("invalid original AuthBus delivery ID"))?;
    if id != &format!("hepta.authbus:{digest}") {
        return Err(invalid("noncanonical AuthBus client identity"));
    }
    Ok(id)
}

fn original_ingress(
    route: &AgentdTextSessionConfig,
    original: &ThreadItem,
    retained: AuthBusRetainedDelivery,
) -> Result<crate::AuthBusTextIngress, AgentdError> {
    let client_id = original_client_id(original)?;
    if retained.message.claims.subject_id.as_str() != route.agent_id.as_str()
        || retained.message.claims.scope_digest != crate::authbus_ingress::scope(&route.agent_id)
        || retained.status.state != AuthBusDeliveryState::Acked
        || retained.status.acknowledgement.is_none()
        || client_id != format!("hepta.authbus:{}", retained.status.delivery_id)
        || retained.message.delivery_id() != retained.status.delivery_id
    {
        return Err(invalid(
            "original human delivery has no retained Core queue acknowledgement",
        ));
    }
    let body: crate::AuthBusTextBody = serde_json::from_slice(&retained.payload)?;
    if body.thread_id != route.thread_id
        || body.spawn_generation == 0
        || body.spawn_generation > route.spawn_generation
        || crate::authbus_ingress::payload(&body)? != retained.payload
        || Digest32::of_bytes(&retained.payload) != retained.message.claims.payload_digest
    {
        return Err(invalid("original human input payload or route mismatch"));
    }
    let ThreadItem::UserMessage { content, .. } = original else {
        return Err(invalid("not an original user item"));
    };
    if *content
        != vec![UserInput::Text {
            text: body.text.clone(),
            text_elements: vec![],
        }]
    {
        return Err(invalid(
            "original turn text differs from its signed human input",
        ));
    }
    let claims = retained.message.claims;
    Ok(crate::AuthBusTextIngress {
        issuer_id: claims.issuer_id.to_string(),
        key_epoch: claims.key_epoch.get(),
        message_id: claims.message_id.to_string(),
        sequence: claims.sequence,
        expires_at_ms: claims.expires_at_ms,
        signature_hex: retained
            .message
            .signature
            .iter()
            .map(|byte| format!("{byte:02x}"))
            .collect(),
        body,
    })
}

pub(super) fn confirm_original_queue(
    response: &codex_app_server_protocol::ThreadQueueReconcileResponse,
    client_id: &str,
    expected: &str,
    turn_id: &str,
) -> Result<(), AgentdError> {
    if response.client_user_message_id != client_id
        || response.payload_sha256 != expected
        || !matches!(response.outcome, codex_app_server_protocol::ThreadQueueReconcileOutcome::Persisted { turn_id:ref observed } if observed == turn_id)
    {
        return Err(invalid(
            "Core did not confirm this exact admitted human input in the original turn",
        ));
    }
    Ok(())
}

#[cfg(test)]
#[path = "notes_thread_human_tests.rs"]
mod tests;
