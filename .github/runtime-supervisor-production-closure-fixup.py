from pathlib import Path

path = Path("codex-rs/hepta-supervisor/src/daemon.rs")
text = path.read_text(encoding="utf-8")

old_codes = '''            "generation_fenced",
            "control_state_unavailable",
            "operation_indeterminate",
'''
new_codes = '''            "generation_fenced",
            "stale_control_target",
            "operation_already_completed",
            "persistence_indeterminate",
            "recovery_required",
            "control_state_unavailable",
            "operation_indeterminate",
'''
if text.count(old_codes) != 1:
    raise SystemExit("wire-code allowlist anchor changed")
text = text.replace(old_codes, new_codes, 1)

anchor = '''    #[cfg(unix)]
    #[tokio::test(flavor = "current_thread")]
    async fn unresolved_signed_intent_keeps_daemon_reachable_but_not_ready() {
'''
test = '''    #[test]
    fn wire_preserves_control_failure_disposition_codes() {
        fn code(payload: SupervisordPayload) -> String {
            let SupervisordPayload::Error { code, .. } = payload else {
                panic!("safe rejection returned a non-error payload");
            };
            code
        }

        let agent_id = AgentId::parse(AGENT_ID).expect("fixed AgentId");
        assert_eq!(
            code(safe_rejection(
                SupervisorError::GenerationFence {
                    agent_id: agent_id.clone(),
                    runtime: 1,
                    registry: 2,
                },
                None,
                false,
            )),
            "stale_control_target"
        );
        assert_eq!(
            code(safe_rejection(
                SupervisorError::TargetReleaseUnchanged(agent_id),
                None,
                false,
            )),
            "operation_already_completed"
        );
        assert_eq!(
            code(safe_rejection(
                SupervisorError::ControlPersistenceIndeterminate("fsync result unknown".to_string()),
                None,
                true,
            )),
            "persistence_indeterminate"
        );
        assert_eq!(
            code(safe_rejection(
                SupervisorError::ControlRecoveryRequired("digest mismatch".to_string()),
                None,
                false,
            )),
            "recovery_required"
        );
    }

'''
if text.count(anchor) != 1:
    raise SystemExit("daemon test insertion anchor changed")
text = text.replace(anchor, test + anchor, 1)
path.write_text(text, encoding="utf-8")
