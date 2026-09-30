//! Atomic production composition for canonical intelligence.
//!
//! A caller supplies one already-constructed runner, one host-owned seven-owner
//! invocation factory, one physical execution host and one durable learning
//! runtime.  Installation is all-or-nothing and emits a source-commit-bound
//! receipt.  The receipt grants no runtime authority; it only identifies the
//! exact composition that the existing owner boundaries accepted.

use std::sync::Arc;

use codex_hepta_learning_ledger::RunStartRecordV1;
use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde::Serialize;

use crate::AgentdConfig;
use crate::AgentdError;
use crate::AgentdIdentity;
use crate::AgentdIntelligenceExecutionHostV1;
use crate::AgentdIntelligenceInvocationV1;
use crate::AgentdIntelligenceLearningRuntimeConfigV1;
use crate::AgentdIntelligenceProductRunnerV1;

const COMPOSITION_RECEIPT_SCHEMA_VERSION: u32 = 1;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct AgentdCanonicalIntelligenceCompositionReceiptV1 {
    pub schema_version: u32,
    pub source_commit: String,
    pub agent_id: String,
    pub spawn_generation: u64,
    pub running_generation: u64,
    pub capability_profile_digest: String,
    pub execution_owner_generation: u64,
    pub learning_owner_generation: u64,
    pub composition_digest: String,
}

/// One complete production profile.  Its fields are private so callers cannot
/// install only the effect path or only the recovery path through this API.
pub struct AgentdCanonicalIntelligenceProductionProfileV1<F> {
    runner: Arc<AgentdIntelligenceProductRunnerV1>,
    invocation_factory: F,
    execution_host: Arc<dyn AgentdIntelligenceExecutionHostV1>,
    learning_runtime: AgentdIntelligenceLearningRuntimeConfigV1,
    source_commit: String,
}

impl<F> AgentdCanonicalIntelligenceProductionProfileV1<F>
where
    F: Fn(
            &AgentdIdentity,
            &RunStartRecordV1,
        ) -> Result<AgentdIntelligenceInvocationV1, AgentdError>
        + Send
        + Sync
        + 'static,
{
    pub fn new(
        runner: Arc<AgentdIntelligenceProductRunnerV1>,
        invocation_factory: F,
        execution_host: Arc<dyn AgentdIntelligenceExecutionHostV1>,
        learning_runtime: AgentdIntelligenceLearningRuntimeConfigV1,
        source_commit: impl Into<String>,
    ) -> Result<Self, AgentdError> {
        let source_commit = source_commit.into();
        validate_source_commit(&source_commit)?;
        if !runner.canonical_profile_ready() {
            return Err(AgentdError::Invalid(
                "canonical intelligence production profile requires rollback and hard-timeout containment"
                    .to_string(),
            ));
        }
        if execution_host.owner_generation() != learning_runtime.owner_generation() {
            return Err(AgentdError::GenerationFenced(
                "canonical intelligence execution and learning owners use different generations"
                    .to_string(),
            ));
        }
        Ok(Self {
            runner,
            invocation_factory,
            execution_host,
            learning_runtime,
            source_commit,
        })
    }

    /// Install all four production components and return an immutable identity
    /// receipt. No partially configured `AgentdConfig` is ever returned.
    pub fn install(
        self,
        config: AgentdConfig,
    ) -> Result<
        (
            AgentdConfig,
            AgentdCanonicalIntelligenceCompositionReceiptV1,
        ),
        AgentdError,
    > {
        let identity = config.identity();
        let running_generation = identity
            .spawn_generation
            .checked_add(1)
            .ok_or_else(|| AgentdError::Invalid("agent generation overflow".to_string()))?;
        let execution_owner_generation = self.execution_host.owner_generation();
        let learning_owner_generation = self.learning_runtime.owner_generation();
        if execution_owner_generation != running_generation
            || learning_owner_generation != running_generation
        {
            return Err(AgentdError::GenerationFenced(format!(
                "canonical intelligence production owners must use Running generation {running_generation}"
            )));
        }

        let capability_profile_digest = self.runner.capability_profile_digest();
        let composition_digest = composition_digest(
            &self.source_commit,
            identity.agent_id.as_str(),
            identity.spawn_generation,
            running_generation,
            capability_profile_digest,
            execution_owner_generation,
            learning_owner_generation,
        )?;
        let receipt = AgentdCanonicalIntelligenceCompositionReceiptV1 {
            schema_version: COMPOSITION_RECEIPT_SCHEMA_VERSION,
            source_commit: self.source_commit,
            agent_id: identity.agent_id.as_str().to_string(),
            spawn_generation: identity.spawn_generation,
            running_generation,
            capability_profile_digest: capability_profile_digest.to_string(),
            execution_owner_generation,
            learning_owner_generation,
            composition_digest: composition_digest.to_string(),
        };

        let config =
            config.with_canonical_intelligence_profile(self.runner, self.invocation_factory)?;
        let config = config.with_intelligence_learning_runtime(self.learning_runtime)?;
        let config = config.with_intelligence_execution_host(self.execution_host)?;
        Ok((config, receipt))
    }
}

/// Startup accepts either no canonical profile, a prepare-only runner/provider
/// pair, or the complete production four-tuple. Every half-profile is rejected.
pub(crate) fn validate_runtime_profile_shape(
    runner: bool,
    provider: bool,
    learning: bool,
    execution: bool,
) -> Result<(), AgentdError> {
    if runner != provider {
        return Err(AgentdError::Invalid(
            "canonical intelligence runner and invocation provider must be installed atomically"
                .to_string(),
        ));
    }
    if learning != execution {
        return Err(AgentdError::Invalid(
            "canonical intelligence physical execution and durable learning recovery must be installed together"
                .to_string(),
        ));
    }
    if (learning || execution) && !runner {
        return Err(AgentdError::Invalid(
            "canonical intelligence production owners require the complete runner/provider profile"
                .to_string(),
        ));
    }
    Ok(())
}

fn validate_source_commit(value: &str) -> Result<(), AgentdError> {
    let valid_length = matches!(value.len(), 40 | 64);
    let lowercase_hex = value
        .bytes()
        .all(|byte| byte.is_ascii_digit() || matches!(byte, b'a'..=b'f'));
    if !valid_length || !lowercase_hex {
        return Err(AgentdError::Invalid(
            "canonical intelligence source commit must be a full lowercase Git object id"
                .to_string(),
        ));
    }
    Ok(())
}

#[allow(clippy::too_many_arguments)]
fn composition_digest(
    source_commit: &str,
    agent_id: &str,
    spawn_generation: u64,
    running_generation: u64,
    capability_profile_digest: Digest32,
    execution_owner_generation: u64,
    learning_owner_generation: u64,
) -> Result<Digest32, AgentdError> {
    let mut bytes = b"hepta.agentd.canonical-intelligence-composition.v1\0".to_vec();
    push_string(&mut bytes, source_commit)?;
    push_string(&mut bytes, agent_id)?;
    bytes.extend_from_slice(&spawn_generation.to_be_bytes());
    bytes.extend_from_slice(&running_generation.to_be_bytes());
    bytes.extend_from_slice(capability_profile_digest.as_array());
    bytes.extend_from_slice(&execution_owner_generation.to_be_bytes());
    bytes.extend_from_slice(&learning_owner_generation.to_be_bytes());
    Ok(Digest32::of_bytes(&bytes))
}

fn push_string(bytes: &mut Vec<u8>, value: &str) -> Result<(), AgentdError> {
    let length = u32::try_from(value.len())
        .map_err(|_| AgentdError::Invalid("composition identity is too large".to_string()))?;
    bytes.extend_from_slice(&length.to_be_bytes());
    bytes.extend_from_slice(value.as_bytes());
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn runtime_profile_shape_rejects_every_half_profile() {
        for mask in 0_u8..16 {
            let runner = mask & 1 != 0;
            let provider = mask & 2 != 0;
            let learning = mask & 4 != 0;
            let execution = mask & 8 != 0;
            let expected = [0, 3, 15].contains(&mask);
            assert_eq!(
                validate_runtime_profile_shape(runner, provider, learning, execution).is_ok(),
                expected,
                "unexpected profile result for mask {mask:04b}"
            );
        }
    }

    #[test]
    fn source_commit_and_receipt_digest_are_strict_and_deterministic() {
        let source = "0123456789abcdef0123456789abcdef01234567";
        assert!(validate_source_commit(source).is_ok());
        assert!(validate_source_commit("ABCDEF").is_err());
        assert!(validate_source_commit("0123").is_err());
        let first = composition_digest(
            source,
            "agent-a",
            7,
            8,
            Digest32::of_bytes(b"profile"),
            8,
            8,
        )
        .expect("digest");
        let second = composition_digest(
            source,
            "agent-a",
            7,
            8,
            Digest32::of_bytes(b"profile"),
            8,
            8,
        )
        .expect("digest");
        assert_eq!(first, second);
        assert_ne!(
            first,
            composition_digest(
                source,
                "agent-a",
                7,
                8,
                Digest32::of_bytes(b"different"),
                8,
                8,
            )
            .expect("digest")
        );
    }
}
