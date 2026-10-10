use serde::Deserialize;
use serde::Serialize;
use sha2::Digest;
use sha2::Sha256;

use crate::Sha256Digest;
use crate::stable_id::parse_prefixed_sha256_id;

pub const PROVIDER_EVIDENCE_SCHEMA_VERSION: u32 = 1;

const MAX_PROVIDER_TEXT_BYTES: usize = 512;
const MAX_PROVIDER_REASON_BYTES: usize = 128;

fn validate_text(value: &str, label: &str, max_bytes: usize) -> Result<(), String> {
    if value.trim().is_empty() || value.len() > max_bytes || value.as_bytes().contains(&0) {
        return Err(format!(
            "{label} must contain 1..={max_bytes} non-NUL bytes"
        ));
    }
    Ok(())
}

fn validate_digest(digest: &Sha256Digest, label: &str) -> Result<(), String> {
    Sha256Digest::parse(digest.as_str().to_string())
        .map(|_| ())
        .map_err(|error| format!("{label}: {error}"))
}

fn canonical_wire_bytes<T: Serialize>(value: &T) -> Result<Vec<u8>, String> {
    serde_json::to_vec(value).map_err(|error| format!("provider wire encoding failed: {error}"))
}

#[derive(Clone, Debug, Deserialize, Eq, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(transparent)]
pub struct RequestBindingId(String);

impl RequestBindingId {
    pub fn for_request(binding: &ProviderRequestBinding) -> Self {
        let schema_version = binding.schema_version.to_string();
        let previous_response_id = binding
            .previous_response_id_sha256
            .as_ref()
            .map_or("", Sha256Digest::as_str);
        let previous_response_present = if binding.previous_response_id_sha256.is_some() {
            "present"
        } else {
            "absent"
        };
        let generate = if binding.generate {
            "generate"
        } else {
            "no_generate"
        };
        let base_parts = [
            schema_version.as_str(),
            binding.thread_id.as_str(),
            binding.turn_id.as_str(),
            binding.host_request_binding_id_sha256.as_str(),
            binding.request_kind.as_str(),
            binding.provider_id.as_str(),
            binding.provider_config_sha256.as_str(),
            binding.model.as_str(),
            binding.transport.as_str(),
            binding.endpoint_sha256.as_str(),
            binding.logical_request_sha256.as_str(),
            binding.wire_semantic_sha256.as_str(),
            previous_response_present,
            previous_response_id,
            generate,
        ];
        if binding.ephemeral_input_sha256.is_none()
            && binding.ephemeral_input_witness_sha256.is_none()
        {
            return Self(format!("provider-request:v1:{}", digest_parts(base_parts)));
        }

        // Lineage two already persisted this exact outer binding. The witness
        // digest owns its own versioned domain, so changing the request-id
        // prefix would only make durable pending and terminal rows unreadable.
        let ephemeral_input = binding
            .ephemeral_input_sha256
            .as_ref()
            .map_or("absent", Sha256Digest::as_str);
        let ephemeral_input_witness = binding
            .ephemeral_input_witness_sha256
            .as_ref()
            .map_or("absent", Sha256Digest::as_str);
        Self(format!(
            "provider-request:v1:{}",
            digest_parts(base_parts.into_iter().chain([
                "ephemeral_input:v1",
                ephemeral_input,
                ephemeral_input_witness,
            ]))
        ))
    }

    pub fn as_str(&self) -> &str {
        &self.0
    }
}

#[derive(Clone, Debug, Deserialize, Eq, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(transparent)]
pub struct ProviderAttemptId(String);

impl ProviderAttemptId {
    pub fn parse(value: impl Into<String>) -> Result<Self, String> {
        parse_prefixed_sha256_id(value, "provider-attempt:v1:", "provider attempt").map(Self)
    }

    pub fn for_send(
        request_binding_id: &RequestBindingId,
        attempt_nonce_sha256: &Sha256Digest,
    ) -> Self {
        Self(format!(
            "provider-attempt:v1:{}",
            digest_parts([request_binding_id.as_str(), attempt_nonce_sha256.as_str()])
        ))
    }

    pub fn as_str(&self) -> &str {
        &self.0
    }
}

#[derive(Clone, Debug, Deserialize, Eq, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(transparent)]
pub struct ProviderReceiptId(String);

impl ProviderReceiptId {
    pub fn for_attempt(attempt_id: &ProviderAttemptId) -> Self {
        Self(format!(
            "provider-receipt:v1:{}",
            digest_parts([attempt_id.as_str()])
        ))
    }

    pub fn as_str(&self) -> &str {
        &self.0
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ProviderRequestKind {
    Turn,
    Prewarm,
    Compaction,
    Memory,
}

impl ProviderRequestKind {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Turn => "turn",
            Self::Prewarm => "prewarm",
            Self::Compaction => "compaction",
            Self::Memory => "memory",
        }
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ProviderTransport {
    Http,
    WebSocket,
}

impl ProviderTransport {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Http => "http",
            Self::WebSocket => "web_socket",
        }
    }
}

/// Stable, secret-free semantic material that identifies one logical provider request.
///
/// Request bodies, prompts, authentication headers, provider tokens, and response text do not
/// belong in this type. Their only permitted representation is a SHA-256 digest.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ProviderRequestBinding {
    pub schema_version: u32,
    pub thread_id: String,
    pub turn_id: String,
    /// Digest of the host-owned retry-stable request binding identity.
    ///
    /// The opaque host identity itself must never cross the Hepta evidence boundary.
    pub host_request_binding_id_sha256: Sha256Digest,
    pub request_kind: ProviderRequestKind,
    pub provider_id: String,
    /// Compatibility-named digest of the versioned, secret-free provider
    /// selector. It must never be derived from credentials, headers, raw
    /// endpoint configuration, query values, or retry policy.
    pub provider_config_sha256: Sha256Digest,
    pub model: String,
    pub transport: ProviderTransport,
    pub endpoint_sha256: Sha256Digest,
    pub logical_request_sha256: Sha256Digest,
    pub wire_semantic_sha256: Sha256Digest,
    /// Digest of the exact host-rendered input scoped to one physical send.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub ephemeral_input_sha256: Option<Sha256Digest>,
    /// Host witness binding ephemeral input to the exact provider attempt.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub ephemeral_input_witness_sha256: Option<Sha256Digest>,
    pub previous_response_id_sha256: Option<Sha256Digest>,
    pub generate: bool,
}

impl ProviderRequestBinding {
    /// Validates the active B3 wire binding without inspecting any secret or
    /// provider response body.  Historical rows may still be decoded by the
    /// evidence projection, but an active adapter must validate before use.
    pub fn validate(&self) -> Result<(), String> {
        if self.schema_version != PROVIDER_EVIDENCE_SCHEMA_VERSION {
            return Err("unsupported provider request schema version".to_string());
        }
        for (label, value) in [
            ("provider thread id", self.thread_id.as_str()),
            ("provider turn id", self.turn_id.as_str()),
            ("provider id", self.provider_id.as_str()),
            ("provider model", self.model.as_str()),
        ] {
            validate_text(value, label, MAX_PROVIDER_TEXT_BYTES)?;
        }
        for (label, digest) in [
            (
                "host request binding digest",
                &self.host_request_binding_id_sha256,
            ),
            ("provider config digest", &self.provider_config_sha256),
            ("provider endpoint digest", &self.endpoint_sha256),
            ("logical request digest", &self.logical_request_sha256),
            ("wire semantic digest", &self.wire_semantic_sha256),
        ] {
            validate_digest(digest, label)?;
        }
        if let Some(previous) = &self.previous_response_id_sha256 {
            validate_digest(previous, "previous response digest")?;
        }
        match (
            &self.ephemeral_input_sha256,
            &self.ephemeral_input_witness_sha256,
        ) {
            (Some(input), Some(witness)) => {
                validate_digest(input, "ephemeral input digest")?;
                validate_digest(witness, "ephemeral input witness digest")?;
            }
            (None, None) => {}
            _ => {
                return Err(
                    "ephemeral input and witness digests must be present together".to_string(),
                );
            }
        }
        Ok(())
    }

    /// Encodes validated bytes for the active provider wire context.  This is
    /// intentionally distinct from the evidence store's sorted projection
    /// bytes and carries no authority or credential material.
    pub fn canonical_wire_bytes(&self) -> Result<Vec<u8>, String> {
        self.validate()?;
        canonical_wire_bytes(self)
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ProviderInvocationIntent {
    pub schema_version: u32,
    pub attempt_id: ProviderAttemptId,
    pub request_binding_id: RequestBindingId,
    pub attempt_nonce_sha256: Sha256Digest,
    pub binding: ProviderRequestBinding,
}

impl ProviderInvocationIntent {
    /// Construct an intent from a host-generated 128-bit per-send nonce.
    ///
    /// The nonce itself is discarded immediately; only its SHA-256 digest can cross the
    /// governance boundary or be persisted.
    pub fn new(attempt_nonce: [u8; 16], binding: ProviderRequestBinding) -> Self {
        let attempt_nonce_sha256 = Sha256Digest::for_bytes(&attempt_nonce);
        Self::from_attempt_id_digest(attempt_nonce_sha256, binding)
    }

    /// Construct an intent from an opaque host-owned per-send attempt identity.
    ///
    /// Only the SHA-256 digest crosses the governance boundary; the host identity is discarded.
    pub fn for_host_attempt_id(host_attempt_id: &str, binding: ProviderRequestBinding) -> Self {
        let attempt_nonce_sha256 = Sha256Digest::for_bytes(host_attempt_id.as_bytes());
        Self::from_attempt_id_digest(attempt_nonce_sha256, binding)
    }

    fn from_attempt_id_digest(
        attempt_nonce_sha256: Sha256Digest,
        binding: ProviderRequestBinding,
    ) -> Self {
        let request_binding_id = RequestBindingId::for_request(&binding);
        let attempt_id = ProviderAttemptId::for_send(&request_binding_id, &attempt_nonce_sha256);
        Self {
            schema_version: PROVIDER_EVIDENCE_SCHEMA_VERSION,
            attempt_id,
            request_binding_id,
            attempt_nonce_sha256,
            binding,
        }
    }

    /// Validates all identity derivations before an adapter boundary is
    /// crossed.  A deserialized or manually forged ID cannot be accepted just
    /// because its string shape looks plausible.
    pub fn validate(&self) -> Result<(), String> {
        if self.schema_version != PROVIDER_EVIDENCE_SCHEMA_VERSION {
            return Err("unsupported provider invocation schema version".to_string());
        }
        self.binding.validate()?;
        validate_digest(&self.attempt_nonce_sha256, "attempt nonce digest")?;
        let expected_binding = RequestBindingId::for_request(&self.binding);
        if self.request_binding_id != expected_binding {
            return Err("request binding id does not bind provider request semantics".to_string());
        }
        let expected_attempt =
            ProviderAttemptId::for_send(&self.request_binding_id, &self.attempt_nonce_sha256);
        if self.attempt_id != expected_attempt {
            return Err("provider attempt id does not bind request and send nonce".to_string());
        }
        Ok(())
    }

    pub fn canonical_wire_bytes(&self) -> Result<Vec<u8>, String> {
        self.validate()?;
        canonical_wire_bytes(self)
    }
}

/// Terminal observation for one provider send attempt.
///
/// `Completed` proves only that the provider emitted its response-completed signal. It is not an
/// effect acknowledgement and does not establish exactly-once execution.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "terminal", rename_all = "snake_case")]
#[serde(deny_unknown_fields)]
pub enum ProviderTerminal {
    Completed {
        response_id_sha256: Sha256Digest,
        response_items_sha256: Sha256Digest,
        token_usage_sha256: Sha256Digest,
        /// Exact provider observation. `None` means the provider omitted the field.
        end_turn: Option<bool>,
    },
    /// Successful unary operation whose provider response contains only items.
    CompletedUnary {
        response_items_sha256: Sha256Digest,
    },
    Rejected {
        reason_code: String,
    },
    NotDispatched {
        reason_code: String,
    },
    Indeterminate {
        reason_code: String,
        partial_response_sha256: Option<Sha256Digest>,
    },
}

impl ProviderTerminal {
    pub const fn kind(&self) -> &'static str {
        match self {
            Self::Completed { .. } | Self::CompletedUnary { .. } => "completed",
            Self::Rejected { .. } => "rejected",
            Self::NotDispatched { .. } => "not_dispatched",
            Self::Indeterminate { .. } => "indeterminate",
        }
    }

    pub fn validate(&self) -> Result<(), String> {
        match self {
            Self::Completed {
                response_id_sha256,
                response_items_sha256,
                token_usage_sha256,
                ..
            } => {
                validate_digest(response_id_sha256, "response id digest")?;
                validate_digest(response_items_sha256, "response items digest")?;
                validate_digest(token_usage_sha256, "token usage digest")?;
            }
            Self::CompletedUnary {
                response_items_sha256,
            } => validate_digest(response_items_sha256, "response items digest")?,
            Self::Rejected { reason_code }
            | Self::NotDispatched { reason_code }
            | Self::Indeterminate { reason_code, .. } => {
                validate_text(
                    reason_code,
                    "provider terminal reason code",
                    MAX_PROVIDER_REASON_BYTES,
                )?;
                if let Self::Indeterminate {
                    partial_response_sha256: Some(partial),
                    ..
                } = self
                {
                    validate_digest(partial, "partial response digest")?;
                }
            }
        }
        Ok(())
    }

    pub fn canonical_wire_bytes(&self) -> Result<Vec<u8>, String> {
        self.validate()?;
        canonical_wire_bytes(self)
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ProviderInvocationReceipt {
    pub schema_version: u32,
    pub receipt_id: ProviderReceiptId,
    pub attempt_id: ProviderAttemptId,
    pub request_binding_id: RequestBindingId,
    pub intent: ProviderInvocationIntent,
    pub terminal: ProviderTerminal,
}

impl ProviderInvocationReceipt {
    pub fn new(intent: ProviderInvocationIntent, terminal: ProviderTerminal) -> Self {
        let attempt_id = intent.attempt_id.clone();
        let request_binding_id = intent.request_binding_id.clone();
        Self {
            schema_version: PROVIDER_EVIDENCE_SCHEMA_VERSION,
            receipt_id: ProviderReceiptId::for_attempt(&attempt_id),
            attempt_id,
            request_binding_id,
            intent,
            terminal,
        }
    }

    pub fn validate(&self) -> Result<(), String> {
        if self.schema_version != PROVIDER_EVIDENCE_SCHEMA_VERSION {
            return Err("unsupported provider receipt schema version".to_string());
        }
        self.intent.validate()?;
        if self.attempt_id != self.intent.attempt_id
            || self.request_binding_id != self.intent.request_binding_id
        {
            return Err("provider receipt does not bind its exact intent".to_string());
        }
        if self.receipt_id != ProviderReceiptId::for_attempt(&self.attempt_id) {
            return Err("provider receipt id does not bind its attempt id".to_string());
        }
        self.terminal.validate()
    }

    pub fn canonical_wire_bytes(&self) -> Result<Vec<u8>, String> {
        self.validate()?;
        canonical_wire_bytes(self)
    }
}

fn digest_parts<'a>(parts: impl IntoIterator<Item = &'a str>) -> String {
    let mut hasher = Sha256::new();
    for part in parts {
        hasher.update((part.len() as u64).to_be_bytes());
        hasher.update(part.as_bytes());
    }
    format!("{:x}", hasher.finalize())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn binding() -> ProviderRequestBinding {
        ProviderRequestBinding {
            schema_version: PROVIDER_EVIDENCE_SCHEMA_VERSION,
            thread_id: "thread-1".to_string(),
            turn_id: "turn-1".to_string(),
            host_request_binding_id_sha256: Sha256Digest::for_bytes(b"host-request-1"),
            request_kind: ProviderRequestKind::Turn,
            provider_id: "provider-1".to_string(),
            provider_config_sha256: Sha256Digest::for_bytes(b"config"),
            model: "model-1".to_string(),
            transport: ProviderTransport::Http,
            endpoint_sha256: Sha256Digest::for_bytes(b"/responses"),
            logical_request_sha256: Sha256Digest::for_bytes(b"logical"),
            wire_semantic_sha256: Sha256Digest::for_bytes(b"wire"),
            ephemeral_input_sha256: None,
            ephemeral_input_witness_sha256: None,
            previous_response_id_sha256: None,
            generate: true,
        }
    }

    #[test]
    fn provider_ids_are_versioned_stable_and_length_delimited() {
        let binding = binding();
        let request_id = RequestBindingId::for_request(&binding);
        let repeated = RequestBindingId::for_request(&binding);
        let left_nonce = Sha256Digest::for_bytes(b"ab:c");
        let right_nonce = Sha256Digest::for_bytes(b"a:bc");
        let left = ProviderAttemptId::for_send(&request_id, &left_nonce);
        let right = ProviderAttemptId::for_send(&request_id, &right_nonce);

        assert_eq!(
            request_id.as_str(),
            "provider-request:v1:af856c7c8c26482cec5a16aeb1c302f126e7eb1091cd4ad1a58b594fc0d40809"
        );
        let serialized = serde_json::to_string(&binding).expect("serialize binding");
        assert!(!serialized.contains("ephemeral_input"));
        let legacy: ProviderRequestBinding =
            serde_json::from_str(&serialized).expect("deserialize binding without optional fields");
        assert!(legacy.ephemeral_input_sha256.is_none());
        assert!(legacy.ephemeral_input_witness_sha256.is_none());
        assert_eq!(request_id, repeated);
        assert!(left.as_str().starts_with("provider-attempt:v1:"));
        assert_ne!(left, right);
        assert!(
            ProviderReceiptId::for_attempt(&left)
                .as_str()
                .starts_with("provider-receipt:v1:")
        );
    }

    #[test]
    fn ephemeral_input_preserves_lineage_two_identity_and_binds_both_digests() {
        let mut binding = binding();
        binding.ephemeral_input_sha256 = Some(Sha256Digest::for_bytes(b"ephemeral-input"));
        binding.ephemeral_input_witness_sha256 =
            Some(Sha256Digest::for_bytes(b"ephemeral-witness"));
        let request_id = RequestBindingId::for_request(&binding);

        assert_eq!(
            request_id.as_str(),
            "provider-request:v1:b7f20b62164f89b8b41023307cbc8380094c6ba750836e31bdb612aac0275344"
        );
        let mut changed_input = binding.clone();
        changed_input.ephemeral_input_sha256 =
            Some(Sha256Digest::for_bytes(b"changed-ephemeral-input"));
        let mut changed_witness = binding.clone();
        changed_witness.ephemeral_input_witness_sha256 =
            Some(Sha256Digest::for_bytes(b"changed-ephemeral-witness"));
        assert_ne!(request_id, RequestBindingId::for_request(&changed_input));
        assert_ne!(request_id, RequestBindingId::for_request(&changed_witness));

        let serialized = serde_json::to_string(&binding).expect("serialize binding");
        assert!(serialized.contains("ephemeral_input_sha256"));
        assert!(serialized.contains("ephemeral_input_witness_sha256"));
    }

    #[test]
    fn orphaned_ephemeral_digest_cannot_alias_an_absent_binding() {
        let v1 = binding();
        let mut orphaned = v1.clone();
        orphaned.ephemeral_input_sha256 = Some(Sha256Digest::for_bytes(b"orphaned"));

        let orphaned_id = RequestBindingId::for_request(&orphaned);
        assert!(orphaned_id.as_str().starts_with("provider-request:v1:"));
        assert_ne!(RequestBindingId::for_request(&v1), orphaned_id);
    }

    #[test]
    fn request_binding_changes_for_websocket_incremental_semantics() {
        let http = binding();
        let mut websocket = http.clone();
        websocket.transport = ProviderTransport::WebSocket;
        websocket.wire_semantic_sha256 = Sha256Digest::for_bytes(b"incremental-wire");
        websocket.previous_response_id_sha256 = Some(Sha256Digest::for_bytes(b"previous"));

        assert_ne!(
            RequestBindingId::for_request(&http),
            RequestBindingId::for_request(&websocket)
        );
    }

    #[test]
    fn host_ids_are_hashed_and_bound_without_persisting_plaintext() {
        let left = binding();
        let mut right = left.clone();
        right.host_request_binding_id_sha256 = Sha256Digest::for_bytes(b"host-request-2");

        let intent = ProviderInvocationIntent::for_host_attempt_id("host-attempt-1", left.clone());

        assert_ne!(
            RequestBindingId::for_request(&left),
            RequestBindingId::for_request(&right)
        );
        assert_eq!(
            intent.attempt_nonce_sha256,
            Sha256Digest::for_bytes(b"host-attempt-1")
        );
        assert_ne!(intent.attempt_nonce_sha256.as_str(), "host-attempt-1");
        assert_ne!(
            intent.binding.host_request_binding_id_sha256.as_str(),
            "host-request-1"
        );
    }

    #[test]
    fn active_provider_wire_rejects_unknown_fields_but_keeps_legacy_optional_decode() {
        let value = serde_json::to_value(binding()).expect("serialize binding");
        let mut unknown = value.clone();
        unknown["future_field"] = serde_json::Value::Bool(true);
        assert!(serde_json::from_value::<ProviderRequestBinding>(unknown).is_err());

        let intent =
            ProviderInvocationIntent::for_host_attempt_id("host-attempt-unknown-field", binding());
        let mut unknown_intent = serde_json::to_value(&intent).expect("serialize intent");
        unknown_intent["future_field"] = serde_json::Value::Bool(true);
        assert!(serde_json::from_value::<ProviderInvocationIntent>(unknown_intent).is_err());

        let mut unknown_terminal = serde_json::to_value(ProviderTerminal::Rejected {
            reason_code: "invalid_grant".to_string(),
        })
        .expect("serialize terminal");
        unknown_terminal["future_field"] = serde_json::Value::Bool(true);
        assert!(serde_json::from_value::<ProviderTerminal>(unknown_terminal).is_err());

        let mut unknown_receipt = serde_json::to_value(ProviderInvocationReceipt::new(
            intent,
            ProviderTerminal::Rejected {
                reason_code: "invalid_grant".to_string(),
            },
        ))
        .expect("serialize receipt");
        unknown_receipt["future_field"] = serde_json::Value::Bool(true);
        assert!(serde_json::from_value::<ProviderInvocationReceipt>(unknown_receipt).is_err());

        let mut legacy = value;
        let object = legacy.as_object_mut().expect("binding object");
        object.remove("ephemeral_input_sha256");
        object.remove("ephemeral_input_witness_sha256");
        let decoded: ProviderRequestBinding =
            serde_json::from_value(legacy).expect("legacy optional fields remain decodable");
        assert!(decoded.ephemeral_input_sha256.is_none());
        assert!(decoded.ephemeral_input_witness_sha256.is_none());
        decoded
            .validate()
            .expect("decoded legacy binding validates");
        assert!(
            !decoded
                .canonical_wire_bytes()
                .expect("canonical wire bytes")
                .is_empty()
        );
    }

    #[test]
    fn provider_wire_validation_fences_identity_and_terminal_bindings() {
        let binding = binding();
        let intent = ProviderInvocationIntent::for_host_attempt_id("host-attempt-1", binding);
        intent.validate().expect("valid intent");
        assert!(
            !intent
                .canonical_wire_bytes()
                .expect("intent wire bytes")
                .is_empty()
        );

        let mut forged_intent = intent.clone();
        forged_intent.binding.provider_id = "provider-forged".to_string();
        assert!(forged_intent.validate().is_err());
        assert!(forged_intent.canonical_wire_bytes().is_err());

        let receipt = ProviderInvocationReceipt::new(
            intent,
            ProviderTerminal::Rejected {
                reason_code: "invalid_grant".to_string(),
            },
        );
        receipt.validate().expect("valid rejected receipt");
        assert!(
            !receipt
                .canonical_wire_bytes()
                .expect("receipt wire bytes")
                .is_empty()
        );

        let mut forged_receipt = receipt.clone();
        forged_receipt.attempt_id = ProviderAttemptId::for_send(
            &forged_receipt.request_binding_id,
            &Sha256Digest::for_bytes(b"different-attempt"),
        );
        assert!(forged_receipt.validate().is_err());

        let mut forged_terminal = receipt;
        forged_terminal.terminal = ProviderTerminal::Rejected {
            reason_code: "   ".to_string(),
        };
        assert!(forged_terminal.validate().is_err());
    }
}
