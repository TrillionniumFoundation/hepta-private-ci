//! `thread/delete` request handling.

use super::thread_processor::unsupported_thread_store_operation;
use super::*;

const MAX_THREAD_DELETE_SUBTREE_THREADS: usize = 4096;

#[derive(Default)]
struct ThreadDeleteSubtreeClosure {
    prepared_thread_ids: Vec<ThreadId>,
    prepared: HashSet<ThreadId>,
}

impl ThreadDeleteSubtreeClosure {
    fn observe(&mut self, observed_thread_ids: Vec<ThreadId>) -> Result<Vec<ThreadId>, ()> {
        let mut new_thread_ids = Vec::new();
        for thread_id in observed_thread_ids {
            if self.prepared.contains(&thread_id) {
                continue;
            }
            if self.prepared_thread_ids.len() >= MAX_THREAD_DELETE_SUBTREE_THREADS {
                return Err(());
            }
            self.prepared.insert(thread_id);
            self.prepared_thread_ids.push(thread_id);
            new_thread_ids.push(thread_id);
        }
        Ok(new_thread_ids)
    }

    fn into_prepared_thread_ids(self) -> Vec<ThreadId> {
        self.prepared_thread_ids
    }

    fn prepared_thread_ids(&self) -> &[ThreadId] {
        self.prepared_thread_ids.as_slice()
    }
}

impl ThreadRequestProcessor {
    pub(crate) async fn thread_delete(
        &self,
        request_id: ConnectionRequestId,
        params: ThreadDeleteParams,
    ) -> Result<Option<ClientResponsePayload>, JSONRPCErrorError> {
        let mut deleted_thread_ids = Vec::new();
        let result = {
            let _thread_list_state_permit = self.acquire_thread_list_state_permit().await?;
            self.thread_delete_response(params, &mut deleted_thread_ids)
                .await
        };
        match result {
            Ok(response) => {
                self.outgoing
                    .send_response(request_id.clone(), response)
                    .await;
                self.send_thread_deleted_notifications(deleted_thread_ids)
                    .await;
                Ok(None)
            }
            Err(error) => Err(error),
        }
    }

    async fn thread_delete_response(
        &self,
        params: ThreadDeleteParams,
        deleted_thread_ids: &mut Vec<String>,
    ) -> Result<ThreadDeleteResponse, JSONRPCErrorError> {
        let thread_id = ThreadId::from_string(&params.thread_id)
            .map_err(|err| invalid_request(format!("invalid thread id: {err}")))?;
        let state_db = self.state_db.as_ref().ok_or_else(|| {
            unsupported_thread_store_operation("thread/delete durable hard-delete fencing")
        })?;
        if !self.thread_store.supports_durable_hard_delete_fencing() {
            return Err(unsupported_thread_store_operation(
                "thread/delete thread-store durable hard-delete fencing",
            ));
        }

        // Publish the complete prepared closure before the first cross-store mutation. If the
        // caller disappears after thread-store or StateDb deletion commits, a retry must recover
        // the exact authority set instead of failing early because both ordinary indexes are now
        // (correctly) missing.
        let durable_delete_subtree = state_db
            .thread_queue()
            .thread_deletion_operation_members(thread_id)
            .await
            .map_err(|error| {
                internal_error(format!(
                    "failed to recover hard-delete operation for thread {thread_id}: {error}"
                ))
            })?;
        let thread_ids = if let Some(thread_ids) = durable_delete_subtree {
            let durable_members = thread_ids.iter().copied().collect::<HashSet<_>>();
            for &member_thread_id in &thread_ids {
                let startup_thread_ids = self.prepare_thread_for_delete(member_thread_id).await?;
                if startup_thread_ids
                    .iter()
                    .any(|startup_thread_id| !durable_members.contains(startup_thread_id))
                {
                    return Err(invalid_request(format!(
                        "thread {thread_id} acquired startup lineage outside its durable hard-delete closure; refusing retry"
                    )));
                }
            }
            thread_ids
        } else {
            let existing_delete_subtree = self
                .pending_thread_delete_subtrees
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner)
                .get(&thread_id)
                .cloned();
            match existing_delete_subtree {
                Some(thread_ids) => thread_ids.to_vec(),
                None => {
                    let thread_ids = self.prepare_thread_subtree_for_delete(thread_id).await?;
                    self.pending_thread_delete_subtrees
                        .lock()
                        .unwrap_or_else(std::sync::PoisonError::into_inner)
                        .entry(thread_id)
                        .or_insert_with(|| thread_ids.into())
                        .to_vec()
                }
            }
        };

        // Seal the complete subtree in one queue.sqlite writer transaction
        // before touching the external thread store. The permanent tombstones
        // linearize against dispatch claim and prevent resurrection if a later
        // cross-store delete fails and must be retried.
        if let Err(error) = state_db
            .thread_queue()
            .seal_thread_subtree_for_deletion(thread_id, thread_ids.as_slice())
            .await
        {
            // A SQLite commit failure can be observationally ambiguous. Release Core's
            // pre-seal fences only when a follow-up read proves that no subtree tombstone is
            // authoritative. Any present or unreadable tombstone remains fail-closed.
            let proven_unsealed = self
                .thread_subtree_is_proven_unsealed(thread_ids.as_slice())
                .await;
            if proven_unsealed {
                self.abort_safe_hard_deletes_before_seal(thread_ids.as_slice())
                    .await;
                self.pending_thread_delete_subtrees
                    .lock()
                    .unwrap_or_else(std::sync::PoisonError::into_inner)
                    .remove(&thread_id);
            }
            return Err(thread_queue_delete_fence_error(error));
        }

        let mut delete_order: Vec<_> = thread_ids.iter().skip(1).rev().copied().collect();
        delete_order.push(thread_id);

        self.thread_store
            .delete_threads(StoreDeleteThreadsParams {
                thread_ids: delete_order.clone(),
            })
            .await
            .map_err(thread_store_delete_error)?;

        state_db
            .delete_threads_strict(thread_ids.as_slice())
            .await
            .map_err(|err| {
                internal_error(format!(
                    "failed to delete app-server state for {thread_id}: {err}"
                ))
            })?;

        // The in-memory closing authority spans the complete cross-store
        // transaction. Clearing it earlier would let a failed store/state
        // delete cold-resume a Core after the queue tombstone was committed.
        self.finalize_hard_deleted_threads(thread_ids.as_slice())
            .await;
        self.pending_thread_delete_subtrees
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .remove(&thread_id);

        deleted_thread_ids.extend(
            delete_order
                .into_iter()
                .map(|thread_id| thread_id.to_string()),
        );
        Ok(ThreadDeleteResponse {})
    }

    /// Shut down the complete live spawn subtree before sealing durable state.
    ///
    /// A Core child spawn does not take the app-server thread-list permit. The first snapshot
    /// therefore is not an authority boundary. Core's atomic hard-delete fence prevents a
    /// fenced runtime (or its immediate child) from finalizing a new spawn, while repeated
    /// enumeration collects children that finalized before their parent was fenced. Only a
    /// stable post-shutdown snapshot may proceed to queue sealing and store deletion.
    async fn prepare_thread_subtree_for_delete(
        &self,
        root_thread_id: ThreadId,
    ) -> Result<Vec<ThreadId>, JSONRPCErrorError> {
        let initial_thread_ids = self
            .state_db_spawn_subtree_thread_ids(root_thread_id)
            .await?;
        self.validate_root_thread_delete(root_thread_id, initial_thread_ids.len() > 1)
            .await?;

        let mut closure = ThreadDeleteSubtreeClosure::default();
        let mut observed_thread_ids = initial_thread_ids;

        loop {
            let new_thread_ids = match closure.observe(observed_thread_ids) {
                Ok(new_thread_ids) => new_thread_ids,
                Err(()) => {
                    self.abort_safe_hard_deletes_before_seal(closure.prepared_thread_ids())
                        .await;
                    return Err(invalid_request(format!(
                        "thread {root_thread_id} spawn subtree exceeds the bounded delete limit of {MAX_THREAD_DELETE_SUBTREE_THREADS}; refusing hard deletion"
                    )));
                }
            };
            if new_thread_ids.is_empty() {
                break;
            }
            let mut admitted_startup_thread_ids = Vec::new();
            for thread_id in new_thread_ids {
                match self.prepare_thread_for_delete(thread_id).await {
                    Ok(startup_thread_ids) => {
                        admitted_startup_thread_ids.extend(startup_thread_ids);
                    }
                    Err(error) => {
                        // Earlier members are Cold/Stopped and may safely resume because no
                        // durable seal exists yet. The ambiguous authority that caused this error
                        // is retained and reused by the next delete retry.
                        self.abort_safe_hard_deletes_before_seal(closure.prepared_thread_ids())
                            .await;
                        return Err(error);
                    }
                }
            }

            // Drain Core-admitted startup lineage before any fallible graph re-enumeration.
            // A copied fork can have materialized rollout/state without yet publishing an
            // AgentGraph edge. Preparing its snapshotted ID first gives that phantom child its
            // own retryable authority; it cannot be lost if the later graph read fails.
            if !admitted_startup_thread_ids.is_empty() {
                observed_thread_ids = admitted_startup_thread_ids;
                continue;
            }

            observed_thread_ids = match self.state_db_spawn_subtree_thread_ids(root_thread_id).await
            {
                Ok(observed_thread_ids) => observed_thread_ids,
                Err(error) => {
                    self.abort_safe_hard_deletes_before_seal(closure.prepared_thread_ids())
                        .await;
                    return Err(error);
                }
            };
        }

        Ok(closure.into_prepared_thread_ids())
    }

    async fn send_thread_deleted_notifications(&self, deleted_thread_ids: Vec<String>) {
        for thread_id in deleted_thread_ids {
            self.outgoing
                .send_server_notification(ServerNotification::ThreadDeleted(
                    ThreadDeletedNotification { thread_id },
                ))
                .await;
        }
    }

    async fn validate_root_thread_delete(
        &self,
        thread_id: ThreadId,
        has_descendants: bool,
    ) -> Result<(), JSONRPCErrorError> {
        if let Ok(thread) = self.thread_manager.get_thread(thread_id).await {
            if !thread.config_snapshot().await.ephemeral {
                return Ok(());
            }
            return Err(invalid_request(format!(
                "thread is not persisted and cannot be deleted: {thread_id}"
            )));
        }
        match self
            .thread_store
            .read_thread(StoreReadThreadParams {
                thread_id,
                include_archived: true,
                include_history: false,
            })
            .await
        {
            Ok(_) => Ok(()),
            Err(ThreadStoreError::ThreadNotFound { .. }) => {
                if has_descendants {
                    return Ok(());
                }
                let Some(state_db) = self.state_db.as_ref() else {
                    return Err(thread_store_delete_error(
                        ThreadStoreError::ThreadNotFound { thread_id },
                    ));
                };
                if state_db
                    .get_thread(thread_id)
                    .await
                    .map_err(|err| {
                        internal_error(format!(
                            "failed to read app-server state for {thread_id}: {err}"
                        ))
                    })?
                    .is_some()
                {
                    Ok(())
                } else {
                    Err(thread_store_delete_error(
                        ThreadStoreError::ThreadNotFound { thread_id },
                    ))
                }
            }
            Err(err) => Err(thread_store_delete_error(err)),
        }
    }

    async fn prepare_thread_for_delete(
        &self,
        thread_id: ThreadId,
    ) -> Result<Vec<ThreadId>, JSONRPCErrorError> {
        let startup_thread_ids = self.prepare_thread_for_hard_delete(thread_id).await?;
        if let Some(log_db) = self.log_db.as_ref() {
            log_db.flush().await;
        }
        Ok(startup_thread_ids)
    }

    async fn thread_subtree_is_proven_unsealed(&self, thread_ids: &[ThreadId]) -> bool {
        let Some(state_db) = self.state_db.as_ref() else {
            return false;
        };
        for &thread_id in thread_ids {
            match state_db
                .thread_queue()
                .thread_queue_is_sealed_for_deletion(thread_id)
                .await
            {
                Ok(false) => {}
                Ok(true) | Err(_) => return false,
            }
        }
        true
    }
}

fn thread_queue_delete_fence_error(err: anyhow::Error) -> JSONRPCErrorError {
    if let Some(conflict) = err.downcast_ref::<codex_state::QueuedClientBindingConflict>() {
        return invalid_request(conflict.message.clone());
    }
    internal_error(format!(
        "failed to seal thread queue before deletion: {err}"
    ))
}

fn thread_store_delete_error(err: ThreadStoreError) -> JSONRPCErrorError {
    match err {
        ThreadStoreError::ThreadNotFound { thread_id } => {
            invalid_request(format!("thread not found: {thread_id}"))
        }
        ThreadStoreError::InvalidRequest { message } | ThreadStoreError::Conflict { message } => {
            invalid_request(message)
        }
        ThreadStoreError::Unsupported { operation } => {
            unsupported_thread_store_operation(operation)
        }
        err => internal_error(format!("failed to delete thread: {err}")),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn subtree_closure_adds_child_that_becomes_visible_during_parent_shutdown() {
        let root = ThreadId::from_string("3b199e4d-e9cb-4e26-a8ee-2ff60ca3ce26")
            .expect("valid root thread id");
        let child = ThreadId::from_string("862f3c47-596d-49f1-af5b-fef7a3a54db5")
            .expect("valid child thread id");
        let mut closure = ThreadDeleteSubtreeClosure::default();

        assert_eq!(closure.observe(vec![root]), Ok(vec![root]));
        // The child commits while the root's shutdown is in progress. The
        // post-shutdown observation must schedule it before deletion can seal.
        assert_eq!(closure.observe(vec![root, child]), Ok(vec![child]));
        assert_eq!(closure.observe(vec![root, child]), Ok(Vec::new()));
        assert_eq!(closure.into_prepared_thread_ids(), vec![root, child]);
    }
}
