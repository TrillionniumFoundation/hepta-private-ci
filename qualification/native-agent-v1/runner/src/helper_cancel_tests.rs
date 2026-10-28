//! Cancellation during a blocked backend preserves the original admission.

use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
use std::time::Duration;

use anyhow::Result;
use codex_hepta_native_agent::PendingTool;
use codex_hepta_native_agent::ToolObservation;
use codex_hepta_native_agent::ToolPort;
use codex_hepta_native_agent::TurnOwner;
use codex_hepta_types::RuntimeToolIntentV1;
use tokio_util::sync::CancellationToken;

use super::Fixture;
use super::call;

#[derive(Default)]
struct BlockingTools {
    entered: tokio::sync::Notify,
    starts: AtomicUsize,
    observations: AtomicUsize,
    block_observation: std::sync::atomic::AtomicBool,
    cancelled_intents: std::sync::Mutex<Vec<RuntimeToolIntentV1>>,
}

impl ToolPort for BlockingTools {
    async fn execute_or_observe(
        &self,
        _: &RuntimeToolIntentV1,
        _: &[u8],
    ) -> Result<ToolObservation> {
        self.starts.fetch_add(1, Ordering::SeqCst);
        self.entered.notify_one();
        std::future::pending().await
    }

    async fn observe(&self, _: &RuntimeToolIntentV1) -> Result<ToolObservation> {
        self.observations.fetch_add(1, Ordering::SeqCst);
        if self.block_observation.load(Ordering::SeqCst) {
            self.entered.notify_one();
            std::future::pending().await
        } else {
            Ok(ToolObservation::Accepted)
        }
    }

    async fn cancel(&self, intent: &RuntimeToolIntentV1) -> Result<()> {
        self.cancelled_intents.lock().unwrap().push(intent.clone());
        Ok(())
    }
}

async fn cancellation_interrupts_blocked_call(recovering: bool) -> Result<()> {
    let fixture = Fixture::new()?;
    let (owner, mut state) = fixture.open()?;
    let proposal = call("sum");
    let admitted = owner.admit_tool(&state.binding, &proposal).await?;
    let original = admitted.intent.clone();
    if recovering {
        state.pending_tool = Some(PendingTool {
            call: proposal.clone(),
            intent: admitted.intent,
            arguments: admitted.arguments,
            submission_attempted: true,
            cancel_requested: false,
        });
        state.tool_calls = 1;
        owner.checkpoint(&state).await?;
    }
    let tools = std::sync::Arc::new(BlockingTools::default());
    tools.block_observation.store(recovering, Ordering::SeqCst);
    let cancel = CancellationToken::new();
    let signal = cancel.clone();
    let observer = std::sync::Arc::clone(&tools);
    let cancellation = tokio::spawn(async move {
        observer.entered.notified().await;
        signal.cancel();
    });
    let result = tokio::time::timeout(
        Duration::from_secs(2),
        crate::tool_session::run_tool(
            &owner,
            tools.as_ref(),
            &mut state,
            proposal.clone(),
            Duration::from_secs(60),
            &cancel,
        ),
    )
    .await
    .expect("cancellation must interrupt the blocked backend without waiting 60 seconds")?;
    cancellation.await?;
    assert_eq!(result["status"], "pending_tool");
    assert_eq!(
        *tools.cancelled_intents.lock().unwrap(),
        vec![original.clone()]
    );
    assert_eq!(
        tools.starts.load(Ordering::SeqCst),
        usize::from(!recovering)
    );
    assert_eq!(
        tools.observations.load(Ordering::SeqCst),
        usize::from(recovering)
    );
    assert!(state.cancelled);
    let pending = state.pending_tool.as_ref().unwrap();
    assert!(pending.submission_attempted);
    assert!(pending.cancel_requested);
    assert_eq!(pending.intent, original);
    drop(owner);

    // A successful cancellation acknowledgement is not a terminal receipt.
    // A fresh owner and token only observe the exact original admission.
    let (owner, mut restored) = fixture.open()?;
    tools.block_observation.store(false, Ordering::SeqCst);
    let result = crate::tool_session::run_tool(
        &owner,
        tools.as_ref(),
        &mut restored,
        proposal,
        Duration::from_secs(1),
        &CancellationToken::new(),
    )
    .await?;
    assert_eq!(result["status"], "pending_tool");
    assert_eq!(
        tools.starts.load(Ordering::SeqCst),
        usize::from(!recovering)
    );
    assert_eq!(
        tools.observations.load(Ordering::SeqCst),
        usize::from(recovering) + 1
    );
    assert_eq!(
        *tools.cancelled_intents.lock().unwrap(),
        vec![original.clone()]
    );
    assert_eq!(restored.pending_tool.as_ref().unwrap().intent, original);
    assert!(restored.final_answer.is_none());
    Ok(())
}

#[tokio::test]
async fn external_tool_cancel_interrupts_in_flight_submission_without_replaying_it() -> Result<()> {
    cancellation_interrupts_blocked_call(false).await
}

#[tokio::test]
async fn external_tool_cancel_interrupts_in_flight_observation_without_replaying_it() -> Result<()>
{
    cancellation_interrupts_blocked_call(true).await
}
