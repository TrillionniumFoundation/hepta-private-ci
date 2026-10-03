use super::*;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
struct Spy(Arc<AtomicUsize>);
impl crate::AgentdPreparedGenerationReaderV2 for Spy {
    fn read(
        &self,
        _: u64,
        _: codex_hepta_agent_components::types::Digest32,
        _: codex_hepta_agent_components::types::Digest32,
    ) -> Result<Option<Vec<u8>>, AgentdError> {
        self.0.fetch_add(1, Ordering::SeqCst);
        Err(AgentdError::Invalid(
            "actual prepared reader reached".into(),
        ))
    }
}
#[tokio::test]
async fn prepared_gate_checks_actual_root_before_retained_reader_or_whole_slot() {
    let (directory, _registry, state) =
        isolation_tests::fixture_with_readiness(true).expect("original state");
    let calls = Arc::new(AtomicUsize::new(0));
    assert!(
        state
            .prepared_generation_reader
            .set(Arc::new(Spy(calls.clone())))
            .is_ok()
    );
    let path = directory.path().join("prepared.sock");
    let agent = state.identity.agent_id.clone();
    let state = Arc::new(state);
    let cancel = tokio_util::sync::CancellationToken::new();
    let server = crate::AgentdControlServer::bind(path.clone(), state.clone(), cancel.clone())
        .await
        .expect("real server");
    let task = tokio::spawn(server.run());
    let client = crate::AgentdClient::new(path, agent, 1).expect("client");
    let result = client
        .prepared_generation_v2(
            2,
            codex_hepta_agent_components::types::Digest32::of_bytes(b"config"),
            codex_hepta_agent_components::types::Digest32::of_bytes(b"body"),
        )
        .await;
    let Err(AgentdError::Protocol(message)) = result else {
        panic!("unqualified original reader cannot yield facts");
    };
    if unsafe { libc::geteuid() } == 0 {
        assert!(message.contains("actual prepared reader reached"));
        assert_eq!(calls.load(Ordering::SeqCst), 1);
    } else {
        assert!(message.contains("root_peer_required"));
        assert_eq!(calls.load(Ordering::SeqCst), 0);
    }
    cancel.cancel();
    task.await.expect("retirement").expect("server");
}
