//! Explicit enrollment of a live Agentd runtime and its recovered source owner.

use std::sync::Arc;
use std::sync::Mutex;
use std::sync::OnceLock;

use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_memory::CognitiveAccess;
use codex_hepta_memory::MemoryCellKeyV1;
use codex_hepta_memory::MemoryCellQueryV1;
use codex_hepta_memory::MemoryCellSourceClaimV1;
use codex_hepta_ndu::NduAuthenticatedOwnerV1;
use tokio_util::sync::CancellationToken;
use tokio_util::sync::DropGuard;

use crate::AgentdNativeMemoryCell;
use crate::AgentdNativeMemoryContextHostV1;
use crate::AgentdNativeMemoryCurrentContextV1;
use crate::AgentdNativeMemoryPreparedReadV1;
use crate::AgentdNativeMemoryShadowOwner;
use crate::AgentdProductionWriterHost;
use crate::NativeMemoryError;
use crate::NativeMemoryModelConfigV1;
use crate::NativeMemoryShadowFilesV1;
use crate::NativeMemoryShadowProfileV1;
use crate::NativeMemoryTickClockV1;
use crate::native_memory_shadow_namespace::reject;
use crate::state::AgentdState;

/// External owners to install once in one Agentd runtime. Construction grants
/// no reads: the runtime must attach its actual Objective and recovered writer.
pub struct AgentdNativeMemoryRegistrationV1 {
    ndu: Arc<Mutex<NduAuthenticatedOwnerV1>>,
    clock: Arc<dyn NativeMemoryTickClockV1>,
    host: OnceLock<Arc<AgentdNativeMemoryHostV1>>,
}

/// Installed factory bound to one live runtime. A later ObjectiveStart can be
/// selected explicitly; enrollment never invents or admits a run.
pub struct AgentdNativeMemoryHostV1 {
    context: Arc<AgentdNativeMemoryContextHostV1>,
    writer: Arc<AgentdProductionWriterHost>,
}

/// One source and pinned decoder supplied by the embedding host. The factory
/// checks its typed key, durable source authority and retained model ancestry.
pub struct NativeMemorySourceConfigV1 {
    pub access: CognitiveAccess,
    pub key: MemoryCellKeyV1,
    pub claim: MemoryCellSourceClaimV1,
    pub model: NativeMemoryModelConfigV1,
}

impl AgentdNativeMemoryRegistrationV1 {
    pub fn new(
        ndu: Arc<Mutex<NduAuthenticatedOwnerV1>>,
        clock: Arc<dyn NativeMemoryTickClockV1>,
    ) -> Self {
        Self {
            ndu,
            clock,
            host: OnceLock::new(),
        }
    }

    pub fn host(&self) -> Result<Arc<AgentdNativeMemoryHostV1>, NativeMemoryError> {
        let host = self
            .host
            .get()
            .ok_or_else(|| reject("native memory runtime is not installed"))?;
        if host.context.cancellation.is_cancelled() {
            return Err(reject("native memory runtime is closed"));
        }
        Ok(Arc::clone(host))
    }

    /// The returned guard belongs to the daemon's run future, not to an external
    /// handle. Dropping or cancelling that runtime closes every factory child.
    pub(crate) fn attach(
        &self,
        state: &Arc<AgentdState>,
        writer: Arc<AgentdProductionWriterHost>,
        runtime_cancellation: &CancellationToken,
    ) -> Result<DropGuard, NativeMemoryError> {
        if self.host.get().is_some() {
            return Err(reject("native memory registration was already installed"));
        }
        let source = writer.writer();
        if writer.recovered_source_anchor().is_none()
            || source.owner_agent_id() != &state.identity().agent_id
            || source.generation() != state.identity().spawn_generation
        {
            return Err(reject(
                "native memory requires this runtime's recovered source owner",
            ));
        }
        let cancellation = runtime_cancellation.child_token();
        let lifetime = cancellation.clone().drop_guard();
        let context = AgentdNativeMemoryContextHostV1::attach_with_cancellation(
            state,
            Arc::clone(&self.ndu),
            Arc::clone(&self.clock),
            cancellation,
        )?;
        self.host
            .set(Arc::new(AgentdNativeMemoryHostV1 { context, writer }))
            .map_err(|_| reject("native memory registration was already installed"))?;
        Ok(lifetime)
    }
}

impl AgentdNativeMemoryHostV1 {
    pub fn prepare_read(
        &self,
        run_id: &str,
        query: MemoryCellQueryV1,
    ) -> Result<AgentdNativeMemoryPreparedReadV1, NativeMemoryError> {
        self.context.prepare_read(run_id, query)
    }

    /// Enroll a shadow owner only after the external issuer signed this exact
    /// runtime/query binding. The source and model still undergo live checks.
    pub async fn open_shadow(
        &self,
        prepared: AgentdNativeMemoryPreparedReadV1,
        signed_grant: &SignedFinalUseGrant,
        source: NativeMemorySourceConfigV1,
        files: NativeMemoryShadowFilesV1,
        profile: NativeMemoryShadowProfileV1,
    ) -> Result<
        Arc<AgentdNativeMemoryShadowOwner<AgentdNativeMemoryCurrentContextV1>>,
        NativeMemoryError,
    > {
        if self.context.cancellation.is_cancelled()
            || !prepared.belongs_to(&self.context)
            || prepared.query().key != source.key
        {
            return Err(reject(
                "prepared read or source key differs from the live factory",
            ));
        }
        let query = prepared.query().clone();
        let context = prepared.authorize(signed_grant)?;
        let cancellation = self.context.cancellation.child_token();
        let pending = cancellation.clone().drop_guard();
        let cell = AgentdNativeMemoryCell::from_registered_source(
            self.writer.writer(),
            source,
            &query,
            cancellation,
        )
        .await?;
        let owner = cell.open_shadow(files, profile, context, &query).await?;
        if self.context.cancellation.is_cancelled() {
            return Err(reject("native memory runtime closed during enrollment"));
        }
        pending.disarm();
        Ok(owner)
    }
}

#[cfg(test)]
#[path = "native_memory_registration_tests.rs"]
mod tests;

#[cfg(all(test, unix))]
#[path = "native_memory_registration_current_tests.rs"]
mod current_tests;

#[cfg(all(test, unix))]
#[path = "native_memory_registration_pretrained_tests.rs"]
mod pretrained_tests;

#[cfg(all(test, unix))]
#[path = "native_memory_registration_startup_tests.rs"]
mod startup_tests;
