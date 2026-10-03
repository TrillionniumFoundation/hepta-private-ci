//! Registered iteration wire profile. Structural decoding and Generator evidence
//! never grant path, execution, selection, promotion or release authority.

use std::collections::BTreeSet;
use std::str::FromStr;

use codex_hepta_agent_components::learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_agent_components::learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_agent_components::learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_agent_components::learning_ledger::VerifiedLearningEvidenceV1;
use codex_hepta_agent_components::types::Digest32;
use codex_hepta_agent_components::types::StableId;
use serde::Deserialize;
use serde::Serialize;

const MAX_ENCODED_BYTES: usize = 262_144;
const COMPUTE_PROFILE: &str = "hepta.iteration-compute-budget.v1";

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct ComputeBudget {
    profile: String,
    maximum_parallel_sandboxes: u8,
    maximum_memory_bytes: u64,
    maximum_processes: u32,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct Envelope {
    envelope_id: String,
    base_commit: String,
    base_tree: String,
    objective_digest: String,
    grammar_digest: String,
    allowed_paths: Vec<String>,
    denied_authorities: Vec<String>,
    maximum_files: u32,
    maximum_bytes: u64,
    maximum_candidates: u32,
    wall_time_micros: u64,
    #[serde(deserialize_with = "deserialize_object")]
    compute_budget: ComputeBudget,
    mandatory_checks: Vec<String>,
    expires_unix_ms: u64,
}

/// Immutable canonical profile with all registered fields retained. It is not
/// convertible to the older authority-free Rust subset: that would lose policy.
#[derive(Clone, Debug)]
pub struct CanonicalIterationEnvelopeV1 {
    envelope: Envelope,
    bytes: Vec<u8>,
    digest: Digest32,
}

/// Borrowed policy from the validated canonical envelope. Consumers enforce
/// these bounds through their original execution owners and retain the exact
/// envelope digest; this view itself grants no execution authority.
#[derive(Clone, Copy, Debug)]
pub struct CanonicalIterationPolicyV1<'a> {
    pub envelope_id: &'a str,
    pub base_commit: &'a str,
    pub base_tree: &'a str,
    pub objective_digest: &'a str,
    pub grammar_digest: &'a str,
    pub allowed_paths: &'a [String],
    pub denied_authorities: &'a [String],
    pub maximum_files: u32,
    pub maximum_bytes: u64,
    pub maximum_candidates: u32,
    pub wall_time_micros: u64,
    pub compute_budget: CanonicalIterationComputeBudgetV1,
    pub mandatory_checks: &'a [String],
    pub expires_unix_ms: u64,
}

/// Declared compute ceilings from the registered, validated budget profile.
#[derive(Clone, Copy, Debug)]
pub struct CanonicalIterationComputeBudgetV1 {
    pub maximum_parallel_sandboxes: u8,
    pub maximum_memory_bytes: u64,
    pub maximum_processes: u32,
}

impl CanonicalIterationEnvelopeV1 {
    pub fn decode(bytes: &[u8]) -> Result<Self, String> {
        if bytes.is_empty() || bytes.len() > MAX_ENCODED_BYTES {
            return Err("iteration envelope byte limit".to_string());
        }
        let mut deserializer = serde_json::Deserializer::from_slice(bytes);
        let envelope: Envelope = deserialize_object(&mut deserializer)
            .map_err(|error| format!("invalid iteration envelope: {error}"))?;
        deserializer.end().map_err(|error| error.to_string())?;
        envelope.validate()?;
        // Sort recursively even when dependency feature unification enables
        // serde_json preserve_order; incoming field order is never semantic.
        let mut value = serde_json::to_value(&envelope).map_err(|error| error.to_string())?;
        value.sort_all_objects();
        let bytes = serde_json::to_vec(&value).map_err(|error| error.to_string())?;
        let digest = Digest32::of_bytes(&bytes);
        Ok(Self {
            envelope,
            bytes,
            digest,
        })
    }

    pub fn canonical_bytes(&self) -> &[u8] {
        &self.bytes
    }

    pub fn signing_payload(&self) -> Vec<u8> {
        let mut payload = b"hepta.agentd.iteration-envelope.v1\0".to_vec();
        payload.extend_from_slice(&self.bytes);
        payload
    }

    pub fn digest(&self) -> Digest32 {
        self.digest
    }

    pub fn policy(&self) -> CanonicalIterationPolicyV1<'_> {
        let envelope = &self.envelope;
        CanonicalIterationPolicyV1 {
            envelope_id: &envelope.envelope_id,
            base_commit: &envelope.base_commit,
            base_tree: &envelope.base_tree,
            objective_digest: &envelope.objective_digest,
            grammar_digest: &envelope.grammar_digest,
            allowed_paths: &envelope.allowed_paths,
            denied_authorities: &envelope.denied_authorities,
            maximum_files: envelope.maximum_files,
            maximum_bytes: envelope.maximum_bytes,
            maximum_candidates: envelope.maximum_candidates,
            wall_time_micros: envelope.wall_time_micros,
            compute_budget: CanonicalIterationComputeBudgetV1 {
                maximum_parallel_sandboxes: envelope.compute_budget.maximum_parallel_sandboxes,
                maximum_memory_bytes: envelope.compute_budget.maximum_memory_bytes,
                maximum_processes: envelope.compute_budget.maximum_processes,
            },
            mandatory_checks: &envelope.mandatory_checks,
            expires_unix_ms: envelope.expires_unix_ms,
        }
    }

    /// Authenticate this exact envelope as a Generator submission against the
    /// real existing verifier and an independently supplied host policy pin.
    /// The pin must come from owner-authorized configuration, never the request.
    /// All principal/evidence timestamps and this clock are Unix milliseconds,
    /// matching PlasticityRuntimeOwnerV1. Never rescale already signed evidence.
    /// This method does not manufacture an owner authorization or run anything.
    pub fn verify_generator_submission(
        &self,
        expected_host_envelope: Digest32,
        verifier: &LearningEvidenceVerifierV1,
        evidence: &SignedLearningEvidenceV1,
        now_unix_ms: u64,
    ) -> Result<VerifiedLearningEvidenceV1, String> {
        if expected_host_envelope.is_zero() || self.digest != expected_host_envelope {
            return Err("iteration envelope differs from host policy pin".to_string());
        }
        if now_unix_ms >= self.envelope.expires_unix_ms {
            return Err("iteration envelope expired".to_string());
        }
        let objective = Digest32::from_str(&self.envelope.objective_digest)
            .map_err(|error| error.to_string())?;
        if objective != verifier.objective_digest() {
            return Err("iteration objective differs from current trust".to_string());
        }
        verifier
            .verify(
                LearningEvidenceRoleV1::Generator,
                evidence,
                &self.signing_payload(),
                now_unix_ms,
            )
            .map_err(|error| error.to_string())
    }
}

impl Envelope {
    fn validate(&self) -> Result<(), String> {
        StableId::new(&self.envelope_id).map_err(|error| error.to_string())?;
        for revision in [&self.base_commit, &self.base_tree] {
            // Git object identity stays textual and algorithm-length explicit;
            // a 40-character SHA-1 must not be padded into a fake SHA-256.
            if !matches!(revision.len(), 40 | 64)
                || !revision
                    .bytes()
                    .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
                || revision.bytes().all(|byte| byte == b'0')
            {
                return Err("invalid lowercase Git object identity".to_string());
            }
        }
        for digest in [&self.objective_digest, &self.grammar_digest] {
            if Digest32::from_str(digest)
                .map_err(|error| error.to_string())?
                .is_zero()
            {
                return Err("zero iteration digest".to_string());
            }
        }
        bounded_strings(&self.allowed_paths, 32_768)?;
        bounded_strings(&self.denied_authorities, 8_192)?;
        bounded_strings(&self.mandatory_checks, 32_768)?;
        for path in &self.allowed_paths {
            if path.starts_with('/')
                || path.contains(':')
                || path.contains('\\')
                || path
                    .split('/')
                    .any(|part| part.is_empty() || part == "." || part == "..")
                || path
                    .bytes()
                    .any(|byte| matches!(byte, b'*' | b'?' | b'[' | b']'))
            {
                return Err(
                    "allowed path must be an exact relative path or directory prefix".to_string(),
                );
            }
        }
        let budget = &self.compute_budget;
        if self.maximum_files == 0
            || self.maximum_files > 100
            || self.maximum_bytes == 0
            || self.maximum_bytes > 1_048_576
            || self.maximum_candidates == 0
            || self.maximum_candidates > 32
            || self.wall_time_micros == 0
            || self.expires_unix_ms == 0
            || budget.profile != COMPUTE_PROFILE
            || budget.maximum_parallel_sandboxes == 0
            || budget.maximum_parallel_sandboxes > 8
            || budget.maximum_memory_bytes == 0
            || budget.maximum_processes == 0
        {
            return Err("invalid iteration resource bound or compute profile".to_string());
        }
        Ok(())
    }
}

// Derived structs also accept positional sequences. Require map access before
// delegating to their generated field visitor, preserving duplicate rejection.
fn deserialize_object<'de, D, T>(deserializer: D) -> Result<T, D::Error>
where
    D: serde::Deserializer<'de>,
    T: Deserialize<'de>,
{
    struct ObjectVisitor<T>(std::marker::PhantomData<T>);
    impl<'de, T: Deserialize<'de>> serde::de::Visitor<'de> for ObjectVisitor<T> {
        type Value = T;

        fn expecting(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
            formatter.write_str("a JSON object with named fields")
        }

        fn visit_map<A: serde::de::MapAccess<'de>>(self, map: A) -> Result<T, A::Error> {
            T::deserialize(serde::de::value::MapAccessDeserializer::new(map))
        }
    }
    deserializer.deserialize_map(ObjectVisitor(std::marker::PhantomData))
}

fn bounded_strings(values: &[String], maximum_bytes: usize) -> Result<(), String> {
    if values.is_empty()
        || values.len() > 256
        || values.iter().any(|value| {
            value.is_empty() || value.len() > 4096 || value.chars().any(char::is_control)
        })
        || values.iter().collect::<BTreeSet<_>>().len() != values.len()
        || serde_json::to_vec(values)
            .map_err(|error| error.to_string())?
            .len()
            > maximum_bytes
    {
        return Err("invalid bounded iteration policy array".to_string());
    }
    Ok(())
}

#[cfg(test)]
#[path = "iteration_envelope_wire_tests.rs"]
mod tests;
