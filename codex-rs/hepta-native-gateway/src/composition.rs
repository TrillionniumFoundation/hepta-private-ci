use std::sync::Arc;

use anyhow::Result;
use anyhow::bail;
use codex_hepta_runtime::HeptaRuntime;

use super::shell_runtime::BackendConnector;
use super::shell_runtime::BackendSession;
use super::shell_runtime::EndpointManifest;
use super::shell_runtime::SessionKey;

pub(crate) const NATIVE_PROTOCOL_VERSION: u64 = 1;
pub(crate) const LOCAL_ENDPOINT_ID: &str = "hepta.runtime.local";

/// Binds the native shell to the process-owned Hepta runtime without creating a
/// second execution spine. The connector authenticates a frozen manifest and
/// derives its generation fence from the runtime's verified status snapshot.
#[derive(Clone)]
pub(crate) struct LocalRuntimeBackend {
    runtime: Arc<HeptaRuntime>,
    expected_manifest_digest: String,
}

impl LocalRuntimeBackend {
    pub(crate) fn new(runtime: Arc<HeptaRuntime>, expected_manifest_digest: String) -> Result<Self> {
        validate_digest(&expected_manifest_digest)?;
        Ok(Self {
            runtime,
            expected_manifest_digest,
        })
    }
}

impl BackendConnector for LocalRuntimeBackend {
    fn connect(&self, manifest: &EndpointManifest) -> Result<BackendSession> {
        if manifest.endpoint_id != LOCAL_ENDPOINT_ID
            || manifest.protocol_version != NATIVE_PROTOCOL_VERSION
            || manifest.manifest_digest != self.expected_manifest_digest
        {
            bail!("native runtime endpoint manifest is not the selected local runtime");
        }
        let status = self.runtime.status();
        if status.status != "ready" || !status.state.integrity_binding_present {
            bail!("native runtime is not ready with verified integrity");
        }
        let generation = status
            .state
            .runtime_snapshot_generation
            .checked_add(1)
            .ok_or_else(|| anyhow::anyhow!("native runtime generation overflow"))?;
        Ok(BackendSession {
            authenticated: true,
            protocol_version: NATIVE_PROTOCOL_VERSION,
            session_id: format!("native.local.{generation}"),
            generation,
        })
    }

    fn close(&self, _session: &SessionKey) -> Result<()> {
        Ok(())
    }
}

fn validate_digest(value: &str) -> Result<()> {
    if value.len() != 64
        || value.bytes().all(|byte| byte == b'0')
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || matches!(byte, b'a'..=b'f'))
    {
        bail!("native runtime manifest digest must be a non-zero lowercase SHA-256 digest");
    }
    Ok(())
}
