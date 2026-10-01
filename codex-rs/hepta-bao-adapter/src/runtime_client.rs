//! Enrolled Agent port to the single protected daemon; effect calls never retry.
use crate::ConsumerPortError;
use crate::SecretsRuntimeResponse;
use crate::consumer_port::PreparedConnection;
use crate::runtime_config::runtime_original_id;
use crate::runtime_service::RuntimeRequest;
use serde::Deserialize;
use serde::Serialize;
use std::path::Path;
use std::path::PathBuf;
use std::time::Duration;

#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct SecretsRuntimeClientConfig {
    schema_version: u32,
    agent_uid: u32,
    agent_id: String,
    runtime_uid: u32,
    socket_path: PathBuf,
    operation_timeout_ms: u64,
}
impl SecretsRuntimeClientConfig {
    pub fn load_root_owned(path: &Path) -> Result<Self, ConsumerPortError> {
        crate::private_files::read_root_configuration(path)
    }
}

pub struct SecretsRuntimeClient {
    config: SecretsRuntimeClientConfig,
}
impl SecretsRuntimeClient {
    pub fn new(
        config: SecretsRuntimeClientConfig,
        actual_agent_id: &str,
    ) -> Result<Self, ConsumerPortError> {
        if config.schema_version != 1
            || config.agent_uid != rustix::process::geteuid().as_raw()
            || config.agent_uid == config.runtime_uid
            || config.agent_id != actual_agent_id
            || !config.socket_path.is_absolute()
            || config.operation_timeout_ms == 0
            || config.operation_timeout_ms > 30_000
        {
            return Err(ConsumerPortError::Invalid);
        }
        runtime_original_id(&config.agent_id, "configuration-validation")?;
        Ok(Self { config })
    }
    /// A failure after dispatch is Unknown. The caller retains this exact ID
    /// and may only query Status or Recover; this method never retries effects.
    pub fn consume_original(
        &self,
        original: &str,
        budget: Duration,
    ) -> Result<SecretsRuntimeResponse, ConsumerPortError> {
        let original_operation_id = runtime_original_id(&self.config.agent_id, original)?;
        let budget_ms = u64::try_from(budget.as_millis())
            .map_err(|_| ConsumerPortError::Invalid)?
            .min(self.config.operation_timeout_ms);
        if budget_ms == 0 {
            return Err(ConsumerPortError::Invalid);
        }
        let request = RuntimeRequest::Consume {
            operation_id: original.to_owned(),
            budget_ms,
        };
        match self.call(&request, &original_operation_id, budget_ms) {
            Ok(response) => Ok(response),
            Err(_) => Ok(SecretsRuntimeResponse::Unknown {
                original_operation_id,
            }),
        }
    }
    pub fn original_status(
        &self,
        original: &str,
    ) -> Result<SecretsRuntimeResponse, ConsumerPortError> {
        self.call(
            &RuntimeRequest::Status {
                operation_id: original.to_owned(),
            },
            &runtime_original_id(&self.config.agent_id, original)?,
            self.config.operation_timeout_ms,
        )
    }
    pub fn recover_original(
        &self,
        original: &str,
    ) -> Result<SecretsRuntimeResponse, ConsumerPortError> {
        self.call(
            &RuntimeRequest::Recover {
                operation_id: original.to_owned(),
            },
            &runtime_original_id(&self.config.agent_id, original)?,
            self.config.operation_timeout_ms,
        )
    }
    fn call(
        &self,
        request: &RuntimeRequest,
        expected: &str,
        timeout_ms: u64,
    ) -> Result<SecretsRuntimeResponse, ConsumerPortError> {
        let response = PreparedConnection::connect_runtime(
            &self.config.socket_path,
            self.config.runtime_uid,
            Duration::from_millis(timeout_ms),
        )?
        .exchange(request)?;
        match &response {
            SecretsRuntimeResponse::Completed {
                original_operation_id,
                ..
            }
            | SecretsRuntimeResponse::Unknown {
                original_operation_id,
            } if original_operation_id == expected => Ok(response),
            SecretsRuntimeResponse::Rejected => Ok(response),
            _ => Err(ConsumerPortError::Unavailable),
        }
    }
}
