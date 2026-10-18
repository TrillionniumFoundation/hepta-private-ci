use std::sync::Arc;
use std::sync::Mutex;
use std::sync::OnceLock;
use std::sync::Weak;
use std::time::Duration;

use codex_extension_api::ExtensionFuture;
use codex_extension_api::ExtensionRegistryBuilder;
use codex_extension_api::ThreadIdleInput;
use codex_extension_api::ThreadLifecycleContributor;
use codex_protocol::protocol::EventMsg;
use pretty_assertions::assert_eq;
use test_case::test_case;
use tokio::sync::Notify;
use tokio::sync::oneshot;
use tokio::time::timeout;

use super::CancellationToken;
use super::SessionTask;
use super::SessionTaskResult;
use super::TaskKind;
use super::TerminalEventKind;
use super::TurnContext;
use super::TurnInput;
use super::attach_in_memory_thread_store;
use super::make_session_and_context_with_rx;
use super::recv_terminal_event;
use crate::config::Config;
use crate::session::session::RolloutPersistenceFault;
use crate::session::session::Session;

#[derive(Clone, Copy)]
enum Boundary {
    Persisted,
    MissingPersistence,
    TerminalAppendFailure,
    TaskFailure,
}

enum OutcomeTask {
    Succeeds,
    Fails,
}

impl SessionTask for OutcomeTask {
    fn kind(&self) -> TaskKind {
        TaskKind::Regular
    }
    fn span_name(&self) -> &'static str {
        "session_task.finish_outcome"
    }
    async fn run(
        self: Arc<Self>,
        _session: Arc<Session>,
        _ctx: Arc<TurnContext>,
        _input: Vec<TurnInput>,
        _cancellation_token: CancellationToken,
    ) -> SessionTaskResult {
        match self.as_ref() {
            Self::Succeeds => Ok(None),
            Self::Fails => Err(codex_protocol::error::CodexErr::Fatal(
                "fixture task failure".to_string(),
            )),
        }
    }
}

#[derive(Debug, PartialEq, Eq)]
struct AdmissionObservation {
    active_slot_empty: bool,
    admission_fenced: bool,
    completion_pending: bool,
}

struct IdleProbe {
    session: OnceLock<Weak<Session>>,
    observation: Mutex<Option<oneshot::Sender<AdmissionObservation>>>,
    release: Notify,
}

impl ThreadLifecycleContributor<Config> for IdleProbe {
    fn on_thread_idle<'a>(&'a self, _input: ThreadIdleInput<'a>) -> ExtensionFuture<'a, ()> {
        Box::pin(async move {
            let session = self
                .session
                .get()
                .and_then(Weak::upgrade)
                .unwrap_or_else(|| panic!("test session remains alive"));
            let observation = AdmissionObservation {
                active_slot_empty: session.active_turn.lock().await.is_none(),
                admission_fenced: session.has_pending_admission_fence(),
                completion_pending: session.has_pending_task_terminalization(),
            };
            let sender = self
                .observation
                .lock()
                .unwrap_or_else(|error| panic!("probe mutex: {error}"))
                .take()
                .unwrap_or_else(|| panic!("only one idle callback"));
            sender
                .send(observation)
                .unwrap_or_else(|_| panic!("probe receiver remains open"));
            self.release.notified().await;
        })
    }
}

#[test_case(Boundary::Persisted; "persisted finish opens admission")]
#[test_case(Boundary::MissingPersistence; "no-op flush does not authorize admission")]
#[test_case(Boundary::TerminalAppendFailure; "failed terminal append keeps admission fenced")]
#[test_case(Boundary::TaskFailure; "failed task never receives ordinary-success permission")]
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn ordinary_finish_callback_requires_positive_persistence(boundary: Boundary) {
    let (mut session, turn, events) = make_session_and_context_with_rx().await;
    if !matches!(boundary, Boundary::MissingPersistence) {
        attach_in_memory_thread_store(Arc::get_mut(&mut session).expect("unique test session"))
            .await;
    }
    if matches!(boundary, Boundary::TerminalAppendFailure) {
        session
            .inject_rollout_persistence_fault(RolloutPersistenceFault::TurnCompleteAppend)
            .await;
    }
    let (sender, received) = oneshot::channel();
    let probe = Arc::new(IdleProbe {
        session: OnceLock::new(),
        observation: Mutex::new(Some(sender)),
        release: Notify::new(),
    });
    let mut extensions = ExtensionRegistryBuilder::<Config>::new();
    extensions.thread_lifecycle_contributor(probe.clone());
    Arc::get_mut(&mut session)
        .expect("unique test session")
        .services
        .extensions = Arc::new(extensions.build());
    assert!(probe.session.set(Arc::downgrade(&session)).is_ok());
    session
        .spawn_task(
            turn,
            Vec::new(),
            if matches!(boundary, Boundary::TaskFailure) {
                OutcomeTask::Fails
            } else {
                OutcomeTask::Succeeds
            },
        )
        .await
        .expect("start completing task");

    let observed = timeout(Duration::from_secs(2), received)
        .await
        .expect("idle callback reached")
        .expect("probe sender alive");
    assert_eq!(
        observed,
        AdmissionObservation {
            active_slot_empty: true,
            admission_fenced: !matches!(boundary, Boundary::Persisted),
            completion_pending: true,
        }
    );
    let terminal = recv_terminal_event(&events, TerminalEventKind::TurnComplete).await;
    assert!(
        matches!(terminal.msg, EventMsg::TurnComplete(event) if event.error.is_some() == matches!(boundary, Boundary::TaskFailure))
    );
    assert_eq!(
        session.rollout_persistence_failure_generation(),
        u64::from(matches!(boundary, Boundary::TerminalAppendFailure))
    );
    let completion = session
        .pending_task_terminalization_completions
        .lock()
        .expect("completion registry")
        .first()
        .map(|(_, completion, _, _, _, _)| Arc::clone(completion))
        .expect("blocked callback retains completion tracking");
    probe.release.notify_one();
    timeout(Duration::from_secs(2), completion.wait())
        .await
        .expect("callback drains");
    assert!(!session.has_pending_task_terminalization());
    assert!(!session.has_pending_admission_fence());
}
