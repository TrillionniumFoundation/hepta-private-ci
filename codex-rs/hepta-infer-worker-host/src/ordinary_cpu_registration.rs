//! Fixed, bounded ordinary-child metadata; no authority or execution API.

use codex_hepta_memory::PRODUCTION_DURABLE_WRITER_NAMESPACE;
use codex_hepta_memory::PRODUCTION_DURABLE_WRITER_SCHEMA_VERSION;
use codex_hepta_memory::ProductionDispatchRequest;
use codex_hepta_operations::OperationIntentV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use std::path::PathBuf;
use std::time::Duration;

pub const DESTINATION: &str = "infer-worker-host.ordinary-cpu.v1";
pub const TOPIC: &str = "hepta.ordinary-cpu.exit.v1";

/// Trusted host registration, frozen before any signed request is prepared.
/// This scope observes ordinary child exit only; it does not enforce U/C/A caps.
pub struct OrdinaryCpuBinding {
    pub subject_id: StableId,
    pub scope_digest: Digest32,
    pub policy_generation: Generation,
    pub source_digest: Digest32,
    pub worker_id: StableId,
    pub profile_id: StableId,
    pub observer_deadline: Duration,
}

/// Fixed local deployment configuration. Request bytes cannot select a command.
/// The host must keep its executable/deployment immutable and independently
/// authenticate its declared source identity; a path/digest is not that proof.
pub struct OrdinaryCpuRegistration {
    binding: OrdinaryCpuBinding,
    program: PathBuf,
    arguments: Vec<String>,
}

impl OrdinaryCpuRegistration {
    pub fn new(
        binding: OrdinaryCpuBinding,
        program: PathBuf,
        arguments: Vec<String>,
    ) -> Result<Self, String> {
        if !program.is_absolute()
            || program.as_os_str().len() > 4096
            || program.as_os_str().as_encoded_bytes().contains(&0)
            || arguments.len() > 8
            || arguments
                .iter()
                .any(|arg| arg.len() > 256 || arg.contains('\0'))
            || binding.source_digest.is_zero()
            || binding.scope_digest.is_zero()
            || binding.observer_deadline.is_zero()
            || binding.observer_deadline > Duration::from_secs(8)
        {
            return Err("invalid or unbounded ordinary CPU registration".to_owned());
        }
        if program.to_str().is_none() {
            return Err("ordinary CPU program must have an exact UTF-8 spelling".to_owned());
        }
        Ok(Self {
            binding,
            program,
            arguments,
        })
    }

    pub fn payload_json(&self) -> Result<String, String> {
        let command_bytes =
            serde_json::to_vec(&(&self.program, &self.arguments)).map_err(|e| e.to_string())?;
        Ok(serde_json::json!({
            "schema_version": 1,
            "scope": "ordinary_child_exit_only",
            "worker_id": self.binding.worker_id.as_str(),
            "source_digest": self.binding.source_digest.to_string(),
            "profile_id": self.binding.profile_id.as_str(),
            "command_digest": Digest32::of_bytes(&command_bytes).to_string(),
            "observer_deadline_ns": self.binding.observer_deadline.as_nanos() as u64,
        })
        .to_string())
    }

    pub fn operation(&self, operation_id: StableId) -> Result<OperationIntentV1, String> {
        OperationIntentV1::new(
            operation_id,
            self.binding.subject_id.clone(),
            StableId::new(DESTINATION).map_err(|e| e.to_string())?,
            Digest32::of_bytes(self.payload_json()?.as_bytes()),
            self.binding.scope_digest,
            self.binding.policy_generation,
            /*expected_predecessor*/ None,
        )
        .map_err(|e| e.to_string())
    }

    /// Validate the registered bytes and complete canonical intent without
    /// granting any authority or entering a worker.
    pub fn validate(
        &self,
        request: &ProductionDispatchRequest,
    ) -> Result<OperationIntentV1, String> {
        if request.occurrence_key.len() > 128
            || request.lease_id.is_empty()
            || request.lease_id.len() > 128
        {
            return Err("unbounded ordinary CPU operation or lease identity".to_owned());
        }
        let intent =
            self.operation(StableId::new(&request.occurrence_key).map_err(|e| e.to_string())?)?;
        if request.schema_version != PRODUCTION_DURABLE_WRITER_SCHEMA_VERSION
            || request.namespace != PRODUCTION_DURABLE_WRITER_NAMESPACE
            || request.topic != TOPIC
            || request.idempotency_key != request.occurrence_key
            || request.payload_json != self.payload_json()?
            || request.payload_sha256.as_str() != intent.payload_digest().to_string()
            || request.operation_subject_id != intent.subject_id().as_str()
            || request.operation_destination_id != DESTINATION
            || request.operation_scope_sha256.as_str() != intent.scope_digest().to_string()
            || request.operation_policy_generation != intent.policy_generation().get()
            || request.expected_predecessor_sha256.is_some()
            || request.operation_semantic_sha256.as_str() != intent.semantic_digest().to_string()
        {
            return Err(
                "ordinary CPU request differs from its complete registered intent".to_owned(),
            );
        }
        Ok(intent)
    }
}

#[cfg(test)]
#[path = "ordinary_cpu_registration_tests.rs"]
mod tests;
