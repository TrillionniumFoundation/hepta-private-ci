//! Imports reuse the configured original writer and authenticated source reader.
//! An acknowledgement proves a committed cut, not future source freshness.
use std::sync::Arc;

use codex_hepta_agent_protocol::EpisodicSnapshotImportResult;
use codex_hepta_agent_protocol::MAX_EPISODIC_SNAPSHOT_IMPORT_BYTES;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_memory::CognitiveAccess;
use codex_hepta_memory::CognitiveScope;
use codex_hepta_memory::EpisodicSnapshotVerifier;

use crate::AgentdError;
use crate::AgentdProductionWriterHost;

pub(crate) struct EpisodicImportIngress {
    pub(crate) namespace: String,
    pub(crate) writer: Arc<AgentdProductionWriterHost>,
    pub(crate) verifier: Arc<dyn EpisodicSnapshotVerifier>,
}

impl EpisodicImportIngress {
    pub(crate) async fn import(
        &self,
        snapshot_json: &str,
    ) -> Result<EpisodicSnapshotImportResult, AgentdError> {
        if snapshot_json.len() > MAX_EPISODIC_SNAPSHOT_IMPORT_BYTES {
            return Err(AgentdError::Invalid("episodic control input exceeds 20 KiB".into()));
        }
        let envelope: serde_json::Value = serde_json::from_str(snapshot_json)?;
        if envelope.get("body").and_then(|body| body.get("namespace"))
            .and_then(serde_json::Value::as_str) != Some(self.namespace.as_str())
        {
            return Err(AgentdError::Invalid("episodic namespace is not configured".into()));
        }
        // Identity and scope come from the retained host, never the request.
        let access = CognitiveAccess::agent_private(self.writer.writer().owner_agent_id().clone());
        let receipt = self.writer.import_episodic_snapshot(
            &access,
            &CognitiveScope::AgentPrivate,
            snapshot_json,
            self.verifier.as_ref(),
        ).await?;
        let receipt_sha256 = Sha256Digest::for_bytes(&serde_json::to_vec(&receipt)?);
        let active_records = receipt.bindings.iter().filter(|binding| binding.active).count();
        let retired_records = receipt.bindings.len() - active_records;
        Ok(EpisodicSnapshotImportResult {
            authority_id: receipt.authority_id,
            namespace: receipt.namespace,
            generation: receipt.generation,
            snapshot_sha256: receipt.snapshot_sha256,
            receipt_sha256: receipt_sha256.as_str().to_owned(),
            active_records: u16::try_from(active_records)
                .map_err(|_| AgentdError::Protocol("episodic receipt count exceeds bound".into()))?,
            retired_records: u16::try_from(retired_records)
                .map_err(|_| AgentdError::Protocol("episodic receipt count exceeds bound".into()))?,
        })
    }
}
