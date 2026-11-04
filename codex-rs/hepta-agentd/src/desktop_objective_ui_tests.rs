//! Exercise the actual workspace entry with the original production attachment
//! and real control server. Fixture issuers remain qualification-only.
use super::fixture::CheckpointMode;
use super::objective_control_fixture::ControlFixture;
use super::objective_control_fixture::ReplyDelivery;
use super::objective_control_fixture::TestResult;
use crate::AgentdObjectiveUiInputs;
use crate::ObjectiveClientMode;
use crate::install_original_objective_ui;
use codex_hepta_types::Digest32;
use hepta_control_core::chat::ChatWorkspace;
use hepta_control_core::chat_owner::CHAT_OWNER_PROTOCOL;
use hepta_control_core::chat_owner::OwnerScope;
use hepta_control_core::chat_owner::OwnerSession;
use hepta_control_core::objective_ui::ObjectiveUiBinding;
use pretty_assertions::assert_eq;
use std::sync::atomic::Ordering;
use std::time::Duration;

const DRAFT: &str = "Read the current task";

fn presentation() -> TestResult<(ChatWorkspace, ObjectiveUiBinding, OwnerSession)> {
    let now = crate::authbus_ingress::now_ms()?;
    let scope = OwnerScope {
        principal_id: "principal.production".to_string(),
        session_id: "session.original".to_string(),
        connection_generation: 1,
        permission_revision: 1,
        agent_id: "00000000-0000-4000-8000-00000000c062".to_string(),
        agent_generation: 1,
        thread_id: "thread.objective".to_string(),
    };
    let session = OwnerSession {
        protocol: CHAT_OWNER_PROTOCOL.to_string(),
        scope: scope.clone(),
        expires_at_ms: now + 180_000,
        capabilities: vec![],
    };
    let mut workspace = ChatWorkspace::default();
    workspace
        .install_owner(session.clone(), now)
        .map_err(|error| format!("{error:?}"))?;
    if !workspace.edit(DRAFT.to_string()) {
        return Err("draft edit rejected".into());
    }
    let binding = ObjectiveUiBinding {
        owner: scope,
        owner_expires_at_ms: session.expires_at_ms,
        window_id: "window.original".to_string(),
        window_generation: 1,
        presentation_epoch: workspace.presentation_epoch(),
        room: workspace.active_id(),
        draft_sha256: *Digest32::of_bytes(DRAFT.as_bytes()).as_array(),
    };
    Ok((workspace, binding, session))
}

fn install(
    workspace: &mut ChatWorkspace,
    fixture: &mut ControlFixture,
    binding: ObjectiveUiBinding,
    mode: ObjectiveClientMode,
) -> TestResult {
    let inputs = AgentdObjectiveUiInputs {
        attachment: fixture.take_attachment()?,
        client: fixture.transport()?,
        original: fixture.original.clone(),
        peer: fixture.peer(),
        binding,
        mode,
        runtime: tokio::runtime::Handle::current(),
    };
    install_original_objective_ui(workspace, inputs)?;
    Ok(())
}

async fn wait_status(workspace: &mut ChatWorkspace, expected: &str) -> TestResult {
    let observed = tokio::time::timeout(Duration::from_secs(5), async {
        loop {
            workspace.poll_objective_owner();
            if workspace.owner_status(crate::authbus_ingress::now_ms()?) == expected {
                return Ok::<(), crate::AgentdError>(());
            }
            tokio::time::sleep(Duration::from_millis(10)).await;
        }
    })
    .await;
    match observed {
        Ok(result) => Ok(result?),
        Err(error) => Err(format!(
            "{error}; expected {expected:?}, observed {:?}",
            workspace.owner_status(crate::authbus_ingress::now_ms()?)
        )
        .into()),
    }
}

#[tokio::test]
async fn real_workspace_submit_duplicate_click_and_cancel_use_one_original_owner() -> TestResult {
    let (mut workspace, binding, _) = presentation()?;
    let mut fixture =
        ControlFixture::new(&binding.original_run_id(), DRAFT, ReplyDelivery::Complete).await?;
    install(
        &mut workspace,
        &mut fixture,
        binding,
        ObjectiveClientMode::Initial,
    )?;
    insta::assert_snapshot!(format!(
        "status: {}\nsubmit: {}\ncancel: {}\nrefresh: {}\ndraft: {}",
        workspace.owner_status(crate::authbus_ingress::now_ms()?),
        workspace.objective_can_submit(),workspace.objective_can_cancel(),
        workspace.objective_can_refresh(),workspace.draft().text,
    ), @r###"
    status: An independently authorized request is ready.
    submit: true
    cancel: true
    refresh: false
    draft: Read the current task
    "###);
    assert!(workspace.request_send());
    assert!(workspace.request_send());
    wait_status(
        &mut workspace,
        "Request admitted; no completed response has been observed.",
    )
    .await?;
    insta::assert_snapshot!(format!(
        "status: {}\nsubmit: {}\ncancel: {}\nrefresh: {}\ndraft: {}",
        workspace.owner_status(crate::authbus_ingress::now_ms()?),
        workspace.objective_can_submit(),workspace.objective_can_cancel(),
        workspace.objective_can_refresh(),workspace.draft().text,
    ), @r###"
    status: Request admitted; no completed response has been observed.
    submit: false
    cancel: true
    refresh: true
    draft: Read the current task
    "###);
    assert!(workspace.request_objective_cancel());
    assert!(workspace.request_objective_cancel());
    wait_status(
        &mut workspace,
        "The owner acknowledged cancellation before dispatch.",
    )
    .await?;
    assert!(!workspace.objective_can_cancel());
    assert_eq!(fixture.starts.load(Ordering::SeqCst), 1);
    assert_eq!(fixture.probes.target.effects.load(Ordering::SeqCst), 0);
    drop(workspace);
    fixture.finish().await
}

#[tokio::test]
async fn real_workspace_lost_ack_and_recovered_window_never_send_a_second_request() -> TestResult {
    let (mut workspace, binding, session) = presentation()?;
    let mut fixture = ControlFixture::new(
        &binding.original_run_id(),
        DRAFT,
        ReplyDelivery::DropFirstSubmissionAck,
    )
    .await?;
    install(
        &mut workspace,
        &mut fixture,
        binding.clone(),
        ObjectiveClientMode::Initial,
    )?;
    assert!(workspace.request_send());
    wait_status(
        &mut workspace,
        "The outcome is unknown. Refresh the original request without sending again.",
    )
    .await?;
    assert!(!workspace.objective_can_submit());
    assert!(workspace.request_send());
    assert_eq!(fixture.starts.load(Ordering::SeqCst), 1);
    drop(workspace);

    let mut recovered = ChatWorkspace::default();
    recovered
        .install_owner(session, crate::authbus_ingress::now_ms()?)
        .map_err(|error| format!("{error:?}"))?;
    assert!(recovered.edit(DRAFT.to_string()));
    install(
        &mut recovered,
        &mut fixture,
        binding,
        ObjectiveClientMode::Recovered,
    )?;
    assert!(!recovered.objective_can_submit());
    assert!(recovered.request_send());
    assert!(recovered.request_objective_refresh());
    wait_status(
        &mut recovered,
        "Request admitted; no completed response has been observed.",
    )
    .await?;
    assert_eq!(fixture.starts.load(Ordering::SeqCst), 1);
    assert_eq!(fixture.probes.target.effects.load(Ordering::SeqCst), 0);
    drop(recovered);
    fixture.finish().await
}

#[tokio::test]
async fn signed_window_generation_and_draft_binding_reject_cross_window_adoption() -> TestResult {
    let (mut workspace, binding, _) = presentation()?;
    let mut fixture =
        ControlFixture::new(&binding.original_run_id(), DRAFT, ReplyDelivery::Complete).await?;
    let mut other = binding.clone();
    other.window_generation += 1;
    assert!(
        install(
            &mut workspace,
            &mut fixture,
            other,
            ObjectiveClientMode::Initial
        )
        .is_err()
    );
    assert!(!workspace.objective_installed());
    assert!(workspace.edit("Changed draft".to_string()));
    assert!(
        install(
            &mut workspace,
            &mut fixture,
            binding,
            ObjectiveClientMode::Initial
        )
        .is_err()
    );
    assert!(!workspace.request_send());
    assert_eq!(fixture.starts.load(Ordering::SeqCst), 0);
    drop(workspace);
    fixture.finish().await
}

#[tokio::test]
async fn owner_session_rotation_closes_a_waiting_checkpoint_without_late_dispatch() -> TestResult {
    let (mut workspace, binding, mut session) = presentation()?;
    let mut fixture =
        ControlFixture::new(&binding.original_run_id(), DRAFT, ReplyDelivery::Complete).await?;
    *fixture.probes.checkpoint.mode.lock().unwrap() = CheckpointMode::Hold;
    install(
        &mut workspace,
        &mut fixture,
        binding,
        ObjectiveClientMode::Initial,
    )?;
    assert!(workspace.request_send());
    tokio::time::timeout(Duration::from_secs(3), async {
        loop {
            if fixture.probes.checkpoint.seen.lock().unwrap().len() >= 2 {
                break;
            }
            tokio::task::yield_now().await;
        }
    })
    .await?;
    session.scope.session_id = "session.rotated".to_string();
    session.scope.connection_generation += 1;
    workspace
        .install_owner(session, crate::authbus_ingress::now_ms()?)
        .map_err(|error| format!("{error:?}"))?;
    *fixture.probes.checkpoint.mode.lock().unwrap() = CheckpointMode::Accept;
    tokio::task::yield_now().await;
    assert!(!workspace.objective_installed());
    assert!(!workspace.poll_objective_owner());
    assert_eq!(fixture.starts.load(Ordering::SeqCst), 0);
    let mut recovered = fixture.client(ObjectiveClientMode::Recovered)?;
    assert!(matches!(
        recovered.refresh().await?.latest,
        crate::ObjectiveAdmissionOutcome::Unknown { .. }
    ));
    assert_eq!(fixture.starts.load(Ordering::SeqCst), 0);
    drop(recovered);
    drop(workspace);
    fixture.finish().await
}

#[tokio::test]
async fn real_workspace_cancel_before_submit_keeps_draft_and_never_dispatches() -> TestResult {
    let (mut workspace, binding, _) = presentation()?;
    let mut fixture =
        ControlFixture::new(&binding.original_run_id(), DRAFT, ReplyDelivery::Complete).await?;
    install(
        &mut workspace,
        &mut fixture,
        binding,
        ObjectiveClientMode::Initial,
    )?;
    assert!(workspace.request_objective_cancel());
    wait_status(
        &mut workspace,
        "Cancelled before the original request was dispatched.",
    )
    .await?;
    assert!(workspace.request_send());
    assert_eq!(workspace.draft().text, DRAFT);
    assert_eq!(fixture.starts.load(Ordering::SeqCst), 0);
    assert_eq!(fixture.probes.target.effects.load(Ordering::SeqCst), 0);
    drop(workspace);
    fixture.finish().await
}
