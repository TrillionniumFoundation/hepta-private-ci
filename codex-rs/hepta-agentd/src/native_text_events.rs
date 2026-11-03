//! Route provisional native text through the original Core task's UI channel.

use std::sync::Arc;

use anyhow::Context;
use anyhow::Result;
use anyhow::ensure;
use codex_core::hosted_turn::HostedTextDelta;
use codex_core::hosted_turn::HostedTurnEntry;
use codex_hepta_native_agent::NativeEvent;
use codex_hepta_native_agent::NativeEventSink;
use codex_hepta_native_agent::TurnBinding;
use codex_hepta_native_agent::TurnState;
use codex_protocol::ResponseItemId;
use codex_protocol::models::MessagePhase;

use crate::NativeTurnAnchorV1;
use crate::native_ports::NativeEntryOwner;

pub(crate) struct NativeUiEvents {
    binding: TurnBinding,
    original_prefix: usize,
    namespace: String,
    entry: Option<Arc<HostedTurnEntry>>,
}

impl NativeUiEvents {
    pub(crate) fn new(
        anchor: &NativeTurnAnchorV1,
        turn: &TurnState,
        owner: &NativeEntryOwner,
    ) -> Result<Self> {
        let original = anchor
            .run
            .as_ref()
            .context("native text lost original context binding")?;
        let digest = anchor
            .rendered_context_sha256
            .as_deref()
            .unwrap_or(&original.context_digest);
        let original_prefix = crate::native_history::original_prefix_len(&turn.context, digest)?;
        let namespace = crate::native_history::output_namespace(&anchor.checkpoint)?;
        let entry = match owner {
            NativeEntryOwner::Core(entry) => Some(Arc::clone(entry)),
            NativeEntryOwner::Agentd => None,
        };
        Ok(Self {
            binding: turn.binding.clone(),
            original_prefix,
            namespace,
            entry,
        })
    }
}

impl NativeEventSink for NativeUiEvents {
    async fn emit(&self, binding: &TurnBinding, event: NativeEvent) -> Result<()> {
        ensure!(
            binding == &self.binding,
            "native text changed its original turn"
        );
        let Some(entry) = &self.entry else {
            return Ok(());
        };
        let NativeEvent::TextDelta(delta) = event;
        let ordinal = delta
            .context_index
            .checked_sub(self.original_prefix)
            .context("native text attempted to replace original input")?;
        let phase = delta
            .phase
            .map(|phase| serde_json::from_value::<MessagePhase>(serde_json::Value::String(phase)))
            .transpose()?;
        let item_id =
            ResponseItemId::with_suffix("msg", format!("{}_{ordinal}", self.namespace)).to_string();
        entry
            .emit_text_delta(HostedTextDelta {
                item_id,
                text: delta.text,
                phase,
            })
            .await?;
        Ok(())
    }
}
