use super::*;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use pretty_assertions::assert_eq;
use std::os::unix::fs::PermissionsExt;

#[tokio::test(flavor = "current_thread")]
async fn bad_prepared_program_rejects_before_journal_and_never_becomes_ambiguous() -> Result<()> {
    for change_after_prepare in [false, true] {
        let fixture = Fixture::new()?;
        let state = &fixture.state;
        let agent_id =
            codex_hepta_contracts::AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12")?;
        let workspace = fixture.temp.path().join("workspace");
        std::fs::create_dir(&workspace)?;
        let manifest = AgentManifest::new(
            agent_id.clone(),
            WorkspaceBinding::new(&workspace, state.registry.layout().fleet_root())?,
            ResourceBudget::local_default(),
        )?;
        let registered = handle(
            Arc::clone(state),
            SupervisordMethod::RegisterAgent { manifest },
        )
        .await;
        let before = match registered {
            SupervisordPayload::AgentRegistered { agent } => agent,
            other => panic!("real registration failed: {other:?}"),
        };
        let source = fixture.temp.path().join("program");
        let bytes = vec![b'a'; 70_001];
        std::fs::write(&source, &bytes)?;
        std::fs::set_permissions(&source, std::fs::Permissions::from_mode(0o555))?;
        let release =
            state
                .registry
                .install_release("prepared-bad".parse()?, &source, Vec::new())?;
        state
            .registry
            .allow_release(&agent_id, &release.release_id)?;
        let prepared = change_after_prepare
            .then(|| {
                state
                    .registry
                    .prepare_release_for_launch(&release.release_id)
            })
            .transpose()?;
        std::fs::set_permissions(&release.program, std::fs::Permissions::from_mode(0o755))?;
        std::fs::write(&release.program, vec![b'x'; bytes.len()])?;
        std::fs::set_permissions(&release.program, std::fs::Permissions::from_mode(0o555))?;
        let request_id = 8_013;
        let reply = if let Some(prepared) = prepared {
            super::super::super::mutation::handle_mutation_with_prepared_read(
                Arc::clone(state),
                request_id,
                crate::SupervisordMutation::Start,
                before.control_fence.clone(),
                Some(crate::AgentRelease::try_from(release.clone())?),
                Some(Arc::new(prepared)),
            )
            .await
        } else {
            handle_with_request_id(
                Arc::clone(state),
                request_id,
                SupervisordMethod::Start {
                    fence: before.control_fence.clone(),
                    release_id: release.release_id,
                },
            )
            .await
        };
        assert!(
            matches!(reply, SupervisordPayload::Error { ref code, .. } if code == "release_validation_rejected"),
            "{reply:?}"
        );
        let after = super::super::super::agent_status(state, &agent_id).await?;
        assert_eq!(after.control_fence, before.control_fence);
        assert_eq!(after.lifecycle, AgentLifecycle::Stopped);
        assert_eq!(after.process_id, None);
        assert_eq!(after.spawn_generation, None);
        let record = state.registry.load_agent(&agent_id)?;
        assert!(crate::read_mutation_status(record.layout.owner_run_root())?.is_none());
        assert!(
            crate::mutation_journal_slots::lookup(record.layout.owner_run_root(), request_id)?
                .is_none()
        );
        assert!(!state.recovery_observation_blocked_for(&agent_id));
        assert!(crate::lease::read_lease(record.layout.owner_run_root())?.is_none());
        fixture.cancellation.cancel();
    }
    Ok(())
}
