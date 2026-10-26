use super::*;
use codex_hepta_memory::ProductionWriterError;
use pretty_assertions::assert_eq;

#[tokio::test]
async fn owner_authority_failure_keeps_its_variant_and_only_a_static_task_label() {
    for (name, label) in [
        (
            "production-operation-reconciler",
            "production-operation-reconciler",
        ),
        ("codex-app-server", "codex-app-server"),
        ("untrusted-looking-task-name", "other-runtime-task"),
    ] {
        let mut tasks =
            RuntimeTasks::new(CancellationToken::new(), Duration::from_secs(1)).unwrap();
        tasks
            .spawn_required(name, async {
                Err(AgentdError::ProductionWriter(
                    ProductionWriterError::AuthorityRejected("original strict refusal".into()),
                ))
            })
            .unwrap();
        let error = tasks.observe_next().await.unwrap_err();
        let AgentdError::ProductionWriter(ProductionWriterError::AuthorityRejected(reason)) = error
        else {
            panic!("authority failure changed type");
        };
        assert_eq!(
            reason,
            format!("runtime_task={label}: original strict refusal")
        );
        assert!(tasks.failed && tasks.stopped && tasks.cancellation.is_cancelled());
        tasks.shutdown().await;
    }
}
