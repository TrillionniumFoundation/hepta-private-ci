//! Canonical DATA retained by the original B publication journal. Decoding
//! grants no evaluation, Artifact, selection or publication authority. Readers
//! must retain their original descriptors, witness, scope and signed admission.

use std::io;

use codex_hepta_intelligence_eval::MAX_PRODUCT_EVALUATION_EXECUTION_BYTES_V1;
use codex_hepta_intelligence_eval::SignedEvaluationDecisionV1;
use codex_hepta_neuron::CellBackendManifestV2;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde::Serialize;

const PURPOSE: &str = "hepta.root.independent-b.qualification-publication.v2";

/// Exact publication bytes include the actual native candidate manifest. An
/// external Artifact issuer can read these bytes with the existing witnessed
/// journal codec without reconstructing a manifest or asking B to run again.
#[derive(Clone, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct OriginalRootBPublicationDataV2 {
    schema: u8,
    purpose: String,
    execution: [u8; 32],
    authentication: [u8; 32],
    trust: [u8; 32],
    evidence: [u8; 32],
    manifest_digest: [u8; 32],
    manifest: CellBackendManifestV2,
}

impl OriginalRootBPublicationDataV2 {
    /// This is a bounded data decoder, not proof that a Root owner committed or
    /// acknowledged the supplied bytes. Legacy digest-only records are refused.
    pub fn decode(bytes: &[u8]) -> io::Result<Self> {
        if bytes.is_empty() || bytes.len() > MAX_PRODUCT_EVALUATION_EXECUTION_BYTES_V1 {
            return Err(io::Error::other(
                "original B publication data exceeds bound",
            ));
        }
        let data: Self = serde_json::from_slice(bytes).map_err(io::Error::other)?;
        data.require_shape()?;
        if serde_json::to_vec(&data).map_err(io::Error::other)? != bytes {
            return Err(io::Error::other(
                "original B publication data is not canonical",
            ));
        }
        Ok(data)
    }

    pub fn manifest(&self) -> &CellBackendManifestV2 {
        &self.manifest
    }

    pub fn execution_digest(&self) -> Digest32 {
        Digest32::from_array(self.execution)
    }

    pub fn authentication_digest(&self) -> Digest32 {
        Digest32::from_array(self.authentication)
    }

    pub fn trust_digest(&self) -> Digest32 {
        Digest32::from_array(self.trust)
    }

    pub fn evidence_digest(&self) -> Digest32 {
        Digest32::from_array(self.evidence)
    }

    pub(crate) fn encode_original(
        execution: Digest32,
        decision: &SignedEvaluationDecisionV1,
        manifest: &CellBackendManifestV2,
    ) -> io::Result<Vec<u8>> {
        if decision.decision.authority != AuthorityPosture::DENY_ALL {
            return Err(io::Error::other("original B publication carries authority"));
        }
        let data = Self {
            schema: 2,
            purpose: PURPOSE.into(),
            execution: execution.into_array(),
            authentication: decision.authentication_digest.into_array(),
            trust: decision.trust_digest.into_array(),
            evidence: decision.decision.evidence_digest.into_array(),
            manifest_digest: manifest.digest().map_err(io::Error::other)?,
            manifest: manifest.clone(),
        };
        data.require_shape()?;
        let bytes = serde_json::to_vec(&data).map_err(io::Error::other)?;
        if bytes.len() > MAX_PRODUCT_EVALUATION_EXECUTION_BYTES_V1 {
            return Err(io::Error::other(
                "original B publication data exceeds bound",
            ));
        }
        Ok(bytes)
    }

    fn require_shape(&self) -> io::Result<()> {
        if self.schema != 2
            || self.purpose != PURPOSE
            || [
                self.execution,
                self.authentication,
                self.trust,
                self.evidence,
                self.manifest_digest,
            ]
            .contains(&[0; 32])
            || self.manifest.digest().map_err(io::Error::other)? != self.manifest_digest
        {
            return Err(io::Error::other("original B publication data differs"));
        }
        Ok(())
    }
}

#[cfg(test)]
#[path = "root_independent_b_publication_data_tests.rs"]
mod tests;
