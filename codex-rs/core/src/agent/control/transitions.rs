use codex_protocol::ThreadId;
use std::collections::HashMap;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::Weak;
use tokio::sync::Mutex as AsyncMutex;
use tokio::sync::OwnedMutexGuard;

/// Serializes publication and logical close for one agent in this control tree.
/// Ordinary runtime shutdown waits do not hold this guard; their retirement
/// compares the captured runtime after reacquiring it. Never wait for another
/// agent's guard while holding one, or acquire this guard under the registry.
#[derive(Default)]
pub(super) struct AgentTransitions {
    agents: Mutex<HashMap<ThreadId, Weak<AsyncMutex<()>>>>,
}

/// Shared ownership keeps a transition fenced after its requesting future is
/// canceled, until any detached startup owner finishes delivery or cleanup.
#[derive(Clone)]
pub(crate) struct AgentTransitionLease {
    _guard: Arc<OwnedMutexGuard<()>>,
}

impl AgentTransitions {
    pub(super) async fn lock(&self, thread_id: ThreadId) -> AgentTransitionLease {
        AgentTransitionLease {
            _guard: Arc::new(self.transition(thread_id).lock_owned().await),
        }
    }

    pub(super) fn try_lock(&self, thread_id: ThreadId) -> Option<AgentTransitionLease> {
        self.transition(thread_id)
            .try_lock_owned()
            .ok()
            .map(|guard| AgentTransitionLease {
                _guard: Arc::new(guard),
            })
    }

    fn transition(&self, thread_id: ThreadId) -> Arc<AsyncMutex<()>> {
        let mut agents = self
            .agents
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        agents.retain(|_, transition| transition.strong_count() != 0);
        if let Some(transition) = agents.get(&thread_id).and_then(Weak::upgrade) {
            transition
        } else {
            let transition = Arc::new(AsyncMutex::new(()));
            agents.insert(thread_id, Arc::downgrade(&transition));
            transition
        }
    }
}
