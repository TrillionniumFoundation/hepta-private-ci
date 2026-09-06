//! Local-development-only turn lifecycle admission.
//!
//! This adapter is deliberately boring: it records a bounded turn start in
//! the Agent-local lease/event/outbox journal and closes the lease when the
//! host reports a terminal callback.  It never dispatches an outbox row,
//! writes the KG, changes routing, or grants production authority.

use std::sync::Arc;
use std::sync::Mutex;
use std::sync::PoisonError;

use codex_extension_api::ExtensionData;
use codex_extension_api::ExtensionFuture;
use codex_extension_api::TurnAbortInput;
use codex_extension_api::TurnErrorInput;
use codex_extension_api::TurnLifecycleContributor;
use codex_extension_api::TurnStartInput;
use codex_extension_api::TurnStopInput;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_memory::CognitiveStore;
use codex_hepta_memory::LocalLeaseOutbox;
use codex_hepta_memory::LocalReplayFinalization;
use serde_json::json;
use sha2::Digest;
use sha2::Sha256;

/// Schema version for the local lifecycle journal payloads.
pub const LOCAL_TURN_LIFECYCLE_SCHEMA_VERSION: u32 = 1;
/// A queued lifecycle intent is not an external effect.
pub const LOCAL_TURN_LIFECYCLE_EXTERNAL_EFFECTS: bool = false;
/// The adapter has no KG writer capability.
pub const LOCAL_TURN_LIFECYCLE_KG_WRITE_AUTHORITY: bool = false;
/// The adapter is not a production caller.
pub const LOCAL_TURN_LIFECYCLE_PRODUCTION_CALLER: bool = false;

const LEASE_DOMAIN: &[u8] = b"hepta-memory:local-turn-lifecycle:lease:v1";
const FENCE_DOMAIN: &[u8] = b"hepta-memory:local-turn-lifecycle:fence:v1";
const OCCURRENCE_DOMAIN: &[u8] = b"hepta-memory:local-turn-lifecycle:occurrence:v1";
const LOCAL_LIFECYCLE_IO_TIMEOUT: std::time::Duration = std::time::Duration::from_millis(250);

#[derive(Default)]
struct TurnLeaseState {
    attempted: bool,
    starting: bool,
    terminal_requested: Option<TerminalAction>,
    terminal_started: bool,
    active: Option<ActiveTurnLease>,
}

#[derive(Clone)]
enum TerminalAction {
    Stop,
    Indeterminate(String),
}

#[derive(Clone)]
struct ActiveTurnLease {
    lease: LocalLeaseOutbox,
    occurrence_key: String,
}

/// A host-turn contributor which owns no authority beyond local journal
/// admission.  The state is kept in the host-owned turn store so duplicate
/// callbacks cannot create a second lease or outcome transition.
pub(crate) struct LocalTurnLifecycleContributor {
    store: Arc<CognitiveStore>,
}

impl LocalTurnLifecycleContributor {
    pub(crate) fn new(store: Arc<CognitiveStore>) -> Self {
        Self { store }
    }

    fn state<'a>(&self, turn_store: &'a ExtensionData) -> Arc<Mutex<TurnLeaseState>> {
        turn_store.get_or_init(Mutex::default)
    }

    fn binding_digest(domain: &[u8], thread_id: &str, turn_id: &str) -> Sha256Digest {
        let mut hasher = Sha256::new();
        hasher.update((domain.len() as u64).to_be_bytes());
        hasher.update(domain);
        for part in [thread_id.as_bytes(), turn_id.as_bytes()] {
            hasher.update((part.len() as u64).to_be_bytes());
            hasher.update(part);
        }
        Sha256Digest::from_sha256_output(hasher.finalize())
    }

    fn turn_binding(input: &TurnStartInput<'_>) -> Option<(String, String, String)> {
        let thread_id = input.thread_store.level_id();
        let turn_id = input.turn_id.trim();
        // Core-generated auto-compaction IDs are process-local counters.  A
        // restarted process can emit the same `auto-compact-N` for a
        // different compaction, so they are deliberately outside this
        // durable turn identity contract until core supplies a persisted ID.
        if thread_id.trim().is_empty()
            || turn_id.is_empty()
            || input.turn_id != input.turn_store.level_id()
            || turn_id.starts_with("auto-compact-")
        {
            return None;
        }
        let lease_digest = Self::binding_digest(LEASE_DOMAIN, thread_id, turn_id);
        let fence_digest = Self::binding_digest(FENCE_DOMAIN, thread_id, turn_id);
        let occurrence_digest = Self::binding_digest(OCCURRENCE_DOMAIN, thread_id, turn_id);
        Some((
            format!("local-turn:{}", lease_digest.as_str()),
            format!("local-fence:{}", fence_digest.as_str()),
            format!("local-turn-start:{}", occurrence_digest.as_str()),
        ))
    }

    async fn complete(active: ActiveTurnLease, action: TerminalAction) -> bool {
        let ActiveTurnLease {
            lease,
            occurrence_key,
        } = active;
        // `release` is deliberately guarded by the local journal: it cannot
        // close a lease while an admitted occurrence is still queued or
        // indeterminate.  Settle this contributor's one occurrence first,
        // then use the status-aware finalizer so a crash between the two
        // transactions remains replayable and no intent is stranded behind a
        // terminal fence.
        let settled = match action {
            TerminalAction::Stop => {
                tokio::time::timeout(
                    LOCAL_LIFECYCLE_IO_TIMEOUT,
                    lease.rollback_occurrence(
                        occurrence_key.clone(),
                        "local_turn_stopped_without_external_dispatch",
                    ),
                )
                .await
            }
            TerminalAction::Indeterminate(reason) => {
                tokio::time::timeout(
                    LOCAL_LIFECYCLE_IO_TIMEOUT,
                    lease.mark_indeterminate(occurrence_key.clone(), reason),
                )
                .await
            }
        };
        if match settled {
            Ok(result) => result.is_err(),
            Err(_) => true,
        } {
            // Unknown/failed host outcomes remain quarantined locally.  A
            // callback has no error channel, so retain the exact handle for a
            // later replay rather than attempting an unguarded release.
            return false;
        }

        match tokio::time::timeout(
            LOCAL_LIFECYCLE_IO_TIMEOUT,
            lease.finalize_replayed_occurrence(occurrence_key),
        )
        .await
        {
            Ok(Ok(LocalReplayFinalization::Released { .. })) => true,
            // A settled occurrence should never become queued/not-admitted;
            // treating either result as a failed completion keeps the handle
            // recoverable and preserves fail-closed behavior on a damaged or
            // concurrently changed journal.
            Ok(Ok(LocalReplayFinalization::Queued(_)))
            | Ok(Ok(LocalReplayFinalization::NotAdmitted))
            | Ok(Err(_))
            | Err(_) => false,
        }
    }

    async fn finish(&self, turn_store: &ExtensionData, action: TerminalAction) {
        let state = turn_store.get::<Mutex<TurnLeaseState>>();
        let Some(state) = state else {
            return;
        };
        let active = {
            let mut guard = state.lock().unwrap_or_else(PoisonError::into_inner);
            if guard.terminal_started {
                return;
            }
            if guard.starting {
                // Keep the first terminal observation.  Core may emit an
                // error followed by abort/stop; replacing it would make the
                // durable outcome depend on callback ordering.
                guard.terminal_requested.get_or_insert(action);
                return;
            }
            let Some(active) = guard.active.clone() else {
                return;
            };
            guard.terminal_started = true;
            active
        };
        let completed = Self::complete(active.clone(), action).await;
        let mut guard = state.lock().unwrap_or_else(PoisonError::into_inner);
        if completed {
            guard.active = None;
        } else {
            // Keep the handle recoverable and permit a later terminal
            // callback/replay to retry.  A timeout or corrupt chain must not
            // become a silently lost terminal transition.
            guard.terminal_started = false;
            guard.active = Some(active);
        }
    }

    fn bounded_reason(value: impl std::fmt::Debug) -> String {
        // Limit by Unicode scalar values, not a raw byte offset: Debug output
        // may contain multi-byte text and lifecycle callbacks have no error
        // channel through which a truncation panic could be reported.
        format!("{value:?}").chars().take(256).collect()
    }
}

impl TurnLifecycleContributor for LocalTurnLifecycleContributor {
    fn on_turn_start<'a>(&'a self, input: TurnStartInput<'a>) -> ExtensionFuture<'a, ()> {
        Box::pin(async move {
            let state = self.state(input.turn_store);
            {
                let mut guard = state.lock().unwrap_or_else(PoisonError::into_inner);
                if guard.attempted {
                    return;
                }
                // Set this before the first await.  A duplicate callback in
                // the same host turn therefore cannot race into a second
                // acquire/admit attempt.
                guard.attempted = true;
                guard.starting = true;
            }

            let Some((lease_id, fence, occurrence_key)) = Self::turn_binding(&input) else {
                state
                    .lock()
                    .unwrap_or_else(PoisonError::into_inner)
                    .starting = false;
                return;
            };
            let acquired = self
                .store
                .acquire_local_lease(lease_id, /*generation*/ 1, fence);
            let acquired = match tokio::time::timeout(LOCAL_LIFECYCLE_IO_TIMEOUT, acquired).await {
                Ok(result) => result,
                Err(_) => {
                    let mut guard = state.lock().unwrap_or_else(PoisonError::into_inner);
                    guard.starting = false;
                    // Permit a host replay to retry a transient/unavailable
                    // acquire; no scheduler or background retry is created.
                    guard.attempted = false;
                    return;
                }
            };
            let (lease, replayed) = match acquired {
                Ok(codex_hepta_memory::LocalLeaseAcquire::Acquired(lease)) => (lease, false),
                Ok(codex_hepta_memory::LocalLeaseAcquire::Replay(lease)) => (lease, true),
                Err(_) => {
                    let mut guard = state.lock().unwrap_or_else(PoisonError::into_inner);
                    guard.starting = false;
                    guard.attempted = false;
                    return;
                }
            };

            // A process can die after an indeterminate transition has been
            // committed but before the lease release.  On an exact replay,
            // inspect and finalize that occurrence atomically instead of
            // calling `admit` (which must reject non-queued states).  A
            // queued replay keeps the original receipt and remains local
            // metadata; no dispatch path is reachable here.
            let already_admitted = if replayed {
                let recovered = tokio::time::timeout(
                    LOCAL_LIFECYCLE_IO_TIMEOUT,
                    lease.finalize_replayed_occurrence(occurrence_key.clone()),
                )
                .await;
                match recovered {
                    Ok(Ok(LocalReplayFinalization::NotAdmitted)) => false,
                    Ok(Ok(LocalReplayFinalization::Queued(_))) => true,
                    Ok(Ok(LocalReplayFinalization::Released { .. })) => {
                        let mut guard = state.lock().unwrap_or_else(PoisonError::into_inner);
                        guard.starting = false;
                        guard.terminal_started = true;
                        guard.active = None;
                        return;
                    }
                    Ok(Err(_)) | Err(_) => {
                        // Preserve the verified handle for a later terminal
                        // callback.  A corrupt/stale chain is never hidden by
                        // an eager release or a background retry.
                        let mut guard = state.lock().unwrap_or_else(PoisonError::into_inner);
                        guard.starting = false;
                        guard.active = Some(ActiveTurnLease {
                            lease,
                            occurrence_key,
                        });
                        return;
                    }
                }
            } else {
                false
            };
            if !already_admitted {
                let payload = json!({
                    "schema_version": LOCAL_TURN_LIFECYCLE_SCHEMA_VERSION,
                    "kind": "turn_start",
                    "thread_id_sha256": Self::binding_digest(
                        b"hepta-memory:local-turn-lifecycle:thread:v1",
                        input.thread_store.level_id(),
                        "",
                    ),
                    "turn_id_sha256": Sha256Digest::for_bytes(input.turn_id.as_bytes()),
                    "external_effect": LOCAL_TURN_LIFECYCLE_EXTERNAL_EFFECTS,
                    "kg_write_authority": LOCAL_TURN_LIFECYCLE_KG_WRITE_AUTHORITY,
                    "production_caller": LOCAL_TURN_LIFECYCLE_PRODUCTION_CALLER,
                })
                .to_string();
                let admitted = tokio::time::timeout(
                    LOCAL_LIFECYCLE_IO_TIMEOUT,
                    lease.admit(
                        occurrence_key.clone(),
                        "codex.turn.lifecycle.start.v1",
                        payload,
                    ),
                )
                .await;
                if match admitted {
                    Ok(result) => result.is_err(),
                    Err(_) => true,
                } {
                    // Leave the active lease for exact replay/recovery.  An
                    // admission error may indicate a corrupt or stale chain;
                    // releasing here would hide that evidence and violate
                    // fail-closed semantics.
                    let mut guard = state.lock().unwrap_or_else(PoisonError::into_inner);
                    guard.starting = false;
                    guard.active = Some(ActiveTurnLease {
                        lease,
                        occurrence_key,
                    });
                    return;
                }
            }
            let pending = {
                let mut guard = state.lock().unwrap_or_else(PoisonError::into_inner);
                guard.starting = false;
                if let Some(action) = guard.terminal_requested.take() {
                    guard.terminal_started = true;
                    Some(action)
                } else {
                    guard.active = Some(ActiveTurnLease {
                        lease: lease.clone(),
                        occurrence_key: occurrence_key.clone(),
                    });
                    None
                }
            };
            if let Some(action) = pending {
                let completed = Self::complete(
                    ActiveTurnLease {
                        lease: lease.clone(),
                        occurrence_key: occurrence_key.clone(),
                    },
                    action,
                )
                .await;
                let mut guard = state.lock().unwrap_or_else(PoisonError::into_inner);
                if completed {
                    guard.active = None;
                } else {
                    guard.terminal_started = false;
                    guard.active = Some(ActiveTurnLease {
                        lease,
                        occurrence_key,
                    });
                }
            }
        })
    }

    fn on_turn_stop<'a>(&'a self, input: TurnStopInput<'a>) -> ExtensionFuture<'a, ()> {
        Box::pin(async move {
            self.finish(input.turn_store, TerminalAction::Stop).await;
        })
    }

    fn on_turn_abort<'a>(&'a self, input: TurnAbortInput<'a>) -> ExtensionFuture<'a, ()> {
        Box::pin(async move {
            self.finish(
                input.turn_store,
                TerminalAction::Indeterminate(format!(
                    "turn_aborted:{}",
                    Self::bounded_reason(input.reason)
                )),
            )
            .await;
        })
    }

    fn on_turn_error<'a>(&'a self, input: TurnErrorInput<'a>) -> ExtensionFuture<'a, ()> {
        Box::pin(async move {
            // A mismatched callback must not attach an error reason to a
            // different turn's durable occurrence.
            if input.turn_id != input.turn_store.level_id() {
                return;
            }
            self.finish(
                input.turn_store,
                TerminalAction::Indeterminate(format!(
                    "turn_error:{}:{}",
                    Sha256Digest::for_bytes(input.turn_id.as_bytes()).as_str(),
                    Self::bounded_reason(input.error)
                )),
            )
            .await;
        })
    }
}

#[cfg(test)]
mod tests {
    use std::fs;

    use codex_extension_api::TurnLifecycleContributor;
    use codex_hepta_contracts::AgentId;
    use codex_hepta_paths::HeptaFleetRoot;
    use codex_protocol::config_types::CollaborationMode;
    use codex_protocol::config_types::ModeKind;
    use codex_protocol::config_types::Settings;
    use codex_protocol::protocol::TokenUsage;
    use tempfile::TempDir;

    use super::*;

    fn start_input<'a>(
        turn_id: &'a str,
        session_store: &'a ExtensionData,
        thread_store: &'a ExtensionData,
        turn_store: &'a ExtensionData,
        mode: &'a CollaborationMode,
        usage: &'a TokenUsage,
    ) -> TurnStartInput<'a> {
        TurnStartInput {
            turn_id,
            origin: codex_extension_api::TurnStartOrigin::NewTurn,
            collaboration_mode: mode,
            token_usage_at_turn_start: usage,
            session_store,
            thread_store,
            turn_store,
        }
    }

    async fn opened_store(temp: &TempDir) -> Arc<CognitiveStore> {
        let fleet_root = temp.path().join("fleet");
        fs::create_dir_all(&fleet_root).expect("fleet root");
        let fleet = HeptaFleetRoot::parse(fleet_root).expect("fleet root parse");
        let owner = AgentId::parse("00000000-0000-4000-8000-000000000901").expect("owner");
        Arc::new(
            CognitiveStore::open(&fleet.layout().agent(&owner))
                .await
                .expect("cognitive store"),
        )
    }

    fn mode() -> CollaborationMode {
        CollaborationMode {
            mode: ModeKind::Default,
            settings: Settings {
                model: "test-model".to_string(),
                reasoning_effort: None,
                developer_instructions: None,
            },
        }
    }

    #[test]
    fn process_local_auto_compact_ids_are_not_durable_bindings() {
        let session = ExtensionData::new("session");
        let thread = ExtensionData::new("thread");
        let turn = ExtensionData::new("turn");
        let mode = mode();
        let usage = TokenUsage::default();
        let input = start_input("auto-compact-0", &session, &thread, &turn, &mode, &usage);
        assert!(LocalTurnLifecycleContributor::turn_binding(&input).is_none());
        assert!(LocalTurnLifecycleContributor::bounded_reason("é".repeat(1024)).len() <= 1024);
    }

    #[tokio::test]
    async fn duplicate_start_is_one_local_intent_and_stop_is_idempotent() {
        let temp = TempDir::new().expect("temp dir");
        let store = opened_store(&temp).await;
        let contributor = LocalTurnLifecycleContributor::new(Arc::clone(&store));
        let session = ExtensionData::new("session");
        let thread = ExtensionData::new("thread");
        let turn = ExtensionData::new("turn-901");
        let mode = mode();
        let usage = TokenUsage::default();

        contributor
            .on_turn_start(start_input(
                "turn-901", &session, &thread, &turn, &mode, &usage,
            ))
            .await;
        contributor
            .on_turn_start(start_input(
                "turn-901", &session, &thread, &turn, &mode, &usage,
            ))
            .await;

        let state = turn.get::<Mutex<TurnLeaseState>>().expect("turn state");
        let active = state
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
            .active
            .clone()
            .expect("active lease");
        let counts = active.lease.snapshot_counts().await.expect("counts");
        assert_eq!(counts.event_rows, 1);
        assert_eq!(counts.outbox_rows, 1);

        contributor
            .on_turn_stop(TurnStopInput {
                session_store: &session,
                thread_store: &thread,
                turn_store: &turn,
            })
            .await;
        contributor
            .on_turn_stop(TurnStopInput {
                session_store: &session,
                thread_store: &thread,
                turn_store: &turn,
            })
            .await;
        assert!(
            store
                .acquire_local_lease(active.lease.lease_id(), 1, active.lease.fencing_token(),)
                .await
                .is_err()
        );
    }

    #[tokio::test]
    async fn active_lease_replays_after_host_store_restart() {
        let temp = TempDir::new().expect("temp dir");
        let store = opened_store(&temp).await;
        let first = LocalTurnLifecycleContributor::new(Arc::clone(&store));
        let session = ExtensionData::new("session");
        let thread = ExtensionData::new("thread");
        let first_turn = ExtensionData::new("turn-902");
        let mode = mode();
        let usage = TokenUsage::default();
        first
            .on_turn_start(start_input(
                "turn-902",
                &session,
                &thread,
                &first_turn,
                &mode,
                &usage,
            ))
            .await;

        let restarted = LocalTurnLifecycleContributor::new(Arc::clone(&store));
        let restarted_turn = ExtensionData::new("turn-902");
        restarted
            .on_turn_start(start_input(
                "turn-902",
                &session,
                &thread,
                &restarted_turn,
                &mode,
                &usage,
            ))
            .await;
        let state = restarted_turn
            .get::<Mutex<TurnLeaseState>>()
            .expect("restarted state");
        let active = state
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
            .active
            .clone()
            .expect("replayed active lease");
        let counts = active.lease.snapshot_counts().await.expect("counts");
        assert_eq!(counts.lease_rows, 1);
        assert_eq!(counts.event_rows, 1);
        assert_eq!(counts.outbox_rows, 1);
    }

    #[tokio::test]
    async fn acquire_before_admit_replays_and_retries_local_admission() {
        let temp = TempDir::new().expect("temp dir");
        let store = opened_store(&temp).await;
        let session = ExtensionData::new("session");
        let thread = ExtensionData::new("thread-902-admit");
        let turn = ExtensionData::new("turn-902-admit");
        let mode = mode();
        let usage = TokenUsage::default();
        let input = start_input("turn-902-admit", &session, &thread, &turn, &mode, &usage);
        let (lease_id, fence, _) =
            LocalTurnLifecycleContributor::turn_binding(&input).expect("durable binding");
        let acquired = store
            .acquire_local_lease(lease_id, 1, fence)
            .await
            .expect("acquire before admission");
        assert!(matches!(
            acquired,
            codex_hepta_memory::LocalLeaseAcquire::Acquired(_)
        ));
        drop(acquired);

        // Restarting the host sees an active replay with no event/outbox row.
        // Recovery must classify it as NotAdmitted and finish the original
        // local admission, rather than leaving the turn permanently active.
        let restarted = LocalTurnLifecycleContributor::new(Arc::clone(&store));
        restarted.on_turn_start(input).await;
        let state = turn.get::<Mutex<TurnLeaseState>>().expect("turn state");
        let active = state
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
            .active
            .clone()
            .expect("admitted active lease");
        assert_eq!(
            active.lease.snapshot_counts().await.expect("counts"),
            codex_hepta_memory::LocalLeaseOutboxCounts {
                lease_rows: 1,
                event_rows: 1,
                outbox_rows: 1,
            }
        );
    }

    #[tokio::test]
    async fn indeterminate_crash_window_replays_as_terminal_and_releases() {
        let temp = TempDir::new().expect("temp dir");
        let store = opened_store(&temp).await;
        let first = LocalTurnLifecycleContributor::new(Arc::clone(&store));
        let session = ExtensionData::new("session");
        let thread = ExtensionData::new("thread-903");
        let first_turn = ExtensionData::new("turn-903");
        let mode = mode();
        let usage = TokenUsage::default();
        first
            .on_turn_start(start_input(
                "turn-903",
                &session,
                &thread,
                &first_turn,
                &mode,
                &usage,
            ))
            .await;
        let first_state = first_turn
            .get::<Mutex<TurnLeaseState>>()
            .expect("first state");
        let active = first_state
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
            .active
            .clone()
            .expect("active lease");
        active
            .lease
            .mark_indeterminate(active.occurrence_key.clone(), "simulated-crash-window")
            .await
            .expect("mark indeterminate");
        // Drop the host turn state without invoking stop/abort: this models a
        // process exit after the durable outcome row and before release.
        drop(first_turn);
        drop(first);

        let restarted = LocalTurnLifecycleContributor::new(Arc::clone(&store));
        let restarted_turn = ExtensionData::new("turn-903");
        restarted
            .on_turn_start(start_input(
                "turn-903",
                &session,
                &thread,
                &restarted_turn,
                &mode,
                &usage,
            ))
            .await;
        let restarted_state = restarted_turn
            .get::<Mutex<TurnLeaseState>>()
            .expect("restarted state");
        let guard = restarted_state
            .lock()
            .unwrap_or_else(PoisonError::into_inner);
        assert!(guard.active.is_none());
        assert!(guard.terminal_started);
        drop(guard);
        assert_eq!(
            active.lease.snapshot_counts().await.expect("counts"),
            codex_hepta_memory::LocalLeaseOutboxCounts {
                lease_rows: 2,
                event_rows: 2,
                outbox_rows: 1,
            }
        );
        assert!(
            store
                .acquire_local_lease(active.lease.lease_id(), 1, active.lease.fencing_token())
                .await
                .is_err()
        );
    }
}
