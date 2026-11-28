//! Bounded request correlation for the fixed native material owner. None of
//! these wire fields is a grant, a fresh journal receipt or a use capability.
use super::*;
use codex_hepta_contracts::FinalUseBinding;

const SCHEMA: &str = "hepta.paired-training-read.v1";
pub(crate) const FRAME_BOUND: usize = 65_536;

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct PairedTrainingReadRequest {
    schema: String,
    ingress: crate::AuthBusTextIngress,
    payload_json: String,
    binding: FinalUseBinding,
}

impl PairedTrainingReadRequest {
    pub(super) fn from_original(
        verified: &VerifiedPairedTurn,
        payload_json: String,
        binding: FinalUseBinding,
    ) -> Result<Self, AgentdError> {
        let ingress = verified.original_ingress()?.clone();
        let value = Self {
            schema: SCHEMA.into(),
            ingress,
            payload_json,
            binding,
        };
        // The private caller still owns the actual non-replayed writer receipt.
        // Serialization merely correlates it; the Root independently checks
        // the original peer, four live records and original human at first read.
        value.encode()?;
        Ok(value)
    }

    pub(crate) fn decode(raw: &[u8]) -> std::io::Result<Self> {
        if raw.is_empty() || raw.len() > FRAME_BOUND {
            return Err(std::io::Error::other(
                "paired training request exceeds its fixed bound",
            ));
        }
        let value: Self = serde_json::from_slice(raw)?;
        if value.schema != SCHEMA || value.payload_json.len() > 16 * 1024 {
            return Err(std::io::Error::other("unsupported paired training request"));
        }
        Ok(value)
    }

    pub(super) fn encode(&self) -> Result<Vec<u8>, AgentdError> {
        let raw = serde_json::to_vec(self)?;
        if raw.len() > FRAME_BOUND || self.payload_json.len() > 16 * 1024 {
            return Err(invalid("paired training request exceeds its fixed bound"));
        }
        Ok(raw)
    }

    pub(crate) fn ingress(&self) -> &crate::AuthBusTextIngress {
        &self.ingress
    }

    /// An untrusted reference only. The caller must reconstruct and compare
    /// the complete registered payload and verify the original retained human.
    pub(crate) fn proposed_original_turn(&self) -> std::io::Result<String> {
        let payload: serde_json::Value = serde_json::from_str(&self.payload_json)?;
        payload
            .get("identity")
            .and_then(|value| value.get("turn"))
            .and_then(serde_json::Value::as_str)
            .filter(|turn| !turn.is_empty() && turn.len() <= 128)
            .map(str::to_owned)
            .ok_or_else(|| std::io::Error::other("missing bounded original turn reference"))
    }

    /// Exact correlation with the already registered Root metadata. The digest
    /// duplicates the original v2 outbox framing only for comparison with the
    /// real writer result; it never substitutes for the original authorization.
    pub(crate) fn verify_registered(
        &self,
        registration: &crate::HostAuthorityPairedRegistration,
        writer: &crate::HostAuthorityWriterRegistration,
        proof: &crate::HostSignedWriterAuthorizationV1,
    ) -> std::io::Result<Digest32> {
        let p = &registration.preparation;
        let request = &registration.request;
        let payload = PreparationPayload {
            schema: "hepta.paired-learning.native-preparation.v1".into(),
            identity: request.identity(p).map_err(std::io::Error::other)?,
            original_route: registration.original_route.clone(),
            permission_revision: registration.permission_revision,
            expires_at_ms: registration.human_expires_at_ms,
            statement_sha256: Digest32::of_bytes(
                request.original.usage.consent_text(p.study).as_bytes(),
            )
            .to_string(),
        };
        let expected_payload = serde_json::to_string(&payload)?;
        let scope = Digest32::of_bytes(&serde_json::to_vec(&(
            "hepta.paired-learning.preparation-scope.v1",
            p.study.to_string(),
            p.enrollment.to_string(),
            p.principal_id.as_str(),
        ))?);
        let occurrence = operation_id(request.original.delivery_id);
        let intent = OperationIntentV1::new(
            StableId::new(&occurrence).map_err(std::io::Error::other)?,
            StableId::new(writer.registered_agent_id.as_str()).map_err(std::io::Error::other)?,
            StableId::new(DESTINATION).map_err(std::io::Error::other)?,
            Digest32::of_bytes(expected_payload.as_bytes()),
            scope,
            p.policy_generation,
            /*expected_predecessor*/ None,
        )
        .map_err(std::io::Error::other)?;
        let proof_digest = proof.sha256().map_err(std::io::Error::other)?;
        let payload_digest = intent.payload_digest().to_string();
        let semantic = intent.semantic_digest().to_string();
        let mut framing = Vec::new();
        for part in [
            b"hepta:production-outbox-operation:v2".as_slice(),
            proof_digest.as_str().as_bytes(),
            writer.local_lease_id.as_bytes(),
            occurrence.as_bytes(),
            TOPIC.as_bytes(),
            payload_digest.as_bytes(),
            semantic.as_bytes(),
        ] {
            framing.extend_from_slice(&(part.len() as u64).to_be_bytes());
            framing.extend_from_slice(part);
        }
        framing.push(0); // Original preparation has no predecessor.
        let expected = FinalUseBinding {
            subject_id: writer.registered_agent_id.as_str().into(),
            destination_id: DESTINATION.into(),
            request_sha256: Digest32::of_bytes(&framing).into_array(),
            scope_sha256: scope.into_array(),
            payload_sha256: intent.payload_digest().into_array(),
        };
        if self.schema != SCHEMA
            || self.payload_json != expected_payload
            || self.binding != expected
        {
            return Err(std::io::Error::other(
                "paired training request differs from original durable semantics",
            ));
        }
        Ok(intent.semantic_digest())
    }
}

#[derive(Deserialize, Serialize)]
#[serde(tag = "outcome", rename_all = "snake_case", deny_unknown_fields)]
pub(crate) enum PairedTrainingReadResponse {
    FreshRead {
        original_delivery: String,
        materials_sha256: String,
        failure_base64: String,
        correction_base64: String,
    },
    RetainedReadOnly {
        original_delivery: String,
    },
}
