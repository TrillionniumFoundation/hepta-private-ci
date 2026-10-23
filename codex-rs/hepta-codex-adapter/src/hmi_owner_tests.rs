//! Synthetic owner/media peers exercise wiring, not real authority or devices.
use super::*;
use crate::hmi::tests::*;
use futures::StreamExt;
use serde_json::json;
use std::collections::BTreeMap;
use std::sync::atomic::AtomicBool;
use tokio_tungstenite::accept_async;

#[derive(Clone)]
struct FixtureAuthority(Arc<AtomicBool>);
impl HmiOwnerAuthorityV1 for FixtureAuthority {
    fn check_current(&self, _: &HmiBindingV1) -> Result<(), HmiError> {
        if self.0.load(Ordering::SeqCst) {
            Ok(())
        } else {
            Err(HmiError::Fenced)
        }
    }
}
#[derive(Clone)]
struct FixtureMedia {
    connection: u64,
    file: std::path::PathBuf,
    calls: Arc<Mutex<Vec<String>>>,
    speech: Arc<Mutex<Vec<HmiSpeechRequestV1>>>,
    stop_fails: Arc<AtomicBool>,
}
impl Drop for FixtureMedia {
    fn drop(&mut self) {
        let _ = std::fs::remove_file(&self.file);
    }
}
impl HmiOwnerMediaV1 for FixtureMedia {
    fn connection_id(&self) -> u64 {
        self.connection
    }
    fn capture_generation(&self) -> u64 {
        1
    }
    async fn verify_source(&self, source: &HmiCapturedAudioRefV1) -> Result<(), HmiError> {
        let data = std::fs::read(&self.file).map_err(|e| HmiError::Protocol(e.to_string()))?;
        if Digest32::of_bytes(&data).to_string() != source.sha256 {
            return Err(HmiError::Identity);
        }
        self.calls.lock().unwrap().push("verify".into());
        Ok(())
    }
    async fn attach_turn(&self, _: &HmiOutputScopeV1) -> Result<(), HmiError> {
        self.calls.lock().unwrap().push("attach".into());
        Ok(())
    }
    async fn speak(&self, request: HmiSpeechRequestV1) -> Result<HmiMediaPresentationV1, HmiError> {
        self.speech.lock().unwrap().push(request);
        self.calls.lock().unwrap().push("speak".into());
        Ok(HmiMediaPresentationV1::Queued)
    }
    async fn retire_output(&self, epoch: u64) -> Result<(), HmiError> {
        self.calls.lock().unwrap().push(format!("stop:{epoch}"));
        if self.stop_fails.load(Ordering::SeqCst) {
            Err(HmiError::Transport("fixture device unplugged".into()))
        } else {
            Ok(())
        }
    }
    async fn revoke_capture(&self) -> Result<(), HmiError> {
        self.calls.lock().unwrap().push("captureClosed".into());
        Ok(())
    }
}
#[derive(Clone)]
struct FixtureObservations {
    records: Arc<Mutex<BTreeMap<String, String>>>,
    authority: FixtureAuthority,
    revoke_after_write: bool,
}
impl HmiOwnerObservationsV1 for FixtureObservations {
    async fn observe_final(
        &self,
        _: &HmiBindingV1,
        _: &HmiOwnerTranscriptV1,
        client_id: &str,
        digest: &str,
        mode: ThreadQueueReconcileMode,
    ) -> Result<HmiObservationReceiptV1, HmiError> {
        let mut records = self.records.lock().unwrap();
        match records.get(client_id) {
            Some(previous) if previous != digest => return Err(HmiError::Identity),
            Some(_) => {}
            None if mode == ThreadQueueReconcileMode::ReconcileOnly => {
                return Err(HmiError::Invalid("missing observation"));
            }
            None => {
                records.insert(client_id.into(), digest.into());
            }
        }
        if self.revoke_after_write {
            self.authority.0.store(false, Ordering::SeqCst);
        }
        Ok(HmiObservationReceiptV1 {
            observation_id: "fixture:observation".into(),
            payload_sha256: digest.into(),
        })
    }
}
fn ports(
    connection: u64,
) -> (
    FixtureAuthority,
    FixtureMedia,
    FixtureObservations,
    HmiOwnerTranscriptV1,
) {
    let authority = FixtureAuthority(Arc::new(AtomicBool::new(true)));
    let file = std::env::temp_dir().join(format!(
        "hmi-owner-{}-{connection}.pcm16",
        std::process::id()
    ));
    std::fs::write(&file, b"abcd").unwrap();
    let media = FixtureMedia {
        connection,
        file,
        calls: Arc::default(),
        speech: Arc::default(),
        stop_fails: Arc::new(AtomicBool::new(false)),
    };
    let observations = FixtureObservations {
        records: Arc::default(),
        authority: authority.clone(),
        revoke_after_write: false,
    };
    let b = binding();
    let input = HmiOwnerTranscriptV1 {
        connection_id: connection,
        text: "你好".into(),
        finalized: true,
        source: HmiCapturedAudioRefV1 {
            stream: HmiCaptureStreamV1 {
                principal_id: b.principal_id,
                device_id: b.device_id,
                device_generation: b.device_generation,
                organ_id: b.organ_id,
                organ_generation: b.organ_generation,
                logical_session_id: b.logical_session_id,
            },
            capture_generation: 1,
            sequence: 1,
            asset_id: "capture-1-1.pcm16".into(),
            sha256: Digest32::of_bytes(b"abcd").to_string(),
            byte_length: 4,
            sample_rate: 16000,
            num_channels: 1,
            start_sample: 0,
            end_sample: 2,
        },
    };
    (authority, media, observations, input)
}

#[tokio::test]
async fn sourced_owner_routes_same_thread_output_once_and_stops_locally_before_interrupt() {
    let (listener, url) = listener().await;
    let calls = Arc::new(Mutex::new(Vec::<String>::new()));
    let peer_calls = calls.clone();
    let peer = tokio::spawn(async move {
        let mut socket = accept_async(listener.accept().await.unwrap().0)
            .await
            .unwrap();
        initialize(&mut socket).await;
        let request = read(&mut socket).await;
        assert_eq!(request["params"]["threadId"], "thread:test");
        assert_eq!(request["params"]["input"][0]["text"], "你好");
        reply(&mut socket, &request, admission(&request, false)).await;
        started(&mut socket, &request).await;
        delta(&mut socket, "thread:test", "你").await;
        for (id, text) in [("answer:test", "你好"), ("answer:two", "世界")] {
            notification(
                &mut socket,
                "item/completed",
                json!({"threadId":"thread:test","turnId":"turn:test","completedAtMs":2,
                "item":{"type":"agentMessage","id":id,"text":text,"phase":null}}),
            )
            .await;
        }
        completed(&mut socket, "completed").await;
        let replay = read(&mut socket).await;
        assert_eq!(replay["params"]["mode"], "reconcileOnly");
        assert_eq!(
            replay["params"]["clientUserMessageId"],
            request["params"]["clientUserMessageId"]
        );
        reply(&mut socket, &replay, admission(&replay, true)).await;
        let interrupt = read(&mut socket).await;
        assert_eq!(interrupt["method"], "turn/interrupt");
        assert_eq!(
            interrupt["params"],
            json!({"threadId":"thread:test","turnId":"turn:test"})
        );
        assert!(
            peer_calls
                .lock()
                .unwrap()
                .last()
                .unwrap()
                .starts_with("stop:")
        );
        peer_calls.lock().unwrap().push("remoteInterrupt".into());
        send(&mut socket,json!({"jsonrpc":"2.0","id":interrupt["id"],"error":{"code":-32000,"message":"fixture server restarting"}})).await;
        let _ = socket.next().await;
    });
    let mut connection = HmiConnectionV1::connect(
        args(&url),
        binding(),
        /*event_capacity*/ 16,
        Duration::from_secs(3),
    )
    .await
    .unwrap();
    let (authority, mut media, observations, input) = ports(connection.requests.connection_id());
    media.calls = calls.clone();
    let bridge = HmiOwnerBridgeV1::attach(
        connection.requests.clone(),
        authority,
        media.clone(),
        observations.clone(),
    )
    .unwrap();
    let admitted = bridge
        .route_transcript(input.clone(), ThreadQueueReconcileMode::AllowIfAbsent)
        .await;
    assert!(admitted.error.is_none(), "{admitted:?}");
    assert!(admitted.observation.is_some() && admitted.admission.is_some());
    let terminal = loop {
        let event = connection.events.next().await.unwrap().unwrap();
        let terminal = matches!(event.kind, HmiEventKindV1::Terminal { .. });
        let outcome = bridge.route_output(event.clone()).await;
        assert!(outcome.error.is_none(), "{outcome:?}");
        if terminal {
            assert_eq!(outcome.presentation, Some(HmiMediaPresentationV1::Queued));
            break event;
        }
    };
    assert_eq!(media.speech.lock().unwrap().len(), 1);
    let HmiSpeechRequestV1::Speak { text, .. } = media.speech.lock().unwrap()[0].clone();
    assert_eq!(text, "你好\n世界");
    let replay = bridge
        .route_transcript(input, ThreadQueueReconcileMode::AllowIfAbsent)
        .await;
    assert!(replay.error.is_none(), "{replay:?}");
    assert_eq!(observations.records.lock().unwrap().len(), 1);
    let mut stale = terminal;
    stale.scope.connection_id += 1;
    let before = calls.lock().unwrap().clone();
    let rejected = bridge.route_output(stale).await;
    assert!(rejected.error.is_some() && rejected.interruption.is_none());
    assert_eq!(*calls.lock().unwrap(), before);
    media.stop_fails.store(true, Ordering::SeqCst);
    let stopped = bridge.interrupt().await;
    assert!(stopped.local_stop_error.unwrap().contains("unplugged"));
    assert!(
        stopped
            .remote_interrupt_error
            .unwrap()
            .contains("restarting")
    );
    assert!(!stopped.terminal_observed);
    assert_eq!(media.speech.lock().unwrap().len(), 1);
    connection.events.shutdown().await.unwrap();
    peer.await.unwrap();
}

#[tokio::test]
async fn revocation_after_observation_retains_receipt_and_closes_capture_without_core_admission() {
    let (listener, url) = listener().await;
    let peer = tokio::spawn(async move {
        let mut socket = accept_async(listener.accept().await.unwrap().0)
            .await
            .unwrap();
        initialize(&mut socket).await;
        assert!(matches!(
            socket.next().await,
            Some(Ok(tokio_tungstenite::tungstenite::Message::Close(_))) | None
        ));
    });
    let connection = HmiConnectionV1::connect(
        args(&url),
        binding(),
        /*event_capacity*/ 8,
        Duration::from_secs(3),
    )
    .await
    .unwrap();
    let (authority, media, mut observations, input) = ports(connection.requests.connection_id());
    observations.revoke_after_write = true;
    let bridge = HmiOwnerBridgeV1::attach(
        connection.requests.clone(),
        authority,
        media.clone(),
        observations.clone(),
    )
    .unwrap();
    let outcome = bridge
        .route_transcript(input, ThreadQueueReconcileMode::AllowIfAbsent)
        .await;
    assert!(outcome.error.is_some() && outcome.admission.is_none());
    assert_eq!(
        outcome.observation.unwrap().observation_id,
        "fixture:observation"
    );
    assert!(outcome.interruption.is_some());
    assert_eq!(observations.records.lock().unwrap().len(), 1);
    assert_eq!(media.calls.lock().unwrap().last().unwrap(), "captureClosed");
    connection.events.shutdown().await.unwrap();
    peer.await.unwrap();
}

#[tokio::test]
async fn origin_generation_and_corrupt_media_fail_before_observation_or_core() {
    let (listener, url) = listener().await;
    let peer = tokio::spawn(async move {
        let mut socket = accept_async(listener.accept().await.unwrap().0)
            .await
            .unwrap();
        initialize(&mut socket).await;
        let _ = socket.next().await;
    });
    let connection = HmiConnectionV1::connect(
        args(&url),
        binding(),
        /*event_capacity*/ 8,
        Duration::from_secs(3),
    )
    .await
    .unwrap();
    let (authority, media, observations, input) = ports(connection.requests.connection_id());
    let bridge = HmiOwnerBridgeV1::attach(
        connection.requests.clone(),
        authority,
        media.clone(),
        observations.clone(),
    )
    .unwrap();
    let mut variants = vec![input.clone(); 4];
    variants[0].connection_id += 1;
    variants[1].source.stream.device_generation += 1;
    variants[2].finalized = false;
    variants[3].source.sha256 = "0".repeat(64);
    for invalid in variants {
        let outcome = bridge
            .route_transcript(invalid, ThreadQueueReconcileMode::AllowIfAbsent)
            .await;
        assert!(
            outcome.error.is_some() && outcome.observation.is_none() && outcome.admission.is_none()
        );
    }
    assert!(observations.records.lock().unwrap().is_empty());
    assert!(media.calls.lock().unwrap().is_empty());
    connection.events.shutdown().await.unwrap();
    peer.await.unwrap();
}

#[tokio::test]
async fn native_stop_floor_and_echo_do_not_drift_or_accept_an_old_media_reader() {
    let (listener, url) = listener().await;
    let peer = tokio::spawn(async move {
        let mut socket = accept_async(listener.accept().await.unwrap().0)
            .await
            .unwrap();
        initialize(&mut socket).await;
        let _ = socket.next().await;
    });
    let connection = HmiConnectionV1::connect(
        args(&url),
        binding(),
        /*event_capacity*/ 8,
        Duration::from_secs(3),
    )
    .await
    .unwrap();
    let (authority, media, observations, input) = ports(connection.requests.connection_id());
    let bridge = HmiOwnerBridgeV1::attach(
        connection.requests.clone(),
        authority,
        media.clone(),
        observations,
    )
    .unwrap();
    let first = bridge
        .route_media_interrupt(input.connection_id, &input.source.stream, 5)
        .await
        .unwrap();
    assert_eq!(first.scope.output_epoch, 5);
    let echo = bridge
        .route_media_interrupt(input.connection_id, &input.source.stream, 5)
        .await
        .unwrap();
    assert_eq!(echo.scope, first.scope);
    let before = media.calls.lock().unwrap().clone();
    assert_eq!(
        bridge
            .route_media_interrupt(input.connection_id + 1, &input.source.stream, 6)
            .await
            .unwrap_err(),
        HmiError::Identity
    );
    assert_eq!(
        bridge
            .route_media_interrupt(input.connection_id, &input.source.stream, 4)
            .await
            .unwrap_err(),
        HmiError::Fenced
    );
    assert_eq!(*media.calls.lock().unwrap(), before);
    connection.events.shutdown().await.unwrap();
    peer.await.unwrap();
}

#[tokio::test]
async fn concrete_jsonl_owner_closes_the_sourced_text_speech_and_interrupt_protocol_loop() {
    use tokio::io::AsyncBufReadExt;
    use tokio::io::AsyncWriteExt;
    let (listener, url) = listener().await;
    let peer = tokio::spawn(async move {
        let mut socket = accept_async(listener.accept().await.unwrap().0)
            .await
            .unwrap();
        initialize(&mut socket).await;
        let request = read(&mut socket).await;
        assert_eq!(request["method"], "thread/queue/reconcile");
        assert_eq!(request["params"]["threadId"], "thread:test");
        reply(&mut socket, &request, admission(&request, false)).await;
        started(&mut socket, &request).await;
        delta(&mut socket, "thread:test", "回答").await;
        completed(&mut socket, "completed").await;
        for _ in 0..2 {
            let interrupt = read(&mut socket).await;
            assert_eq!(interrupt["method"], "turn/interrupt");
            reply(&mut socket, &interrupt, json!({})).await;
        }
        let _ = socket.next().await;
    });
    let mut connection = HmiConnectionV1::connect(
        args(&url),
        binding(),
        /*event_capacity*/ 16,
        Duration::from_secs(3),
    )
    .await
    .unwrap();
    let (authority, file_owner, observations, input) = ports(connection.requests.connection_id());
    let (owner, native) = tokio::io::duplex(65536);
    let (read, write) = tokio::io::split(owner);
    let (link, mut events) =
        HmiJsonlMediaV1::bind(input.connection_id, 1, read, write, Duration::from_secs(2)).unwrap();
    let (tx, mut rx) = tokio::sync::mpsc::channel(8);
    // This reader is an owned task, concurrently resolving bounded ack futures.
    // Both it and the peer are joined below; the bridge creates no detached work.
    let pump = tokio::spawn(async move {
        loop {
            let event = events.next().await;
            let done = matches!(&event, Ok(HmiOwnedMediaEventV1::Terminal { .. }) | Err(_));
            tx.try_send(event).unwrap();
            if done {
                break;
            }
        }
    });
    let source = input.source.clone();
    let file = file_owner.file.clone();
    let native = tokio::spawn(async move {
        let (read, mut write) = tokio::io::split(native);
        let mut reader = tokio::io::BufReader::new(read);
        write
            .write_all(
                format!(
                    "{}\n",
                    json!({"type":"source_transcript","source":source,
            "transcript":{"text":"你好","finalized":true,"result":{"audio_source":source}}})
                )
                .as_bytes(),
            )
            .await
            .unwrap();
        let mut last_scope = serde_json::Value::Null;
        let mut retirements = 0;
        for operation in [
            "verify_source",
            "turn",
            "speak",
            "retire",
            "retire",
            "revoke_capture",
        ] {
            let mut line = String::new();
            reader.read_line(&mut line).await.unwrap();
            let command: serde_json::Value = serde_json::from_str(&line).unwrap();
            assert_eq!(command["type"], operation);
            if operation == "verify_source" {
                assert_eq!(
                    command["source"]["sha256"],
                    Digest32::of_bytes(&std::fs::read(&file).unwrap()).to_string()
                );
            }
            if operation == "speak" {
                assert_eq!(command["text"], "回答");
                last_scope = command["scope"].clone();
            }
            if operation == "retire" {
                retirements += 1;
                assert_eq!(
                    command["output_epoch"],
                    last_scope["outputEpoch"].as_u64().unwrap() + retirements
                );
            }
            let ack = if operation == "revoke_capture" {
                json!({"type":"media_terminal","request_id":command["request_id"],"stream":source.stream,
                    "output_epoch":last_scope["outputEpoch"].as_u64().unwrap()+2,"error":null,"local_stop_error":null,
                    "input_error":null,"input_errors":0,"cleanup_error":null,"verification_error":null})
            } else {
                json!({"type":"media_ack","request_id":command["request_id"],"operation":operation,"state":"queued","error":null})
            };
            write
                .write_all(format!("{ack}\n").as_bytes())
                .await
                .unwrap();
            if operation == "speak" {
                write.write_all(format!("{}\n",json!({"type":"presentation","identity":{"stream":source.stream,
                    "turn_id":last_scope["turnId"],"utterance_id":last_scope["utteranceId"],"sequence":last_scope["utteranceSequence"],
                    "output_epoch":last_scope["outputEpoch"]},"state":"submitted","error":null})).as_bytes()).await.unwrap();
                write.write_all(format!("{}\n",json!({"type":"turn_interrupt","stream":source.stream,
                    "request":{"output_epoch":last_scope["outputEpoch"].as_u64().unwrap()+1},"local_error":null})).as_bytes()).await.unwrap();
            }
        }
    });
    let bridge = HmiOwnerBridgeV1::attach(
        connection.requests.clone(),
        authority,
        link,
        observations.clone(),
    )
    .unwrap();
    let input = bridge
        .route_media_event(rx.recv().await.unwrap().unwrap())
        .await;
    assert!(input.input.as_ref().unwrap().admission.is_some());
    loop {
        let event = connection.events.next().await.unwrap().unwrap();
        let done = matches!(event.kind, HmiEventKindV1::Terminal { .. });
        let output = bridge.route_output(event).await;
        assert!(output.error.is_none(), "{output:?}");
        if done {
            break;
        }
    }
    let presentation = bridge
        .route_media_event(rx.recv().await.unwrap().unwrap())
        .await;
    assert!(
        matches!(presentation.event,HmiOwnedMediaEventV1::Presentation { observation } if observation.state == HmiMediaPresentationV1::Submitted)
    );
    let interrupted = bridge
        .route_media_event(rx.recv().await.unwrap().unwrap())
        .await;
    assert!(interrupted.error.is_none() && interrupted.interruption.is_some());
    let closed = bridge.revoke().await;
    assert!(closed.capture_stop_error.is_none() && closed.remote_interrupt_error.is_none());
    assert_eq!(observations.records.lock().unwrap().len(), 1);
    assert!(matches!(
        rx.recv().await.unwrap().unwrap(),
        HmiOwnedMediaEventV1::Terminal { .. }
    ));
    connection.events.shutdown().await.unwrap();
    peer.await.unwrap();
    native.await.unwrap();
    pump.await.unwrap();
}

#[tokio::test]
async fn late_device_failure_keeps_the_original_scope_and_retires_current_output() {
    let (listener, url) = listener().await;
    let peer = tokio::spawn(async move {
        let mut socket = accept_async(listener.accept().await.unwrap().0)
            .await
            .unwrap();
        initialize(&mut socket).await;
        let request = read(&mut socket).await;
        reply(&mut socket, &request, admission(&request, false)).await;
        started(&mut socket, &request).await;
        let interrupt = read(&mut socket).await;
        assert_eq!(interrupt["method"], "turn/interrupt");
        reply(&mut socket, &interrupt, json!({})).await;
        let _ = socket.next().await;
    });
    let mut connection = HmiConnectionV1::connect(
        args(&url),
        binding(),
        /*event_capacity*/ 8,
        Duration::from_secs(3),
    )
    .await
    .unwrap();
    let (authority, media, observations, _) = ports(connection.requests.connection_id());
    connection
        .requests
        .submit_text(
            /*current_generation*/ 7,
            /*sequence*/ 1,
            "device-failure",
            "用户输入",
            ThreadQueueReconcileMode::AllowIfAbsent,
        )
        .await
        .unwrap();
    let started = connection.events.next().await.unwrap().unwrap();
    let bridge =
        HmiOwnerBridgeV1::attach(connection.requests.clone(), authority, media, observations)
            .unwrap();
    let observed = HmiMediaPresentationEventV1 {
        scope: started.scope.clone(),
        state: HmiMediaPresentationV1::Unknown,
        error: Some("device callback lost".into()),
    };
    let outcome = bridge
        .route_media_event(HmiOwnedMediaEventV1::Presentation {
            observation: observed,
        })
        .await;
    assert_eq!(outcome.error, Some("device callback lost".into()));
    assert!(outcome.interruption.is_some());
    assert!(!connection.requests.permits_output(&started.scope).unwrap());
    assert!(
        matches!(outcome.event,HmiOwnedMediaEventV1::Presentation { observation } if observation.scope == started.scope && observation.state == HmiMediaPresentationV1::Unknown)
    );
    connection.events.shutdown().await.unwrap();
    peer.await.unwrap();
}
