//! Actual owner reads for the hosted inference path. Context realization is
//! untrusted data and never provides a final-use grant or execution authority.

use std::io::Read;
use std::path::Path;

use codex_hepta_agentd::AgentdClient;
use codex_hepta_cognitive_types::MemoryRequestV1;
use codex_hepta_context_compiler::MemoryCellEvidenceV1;
use codex_hepta_context_compiler::realize_memory_cell_evidence_v1;

use super::AppServerModelDriver;
use super::Result;

impl AppServerModelDriver {
    /// Bind one typed owner request to this driver. Its operation is resolved
    /// by the configured daemon model, never supplied as caller routing gold.
    /// Admission identity includes the whole request; retries cannot replace it.
    pub fn with_memory_request(mut self, request: MemoryRequestV1) -> Result<Self> {
        request.validate()?;
        if self.memory_request.is_some() {
            return Err("native memory request is already configured".into());
        }
        self.memory_request = Some(request);
        Ok(self)
    }

    pub(super) fn bind_memory_admission(&self, prior_digest: String) -> Result<String> {
        match self.memory_request.as_ref() {
            None => Ok(prior_digest),
            Some(request) => Ok(super::control::digest(&serde_json::to_vec(&(
                "hepta.native-memory-request.v1",
                prior_digest,
                request,
            ))?)),
        }
    }

    pub(super) async fn acquire_memory_evidence(
        &self,
        owner: &AgentdClient,
    ) -> Result<Option<MemoryCellEvidenceV1>> {
        let Some(request) = self.memory_request.as_ref() else {
            return Ok(None);
        };
        let readout = owner.memory_cell_read(request.clone()).await?;
        Ok(Some(realize_memory_cell_evidence_v1(request, &readout)?))
    }

    pub(super) async fn revalidate_memory_evidence(
        &self,
        owner: &AgentdClient,
        attached: &MemoryCellEvidenceV1,
    ) -> Result<()> {
        let current = self
            .acquire_memory_evidence(owner)
            .await?
            .ok_or("native memory request disappeared before final use")?;
        if current.request_digest() != attached.request_digest()
            || current.evidence_digest() != attached.evidence_digest()
            || current.realized() != attached.realized()
        {
            return Err(
                "memory source, selected model or read result changed before final use".into(),
            );
        }
        Ok(())
    }
}

/// Bounded CLI input is a query only. Strict decoding rejects model selection,
/// claimed operation, source registry and authority fields in caller JSON.
pub fn load_native_memory_request_v1(path: &Path) -> Result<MemoryRequestV1> {
    const MAX_REQUEST_BYTES: u64 = 65_536;
    if !path.is_absolute() {
        return Err("--memory-request-file must be absolute".into());
    }
    let mut bytes = Vec::new();
    std::fs::File::open(path)?
        .take(MAX_REQUEST_BYTES + 1)
        .read_to_end(&mut bytes)?;
    if bytes.len() as u64 > MAX_REQUEST_BYTES {
        return Err("native memory request file exceeds 65536 bytes".into());
    }
    Ok(codex_hepta_cognitive_types::decode_memory_request_v1(
        &bytes,
    )?)
}

#[cfg(test)]
#[path = "native_memory_cell_tests.rs"]
mod tests;
