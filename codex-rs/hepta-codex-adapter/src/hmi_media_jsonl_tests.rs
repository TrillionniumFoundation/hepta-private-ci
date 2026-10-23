//! Byte-stream fixtures exercise real codecs and ack futures; no audio device.
use super::*;
use crate::hmi::tests::binding;
use tokio::io::duplex;
use tokio::io::split;

fn source() -> HmiCapturedAudioRefV1 {
    let b = binding();
    HmiCapturedAudioRefV1 {
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
    }
}
fn scope() -> HmiOutputScopeV1 {
    let b = binding();
    HmiOutputScopeV1 {
        principal_id: b.principal_id,
        device_id: b.device_id,
        device_generation: b.device_generation,
        organ_id: b.organ_id,
        organ_generation: b.organ_generation,
        logical_session_id: b.logical_session_id,
        utterance_sequence: 1,
        utterance_id: Some("utterance:test".into()),
        connection_id: 9,
        output_epoch: 2,
        turn_id: Some("turn:test".into()),
    }
}
async fn frame<W: AsyncWrite + Unpin>(writer: &mut W, value: Value) {
    writer
        .write_all(format!("{value}\n").as_bytes())
        .await
        .unwrap();
}

#[tokio::test]
async fn source_roundtrip_verifies_before_admission_and_stamps_owned_reader_connection() {
    let (owner, native) = duplex(65536);
    let (read, write) = split(owner);
    let (link, mut events) =
        HmiJsonlMediaV1::bind(9, 1, read, write, Duration::from_secs(2)).unwrap();
    let source = source();
    let expected = source.clone();
    let peer = tokio::spawn(async move {
        let (read, mut write) = split(native);
        let mut reader = BufReader::new(read);
        let mut line = String::new();
        reader.read_line(&mut line).await.unwrap();
        let command: Value = serde_json::from_str(&line).unwrap();
        assert_eq!(command["type"], "verify_source");
        assert_eq!(command["source"], serde_json::to_value(&source).unwrap());
        frame(&mut write,json!({"type":"media_ack","request_id":command["request_id"],"operation":"verify_source","error":null})).await;
        frame(&mut write,json!({"type":"source_transcript","source":source,"transcript":{"text":"你好","finalized":true,"result":{"audio_source":source}}})).await;
    });
    let (verified, event) = tokio::join!(link.verify_source(&expected), events.next());
    verified.unwrap();
    let HmiOwnedMediaEventV1::FinalTranscript { input } = event.unwrap() else {
        panic!("expected sourced transcript");
    };
    assert_eq!(
        serde_json::to_value(input).unwrap(),
        json!({"connectionId":9,"source":expected,"text":"你好","finalized":true})
    );
    peer.await.unwrap();
}

#[tokio::test]
async fn speech_queue_ack_is_distinct_from_device_buffer_submission() {
    let (owner, native) = duplex(65536);
    let (read, write) = split(owner);
    let (link, mut events) =
        HmiJsonlMediaV1::bind(9, 1, read, write, Duration::from_secs(2)).unwrap();
    let expected = scope();
    let native_source = source();
    let peer = tokio::spawn(async move {
        let (read, mut write) = split(native);
        let mut reader = BufReader::new(read);
        let mut line = String::new();
        reader.read_line(&mut line).await.unwrap();
        let command: Value = serde_json::from_str(&line).unwrap();
        assert_eq!(command["type"], "speak");
        assert_eq!(command["text"], "你好");
        frame(&mut write,json!({"type":"media_ack","request_id":command["request_id"],"operation":"speak","state":"queued","error":null})).await;
        frame(&mut write,json!({"type":"presentation","identity":{"stream":native_source.stream,"turn_id":"turn:test","utterance_id":"utterance:test","sequence":1,"output_epoch":2},"state":"submitted","error":null})).await;
    });
    let (admitted, event) = tokio::join!(
        link.speak(HmiSpeechRequestV1::Speak {
            scope: expected.clone(),
            text: "你好".into()
        }),
        events.next()
    );
    assert_eq!(admitted.unwrap(), HmiMediaPresentationV1::Queued);
    let HmiOwnedMediaEventV1::Presentation { observation } = event.unwrap() else {
        panic!("expected presentation");
    };
    assert_eq!(observation.scope, expected);
    assert_eq!(observation.state, HmiMediaPresentationV1::Submitted);
    peer.await.unwrap();
}

#[tokio::test]
async fn reader_keeps_partial_bytes_across_cancellation_and_rejects_oversize() {
    let (owner, mut native) = duplex(131072);
    let (read, write) = split(owner);
    let (_link, mut events) =
        HmiJsonlMediaV1::bind(9, 1, read, write, Duration::from_secs(2)).unwrap();
    let event = json!({"type":"unbound_transcript","stream":source().stream,"transcript":{"text":"显示","finalized":false,"result":null}}).to_string();
    let middle = event.len() / 2;
    native.write_all(&event.as_bytes()[..middle]).await.unwrap();
    assert!(
        tokio::time::timeout(Duration::from_millis(10), events.next())
            .await
            .is_err()
    );
    native.write_all(&event.as_bytes()[middle..]).await.unwrap();
    native.write_all(b"\n").await.unwrap();
    assert!(
        matches!(events.next().await.unwrap(),HmiOwnedMediaEventV1::DisplayTranscript { text,.. } if text == "显示")
    );
    native.write_all(&vec![b'x'; 65537]).await.unwrap();
    assert_eq!(
        events.next().await.unwrap_err(),
        HmiError::Invalid("media event exceeds 64 KiB")
    );
}

#[tokio::test]
async fn wrong_ack_fences_waiters_instead_of_claiming_local_stop() {
    let (owner, native) = duplex(65536);
    let (read, write) = split(owner);
    let (link, mut events) =
        HmiJsonlMediaV1::bind(9, 1, read, write, Duration::from_secs(2)).unwrap();
    let peer = tokio::spawn(async move {
        let (read, mut write) = split(native);
        let mut reader = BufReader::new(read);
        let mut line = String::new();
        reader.read_line(&mut line).await.unwrap();
        let command: Value = serde_json::from_str(&line).unwrap();
        assert_eq!(command["output_epoch"], 7);
        frame(&mut write,json!({"type":"media_ack","request_id":command["request_id"],"operation":"speak","error":null})).await;
    });
    let (stopped, event) = tokio::join!(link.retire_output(7), events.next());
    assert_eq!(stopped.unwrap_err(), HmiError::Identity);
    assert_eq!(event.unwrap_err(), HmiError::Identity);
    assert_eq!(link.retire_output(7).await.unwrap_err(), HmiError::Fenced);
    peer.await.unwrap();
}

#[tokio::test]
async fn capture_terminal_waits_for_cleanup_and_preserves_all_failure_reasons() {
    let (owner, native) = duplex(65536);
    let (read, write) = split(owner);
    let (link, mut events) =
        HmiJsonlMediaV1::bind(9, 1, read, write, Duration::from_secs(2)).unwrap();
    let peer = tokio::spawn(async move {
        let (read, mut write) = split(native);
        let mut reader = BufReader::new(read);
        let mut line = String::new();
        reader.read_line(&mut line).await.unwrap();
        let command: Value = serde_json::from_str(&line).unwrap();
        assert_eq!(command["type"], "revoke_capture");
        frame(&mut write,json!({"type":"media_terminal","request_id":command["request_id"],"stream":source().stream,"output_epoch":7,
            "error":"recognizer crashed","local_stop_error":"device lost","input_error":"worker failed","input_errors":3,"cleanup_error":"join failed","verification_error":null})).await;
    });
    let (closed, event) = tokio::join!(link.revoke_capture(), events.next());
    let error = closed.unwrap_err().to_string();
    for reason in [
        "recognizer crashed",
        "device lost",
        "worker failed",
        "join failed",
    ] {
        assert!(error.contains(reason));
    }
    let HmiOwnedMediaEventV1::Terminal {
        connection_id,
        diagnostic,
    } = event.unwrap()
    else {
        panic!("expected terminal");
    };
    assert_eq!(connection_id, 9);
    assert_eq!(diagnostic["input_errors"], 3);
    peer.await.unwrap();
}

#[tokio::test]
async fn device_observed_playback_and_swapped_transcript_source_are_not_inferred() {
    for event in [
        json!({"type":"presentation","identity":{"stream":source().stream,"turn_id":"turn:test","utterance_id":"utterance:test","sequence":1,"output_epoch":2},"state":"deviceObservedPlayback","error":null}),
        json!({"type":"source_transcript","source":source(),"transcript":{"text":"你好","finalized":true,"result":{"audio_source":null}}}),
    ] {
        let (owner, mut native) = duplex(65536);
        let (read, write) = split(owner);
        let (_link, mut events) =
            HmiJsonlMediaV1::bind(9, 1, read, write, Duration::from_secs(2)).unwrap();
        frame(&mut native, event).await;
        assert!(events.next().await.is_err());
    }
}

#[tokio::test]
async fn release_requires_the_matching_observation_receipt_and_native_ack() {
    let (owner, native) = duplex(65536);
    let (read, write) = split(owner);
    let (link, mut events) =
        HmiJsonlMediaV1::bind(9, 1, read, write, Duration::from_secs(2)).unwrap();
    let input = HmiOwnerTranscriptV1 {
        connection_id: 9,
        source: source(),
        text: "你好".into(),
        finalized: true,
    };
    let mut receipt = HmiObservationReceiptV1 {
        observation_id: "fixture:retained".into(),
        payload_sha256: "0".repeat(64),
    };
    assert_eq!(
        link.release_source(&input, &receipt).await.unwrap_err(),
        HmiError::Identity
    );
    receipt.payload_sha256 = input.payload_sha256().unwrap();
    let peer = tokio::spawn(async move {
        let (read, mut write) = split(native);
        let mut reader = BufReader::new(read);
        let mut line = String::new();
        reader.read_line(&mut line).await.unwrap();
        let command: Value = serde_json::from_str(&line).unwrap();
        assert_eq!(command["type"], "release_source");
        assert_eq!(command["source"]["assetId"], "capture-1-1.pcm16");
        frame(&mut write,json!({"type":"media_ack","request_id":command["request_id"],"operation":"release_source","error":null})).await;
        frame(&mut write,json!({"type":"unbound_transcript","stream":source().stream,"transcript":{"text":"显示","finalized":false,"result":null}})).await;
    });
    let (released, event) = tokio::join!(link.release_source(&input, &receipt), events.next());
    released.unwrap();
    event.unwrap();
    peer.await.unwrap();
}

#[tokio::test]
async fn missing_stop_ack_has_a_deadline_and_fences_the_media_link() {
    let (owner, mut native) = duplex(65536);
    let (read, write) = split(owner);
    let (link, _events) =
        HmiJsonlMediaV1::bind(9, 1, read, write, Duration::from_millis(10)).unwrap();
    assert_eq!(link.retire_output(7).await.unwrap_err(), HmiError::Deadline);
    let mut bytes = Vec::new();
    use tokio::io::AsyncReadExt;
    native.read_to_end(&mut bytes).await.unwrap();
    assert_eq!(
        serde_json::from_slice::<Value>(&bytes).unwrap()["output_epoch"],
        7
    );
    assert_eq!(link.retire_output(8).await.unwrap_err(), HmiError::Fenced);
}

#[tokio::test]
async fn abandoning_a_partial_command_closes_its_writer_and_wakes_the_owned_reader() {
    use tokio::io::AsyncReadExt;
    let (owner, mut native) = duplex(8);
    let (read, write) = split(owner);
    let (link, mut events) =
        HmiJsonlMediaV1::bind(9, 1, read, write, Duration::from_secs(2)).unwrap();
    let sending = link.clone();
    let request = tokio::spawn(async move { sending.retire_output(7).await });
    let reader = tokio::spawn(async move { events.next().await });
    let mut prefix = [0; 8];
    native.read_exact(&mut prefix).await.unwrap();
    request.abort();
    let _ = request.await;
    assert_eq!(
        tokio::time::timeout(Duration::from_secs(1), reader)
            .await
            .unwrap()
            .unwrap()
            .unwrap_err(),
        HmiError::Fenced
    );
    let mut remaining = Vec::new();
    tokio::time::timeout(Duration::from_secs(1), native.read_to_end(&mut remaining))
        .await
        .unwrap()
        .unwrap();
    assert_ne!(remaining.last(), Some(&b'\n'));
    assert_eq!(link.retire_output(8).await.unwrap_err(), HmiError::Fenced);
}
