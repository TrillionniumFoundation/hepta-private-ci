use crate::unified_exec::UnifiedExecProcessManager;
use std::sync::Arc;
use std::sync::atomic::Ordering;
use tokio::time::Instant;

impl UnifiedExecProcessManager {
    pub(crate) async fn terminate_process_until(&self, process_id: i32, deadline: Instant) -> bool {
        if Instant::now() >= deadline {
            return false;
        }
        let process = {
            let Ok(store) = tokio::time::timeout_at(deadline, self.process_store.lock()).await
            else {
                return false;
            };
            if Instant::now() >= deadline {
                return false;
            }
            let Some(entry) = store.processes.get(&process_id) else {
                return false;
            };
            Arc::clone(&entry.process)
        };

        if process.terminate_confirmed_until(deadline).await.is_err() {
            return false;
        }

        let (session, approval) = {
            let Ok(store) = tokio::time::timeout_at(deadline, self.process_store.lock()).await
            else {
                return false;
            };
            if Instant::now() >= deadline {
                return false;
            }
            let Some(entry) = store.processes.get(&process_id) else {
                // Other paths remove before asynchronous approval cleanup.
                // Absence alone does not confirm that cleanup has completed.
                return false;
            };
            if !Arc::ptr_eq(&entry.process, &process)
                || entry.initial_exec_command_active.load(Ordering::Acquire)
            {
                return false;
            }
            (entry.session.upgrade(), entry.network_approval.clone())
        };

        // Keep the exact entry while cleanup is unresolved. The approval
        // service uses a synchronous lock: timeout_at cannot preempt its lock()
        // call, so this path must try once without waiting or detached cleanup.
        if let Some(session) = session
            && let Some(approval) = approval
            && !session
                .services
                .network_approval
                .try_unregister_call_until(approval.registration_id(), deadline)
        {
            return false;
        }

        let Ok(mut store) = tokio::time::timeout_at(deadline, self.process_store.lock()).await
        else {
            return false;
        };
        if Instant::now() >= deadline {
            return false;
        }
        let Some(entry) = store.processes.get(&process_id) else {
            return false;
        };
        if !Arc::ptr_eq(&entry.process, &process)
            || entry.initial_exec_command_active.load(Ordering::Acquire)
        {
            return false;
        }
        store.remove(process_id).is_some()
    }
}
