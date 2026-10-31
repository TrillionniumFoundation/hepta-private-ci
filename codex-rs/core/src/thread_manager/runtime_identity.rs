use super::*;

impl ThreadManagerState {
    /// Publish synchronous ownership records only while this exact runtime is current.
    /// Registration publication additionally holds its per-agent transition guard;
    /// touching an existing residency record only needs this runtime comparison.
    pub(crate) async fn with_current_runtime<T>(
        &self,
        thread_id: ThreadId,
        expected: &Arc<CodexThread>,
        publish: impl FnOnce() -> T,
    ) -> Option<T> {
        let registry = self.thread_registry.write().await;
        registry
            .threads
            .get(&thread_id)
            .is_some_and(|current| Arc::ptr_eq(current, expected))
            .then(publish)
    }

    /// Submit to the exact runtime being operated on, preserving operation capture.
    /// A later registration under the same thread ID must not receive this operation.
    pub(crate) async fn send_op_to_runtime(
        &self,
        thread: &CodexThread,
        op: Op,
        parent_turn_id: Option<String>,
        root_turn_id: Option<String>,
    ) -> CodexResult<String> {
        let thread_id = thread.session.thread_id();
        if let Some(ops_log) = &self.ops_log
            && let Ok(mut log) = ops_log.lock()
            && let Some(captured_op) = capture_test_op(&op)
        {
            log.push((thread_id, captured_op));
        }
        thread
            .io
            .submit_with_trace(op, /*trace*/ None, parent_turn_id, root_turn_id)
            .await
    }

    /// Retire an unchanged runtime and its synchronous ownership records atomically.
    ///
    /// Keep registry -> residency/agent-record lock order. `retire` must neither
    /// await nor acquire the registry again. Existing residency/agent operations
    /// release their short synchronous locks before awaiting a registry operation.
    /// Holding the registry through `retire` prevents a replacement from registering
    /// between pointer comparison and removal of its ownership records.
    /// A stale owner, including one already removed, cannot retire unknown metadata.
    /// An empty registry alone does not identify a cold agent-registration owner.
    pub(crate) async fn retire_runtime_if_current(
        &self,
        thread_id: ThreadId,
        expected: &Arc<CodexThread>,
        retire: impl FnOnce(),
    ) -> Option<Arc<CodexThread>> {
        let mut registry = self.thread_registry.write().await;
        if !registry
            .threads
            .get(&thread_id)
            .is_some_and(|current| Arc::ptr_eq(current, expected))
        {
            return None;
        }
        let removed = registry.threads.remove(&thread_id);
        retire();
        removed
    }
}
