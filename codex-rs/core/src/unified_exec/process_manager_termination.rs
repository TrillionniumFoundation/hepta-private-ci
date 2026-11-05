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
                return true;
            };
            if !Arc::ptr_eq(&entry.process, &process)
                || entry.initial_exec_command_active.load(Ordering::Acquire)
            {
                return true;
            }
            (entry.session.upgrade(), entry.network_approval.clone())
        };

        // Keep the exact entry in the store across asynchronous cleanup. A
        // cancelled or expired control future must not discard its owner or
        // leave cleanup work dependent on a removed local entry.
        if let Some(session) = session
            && let Some(approval) = approval
            && tokio::time::timeout_at(
                deadline,
                session
                    .services
                    .network_approval
                    .unregister_call(approval.registration_id()),
            )
            .await
            .is_err()
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
            return true;
        };
        if !Arc::ptr_eq(&entry.process, &process)
            || entry.initial_exec_command_active.load(Ordering::Acquire)
        {
            return true;
        }
        store.remove(process_id).is_some()
    }
}
