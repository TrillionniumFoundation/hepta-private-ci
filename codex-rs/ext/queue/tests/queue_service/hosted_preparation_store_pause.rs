//! Pauses one actual append without replacing the original persistence owner.
//! Every other ThreadStore capability is delegated, including all native
//! checkpoint/currentness and hard-delete fencing operations.

use super::*;
use std::any::Any;
use codex_thread_store as store;

#[derive(Default)]
pub(super) struct UserAppendPause {
    armed: AtomicBool,
    pub(super) entered: Notify,
    pub(super) attempted: OnceLock<store::AppendThreadItemsParams>,
}

impl UserAppendPause {
    pub(super) fn arm(&self) {
        assert!(!self.armed.swap(true, Ordering::SeqCst));
    }
}

pub(super) struct PauseUserAppendStore {
    inner: Arc<dyn store::ThreadStore>,
    pause: Arc<UserAppendPause>,
}

impl PauseUserAppendStore {
    pub(super) fn wrap(inner: Arc<dyn store::ThreadStore>, pause: Arc<UserAppendPause>) -> Arc<dyn store::ThreadStore> {
        Arc::new(Self { inner, pause })
    }
}

pub(super) fn is_user_response(item: &RolloutItem) -> bool {
    matches!(item, RolloutItem::ResponseItem(envelope)
        if matches!(&envelope.item, ResponseItem::Message { role, .. } if role == "user"))
}

impl store::ThreadStore for PauseUserAppendStore {
    fn as_any(&self) -> &dyn Any {
        self.inner.as_any()
    }

    fn open_native_checkpoint(
        &self,
        binding: store::NativeCheckpointBinding,
        mode: store::NativeCheckpointOpenMode,
        currentness: std::sync::Arc<dyn store::NativeCheckpointCurrentness>,
    ) -> store::ThreadStoreFuture<'_, store::NativeCheckpointSession> {
        self.inner.open_native_checkpoint(binding, mode, currentness)
    }

    fn load_native_checkpoint<'a>(
        &'a self,
        session: &'a store::NativeCheckpointSession,
    ) -> store::ThreadStoreFuture<'a, store::NativeCheckpointLoad> {
        self.inner.load_native_checkpoint(session)
    }

    fn load_native_checkpoint_chain<'a>(
        &'a self,
        session: &'a store::NativeCheckpointSession,
    ) -> store::ThreadStoreFuture<'a, Vec<store::StoredNativeCheckpoint>> {
        self.inner.load_native_checkpoint_chain(session)
    }

    fn commit_native_checkpoint<'a>(
        &'a self,
        session: &'a store::NativeCheckpointSession,
        expected: store::NativeCheckpointExpected,
        state: store::NativeCheckpointState,
    ) -> store::ThreadStoreFuture<'a, store::StoredNativeCheckpoint> {
        self.inner.commit_native_checkpoint(session, expected, state)
    }

    fn verify_native_history<'a>(
        &'a self,
        session: &'a store::NativeCheckpointSession,
        expected: store::NativeHistoryVerification,
    ) -> store::ThreadStoreFuture<'a, ()> {
        self.inner.verify_native_history(session, expected)
    }

    fn sync_native_history<'a>(
        &'a self,
        session: &'a store::NativeCheckpointSession,
        expected: store::NativeCheckpointVersion,
        items: Vec<codex_protocol::models::ResponseItem>,
    ) -> store::ThreadStoreFuture<'a, ()> {
        self.inner.sync_native_history(session, expected, items)
    }

    fn default_history_mode(&self) -> ThreadHistoryMode {
        self.inner.default_history_mode()
    }

    fn create_thread(&self, params: store::CreateThreadParams) -> store::ThreadStoreFuture<'_, ()> {
        self.inner.create_thread(params)
    }

    fn stage_pending_thread_metadata(
        &self,
        thread_id: ThreadId,
        patch: store::ThreadMetadataPatch,
    ) -> store::ThreadStoreFuture<'_, ()> {
        self.inner.stage_pending_thread_metadata(thread_id, patch)
    }

    fn remove_pending_thread_metadata(&self, thread_id: ThreadId) -> store::ThreadStoreFuture<'_, ()> {
        self.inner.remove_pending_thread_metadata(thread_id)
    }

    fn resume_thread(&self, params: store::ResumeThreadParams) -> store::ThreadStoreFuture<'_, ()> {
        self.inner.resume_thread(params)
    }

    fn is_thread_hard_delete_fenced(&self, thread_id: ThreadId) -> store::ThreadStoreFuture<'_, bool> {
        self.inner.is_thread_hard_delete_fenced(thread_id)
    }

    fn supports_durable_hard_delete_fencing(&self) -> bool {
        self.inner.supports_durable_hard_delete_fencing()
    }

    fn append_items(&self, params: store::AppendThreadItemsParams) -> store::ThreadStoreFuture<'_, ()> {
        Box::pin(async move {
            if params.items.iter().any(is_user_response)
                && self.pause.armed.swap(false, Ordering::SeqCst)
            {
                assert!(self.pause.attempted.set(params.clone()).is_ok());
                self.pause.entered.notify_one();
                // Nothing from this append reaches the original store. The
                // original task is stopped through Core's suspension API.
                std::future::pending::<()>().await;
            }
            self.inner.append_items(params).await
        })
    }

    fn persist_thread(
        &self,
        thread_id: ThreadId,
        context: store::PersistContext,
    ) -> store::ThreadStoreFuture<'_, ()> {
        self.inner.persist_thread(thread_id, context)
    }

    fn flush_thread(&self, thread_id: ThreadId) -> store::ThreadStoreFuture<'_, ()> {
        self.inner.flush_thread(thread_id)
    }

    fn shutdown_thread(&self, thread_id: ThreadId) -> store::ThreadStoreFuture<'_, ()> {
        self.inner.shutdown_thread(thread_id)
    }

    fn discard_thread(&self, thread_id: ThreadId) -> store::ThreadStoreFuture<'_, ()> {
        self.inner.discard_thread(thread_id)
    }

    fn load_history(
        &self,
        params: store::LoadThreadHistoryParams,
    ) -> store::ThreadStoreFuture<'_, store::StoredThreadHistory> {
        self.inner.load_history(params)
    }

    fn load_latest_model_context(
        &self,
        params: store::LoadThreadHistoryParams,
    ) -> store::ThreadStoreFuture<'_, store::StoredModelContext> {
        self.inner.load_latest_model_context(params)
    }

    fn prepare_fork(&self, params: store::PrepareForkParams) -> store::ThreadStoreFuture<'_, store::PreparedFork> {
        self.inner.prepare_fork(params)
    }

    fn revert_thread(&self, params: store::RevertThreadParams) -> store::ThreadStoreFuture<'_, ()> {
        self.inner.revert_thread(params)
    }

    fn read_thread(&self, params: store::ReadThreadParams) -> store::ThreadStoreFuture<'_, store::StoredThread> {
        self.inner.read_thread(params)
    }

    fn read_thread_by_rollout_path(
        &self,
        params: store::ReadThreadByRolloutPathParams,
    ) -> store::ThreadStoreFuture<'_, store::StoredThread> {
        self.inner.read_thread_by_rollout_path(params)
    }

    fn list_threads(&self, params: store::ListThreadsParams) -> store::ThreadStoreFuture<'_, store::ThreadPage> {
        self.inner.list_threads(params)
    }

    fn supports_thread_sections(&self) -> bool {
        self.inner.supports_thread_sections()
    }

    fn list_thread_sections(
        &self,
        params: store::ListThreadSectionsParams,
    ) -> store::ThreadStoreFuture<'_, store::StoredThreadSectionsPage> {
        self.inner.list_thread_sections(params)
    }

    fn create_thread_section(
        &self,
        params: store::CreateThreadSectionParams,
    ) -> store::ThreadStoreFuture<'_, store::StoredThreadSection> {
        self.inner.create_thread_section(params)
    }

    fn rename_thread_section(
        &self,
        params: store::RenameThreadSectionParams,
    ) -> store::ThreadStoreFuture<'_, Option<store::StoredThreadSection>> {
        self.inner.rename_thread_section(params)
    }

    fn delete_thread_section(
        &self,
        params: store::DeleteThreadSectionParams,
    ) -> store::ThreadStoreFuture<'_, bool> {
        self.inner.delete_thread_section(params)
    }

    fn supports_projects(&self) -> bool {
        self.inner.supports_projects()
    }

    fn list_projects(
        &self,
        params: store::ListProjectsParams,
    ) -> store::ThreadStoreFuture<'_, store::StoredProjectsPage> {
        self.inner.list_projects(params)
    }

    fn read_project(&self, project_id: String) -> store::ThreadStoreFuture<'_, Option<store::StoredProject>> {
        self.inner.read_project(project_id)
    }

    fn create_project(
        &self,
        params: store::CreateProjectParams,
    ) -> store::ThreadStoreFuture<'_, store::CreatedProject> {
        self.inner.create_project(params)
    }

    fn update_project(
        &self,
        params: store::UpdateProjectParams,
    ) -> store::ThreadStoreFuture<'_, Option<store::UpdatedProject>> {
        self.inner.update_project(params)
    }

    fn move_project(
        &self,
        params: store::MoveProjectParams,
    ) -> store::ThreadStoreFuture<'_, Option<store::ProjectMoveOutcome>> {
        self.inner.move_project(params)
    }

    fn delete_project(&self, project_id: String) -> store::ThreadStoreFuture<'_, Option<store::DeletedProject>> {
        self.inner.delete_project(project_id)
    }

    fn supports_paginated_history_lists(&self) -> bool {
        self.inner.supports_paginated_history_lists()
    }

    fn search_threads(
        &self,
        params: store::SearchThreadsParams,
    ) -> store::ThreadStoreFuture<'_, store::ThreadSearchPage> {
        self.inner.search_threads(params)
    }

    fn search_thread_occurrences(
        &self,
        params: store::SearchThreadOccurrencesParams,
    ) -> store::ThreadStoreFuture<'_, store::ThreadOccurrenceSearchPage> {
        self.inner.search_thread_occurrences(params)
    }

    fn list_turns(&self, params: store::ListTurnsParams) -> store::ThreadStoreFuture<'_, store::TurnPage> {
        self.inner.list_turns(params)
    }

    fn list_items(&self, params: store::ListItemsParams) -> store::ThreadStoreFuture<'_, store::ItemPage> {
        self.inner.list_items(params)
    }

    fn update_thread_metadata(
        &self,
        params: store::UpdateThreadMetadataParams,
    ) -> store::ThreadStoreFuture<'_, Option<store::StoredThread>> {
        self.inner.update_thread_metadata(params)
    }

    fn move_thread_to_section(
        &self,
        params: store::MoveThreadToSectionParams,
    ) -> store::ThreadStoreFuture<'_, ()> {
        self.inner.move_thread_to_section(params)
    }

    fn archive_thread(&self, params: store::ArchiveThreadParams) -> store::ThreadStoreFuture<'_, ()> {
        self.inner.archive_thread(params)
    }

    fn archive_threads(
        &self,
        params: store::ArchiveThreadsParams,
    ) -> store::ThreadStoreFuture<'_, Vec<ThreadId>> {
        self.inner.archive_threads(params)
    }

    fn unarchive_thread(&self, params: store::ArchiveThreadParams) -> store::ThreadStoreFuture<'_, store::StoredThread> {
        self.inner.unarchive_thread(params)
    }

    fn delete_thread(&self, params: store::DeleteThreadParams) -> store::ThreadStoreFuture<'_, ()> {
        self.inner.delete_thread(params)
    }

    fn delete_threads(&self, params: store::DeleteThreadsParams) -> store::ThreadStoreFuture<'_, ()> {
        self.inner.delete_threads(params)
    }
}
