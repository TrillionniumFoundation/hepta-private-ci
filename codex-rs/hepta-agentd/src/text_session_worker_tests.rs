use super::*;

fn next(worker: &AgentdTextWorker) -> TextWorkerEvent {
    let deadline = std::time::Instant::now() + Duration::from_secs(3);
    loop {
        if let Some(value) = worker.try_recv().unwrap() {
            return value;
        }
        assert!(
            std::time::Instant::now() < deadline,
            "bounded text worker callback"
        );
        std::thread::sleep(Duration::from_millis(5));
    }
}

#[test]
fn missing_root_keeps_reconnect_alive_and_cannot_admit_input() {
    let directory = tempfile::tempdir().unwrap();
    let worker = AgentdTextWorker::start_authenticated(
        TextSignerEndpoint {
            socket_path: directory.path().join("not-started-root.sock"),
            owner_uid: 0,
            owner_pid: std::process::id(),
        },
        Arc::new(|| {}),
    )
    .unwrap();
    assert!(matches!(
        next(&worker),
        TextWorkerEvent::Unavailable {
            request_id: None,
            ..
        }
    ));
    worker.try_send(TextCommand::Reconnect).unwrap();
    assert!(matches!(
        next(&worker),
        TextWorkerEvent::Unavailable {
            request_id: None,
            ..
        }
    ));
    worker
        .try_send(TextCommand::Submit {
            request_id: "test:1".into(),
            text: "未认证输入不得发送".into(),
        })
        .unwrap();
    assert!(
        matches!(next(&worker), TextWorkerEvent::PreparationClosed { request_id: id, connection_id: 0, .. } if id == "test:1")
    );
    worker.try_send(TextCommand::Reconnect).unwrap();
    assert!(matches!(
        next(&worker),
        TextWorkerEvent::Unavailable {
            request_id: None,
            ..
        }
    ));
}
