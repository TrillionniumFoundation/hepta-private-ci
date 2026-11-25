//! Ephemeral admission/join gate; durable pending state remains in the writer.
use crate::AgentdError;
use crate::AgentdState;
use crate::state::NativeCpuRuntimeOwners;
use std::net::Shutdown;
use std::os::unix::net::UnixStream;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::OnceLock;
use std::sync::Weak;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;

pub(crate) struct NativeCpuIngress {
    state: OnceLock<Weak<AgentdState<NativeCpuRuntimeOwners>>>,
    serial: Arc<tokio::sync::Mutex<()>>,
    closed: AtomicBool,
    stopping: AtomicBool,
    rpc: Mutex<Option<UnixStream>>,
}
impl NativeCpuIngress {
    pub(crate) fn new() -> Self {
        Self {
            state: OnceLock::new(),
            serial: Arc::new(tokio::sync::Mutex::new(())),
            closed: AtomicBool::new(false),
            stopping: AtomicBool::new(false),
            rpc: Mutex::new(None),
        }
    }
    pub(crate) fn attach_state(
        &self,
        state: &Arc<AgentdState<NativeCpuRuntimeOwners>>,
    ) -> Result<(), AgentdError> {
        self.state
            .set(Arc::downgrade(state))
            .map_err(|_| AgentdError::Invalid("native admission already registered".into()))
    }
    pub(crate) fn attach_rpc(&self, rpc: UnixStream) -> Result<(), AgentdError> {
        let mut slot = self
            .rpc
            .lock()
            .map_err(|_| AgentdError::Protocol("native admission poisoned".into()))?;
        if slot.is_some() || self.stopping() {
            return Err(AgentdError::Invalid(
                "native command lifetime already fixed".into(),
            ));
        }
        *slot = Some(rpc);
        Ok(())
    }
    pub(crate) async fn begin_mutation(
        &self,
    ) -> Result<tokio::sync::OwnedMutexGuard<()>, AgentdError> {
        let guard = self.serial.clone().lock_owned().await;
        if self.closed.load(Ordering::Acquire) {
            return Err(AgentdError::GenerationFenced(
                "native command admission is closed".into(),
            ));
        }
        self.state
            .get()
            .and_then(Weak::upgrade)
            .ok_or_else(|| AgentdError::Invalid("native admission state unavailable".into()))?
            .require_native_cpu_admission()?;
        Ok(guard)
    }
    pub(crate) async fn maintenance_guard(&self) -> tokio::sync::OwnedMutexGuard<()> {
        self.serial.clone().lock_owned().await
    }
    pub(crate) fn closed(&self) -> bool {
        self.closed.load(Ordering::Acquire)
    }
    pub(crate) fn close(&self) {
        self.closed.store(true, Ordering::Release);
    }
    pub(crate) fn stopping(&self) -> bool {
        self.stopping.load(Ordering::Acquire)
    }
    pub(crate) fn stop(&self) {
        self.close();
        self.stopping.store(true, Ordering::Release);
        if let Ok(slot) = self.rpc.lock()
            && let Some(stream) = slot.as_ref()
        {
            let _ = stream.shutdown(Shutdown::Both);
        }
    }
    pub(crate) async fn blockers(
        &self,
        host: &crate::AgentdProductionWriterHost,
    ) -> Result<u32, AgentdError> {
        self.close();
        let Ok(_guard) = self.serial.try_lock() else {
            return Ok(1);
        };
        host.writer()
            .hos2_drain_blockers()
            .await
            .map_err(Into::into)
    }
}
