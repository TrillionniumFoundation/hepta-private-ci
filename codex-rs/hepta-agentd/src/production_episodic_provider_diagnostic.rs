//! Explicit synthetic interventions for the retained native provider fixture.
//! A native withdrawal occurs after retrieval, inside the fixture claim service,
//! and before the driver's final owner revalidation. This is not owner custody.

use std::sync::Arc;

use codex_hepta_contracts::AgentId;
use codex_hepta_infer_worker_host::native_app_server::NativeContextDelivery;
use codex_hepta_memory::CognitiveAccess;
use codex_hepta_memory::CognitiveScope;
use codex_hepta_memory::ForgetMemoryDraft;
use codex_hepta_memory::LedgerSourceKind;
use codex_hepta_memory::SourceDraft;
use codex_hepta_memory::StableMemoryId;
use serde::Serialize;

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub(super) enum Mode {
    OriginalSmoke,
    Attach,
    Withhold,
    Tombstone,
    CaptureAttach,
    CaptureWithhold,
}

impl Mode {
    pub(super) fn from_environment() -> Result<Self, Box<dyn std::error::Error>> {
        let mode = std::env::var("HEPTA_MEM_NATIVE_INTERVENTION")?;
        let phase = std::env::var("HEPTA_MEM_NATIVE_PHASE")?;
        match (mode.as_str(), phase.as_str()) {
            ("attach", "generate") => Ok(Self::Attach),
            ("withhold", "generate") => Ok(Self::Withhold),
            ("tombstone", "generate") => Ok(Self::Tombstone),
            ("attach", "capture") => Ok(Self::CaptureAttach),
            ("withhold", "capture") => Ok(Self::CaptureWithhold),
            _ => Err("fixed native intervention/phase required".into()),
        }
    }

    pub(super) fn delivery(self) -> NativeContextDelivery {
        match self {
            Self::Withhold | Self::CaptureWithhold => NativeContextDelivery::Withhold,
            Self::OriginalSmoke | Self::Attach | Self::Tombstone | Self::CaptureAttach => {
                NativeContextDelivery::Attach
            }
        }
    }

    pub(super) fn timeout_seconds(self) -> u64 {
        match self {
            Self::OriginalSmoke => 20,
            Self::Attach
            | Self::Withhold
            | Self::Tombstone
            | Self::CaptureAttach
            | Self::CaptureWithhold => 180,
        }
    }
}

pub(super) struct Withdrawal {
    pub(super) host: Arc<crate::AgentdProductionWriterHost>,
    pub(super) agent_id: AgentId,
    pub(super) memory_id: String,
    pub(super) revision: u64,
}

impl Withdrawal {
    pub(super) async fn commit(
        self,
    ) -> Result<serde_json::Value, Box<dyn std::error::Error + Send + Sync>> {
        let before = self.host.writer().recovery_anchor().await?;
        let receipt = self
            .host
            .forget_with_kg(
                &CognitiveAccess::agent_private(self.agent_id),
                &StableMemoryId::parse(&self.memory_id)?,
                self.revision,
                &SourceDraft {
                    scope: CognitiveScope::AgentPrivate,
                    kind: LedgerSourceKind::ExplicitMemoryDirective,
                    event_key: "mem13-withdraw-after-retrieval-before-final-use".into(),
                    content: b"Withdraw the fixture nonce assertion.".to_vec(),
                    observed_at_unix_seconds: 2,
                },
                &ForgetMemoryDraft {
                    scope: CognitiveScope::AgentPrivate,
                    reason: "Withdraw the fixture nonce assertion.".into(),
                    valid_from_unix_seconds: 2,
                    citations: Vec::new(),
                },
            )
            .await?;
        let after = self.host.writer().recovery_anchor().await?;
        if receipt.write.memory.id.revision != self.revision + 1 || before == after {
            return Err("native tombstone did not advance the original owner".into());
        }
        Ok(serde_json::json!({
            "receipt": receipt, "owner_cut_before": before, "owner_cut_after": after,
            "after_retrieval_before_final_revalidation": true, "fixture_only": true,
        }))
    }
}
