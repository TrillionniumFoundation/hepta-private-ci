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
        for failure in [
            ProductionWriterError::AuthorityRejected("original strict refusal".into()),
            ProductionWriterError::Durability("original strict refusal".into()),
        ] {
            let expected_class = std::mem::discriminant(&failure);
            let mut tasks =
                RuntimeTasks::new(CancellationToken::new(), Duration::from_secs(1)).unwrap();
            tasks
                .spawn_required(
                    name,
                    async move { Err(AgentdError::ProductionWriter(failure)) },
                )
                .unwrap();
            let error = tasks.observe_next().await.unwrap_err();
            let AgentdError::ProductionWriter(failure) = error else {
                panic!("authority failure changed type");
            };
            assert_eq!(std::mem::discriminant(&failure), expected_class);
            let reason = match failure {
                ProductionWriterError::AuthorityRejected(reason)
                | ProductionWriterError::Durability(reason) => reason,
                _ => panic!("changed owner failure class"),
            };
            assert_eq!(
                reason,
                format!("runtime_task={label}: original strict refusal")
            );
            assert!(tasks.failed && tasks.stopped && tasks.cancellation.is_cancelled());
            tasks.shutdown().await;
        }
    }
}
