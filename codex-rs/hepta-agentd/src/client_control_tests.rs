//! Protocol-only peers cannot create task receipts or make malformed replies
//! eligible for original-owner recovery.

use std::path::PathBuf;

use codex_hepta_contracts::AgentId;
use codex_uds::UnixListener;

use super::*;

async fn observe_reply(bytes: Vec<u8>) -> anyhow::Result<Result<AgentdResponse, ControlCallError>> {
    let temp_root = if cfg!(target_os = "macos") {
        PathBuf::from("/tmp")
    } else {
        std::env::temp_dir()
    };
    let temp = tempfile::Builder::new()
        .prefix("hctrl-")
        .tempdir_in(temp_root)?;
    let socket = temp.path().join("reply.ctl");
    let mut listener = UnixListener::bind(&socket).await?;
    let server = tokio::spawn(async move {
        let stream = listener.accept().await.expect("fixture peer accept");
        let (reader, mut writer) = tokio::io::split(stream);
        let mut reader = BufReader::new(reader);
        let mut request = Vec::new();
        reader
            .read_until(b'\n', &mut request)
            .await
            .expect("original request frame");
        if !bytes.is_empty() {
            let _closed_peer = writer.write_all(&bytes).await;
        }
    });
    let client = AgentdClient::new(
        socket,
        AgentId::parse("00000000-0000-4000-8000-000000000001")?,
        /*spawn_generation*/ 1,
    )?;
    let observed = client
        .send_once(AgentdRequest::capabilities(
            /*request_id*/ 1, /*spawn_generation*/ 1,
        ))
        .await;
    server.await?;
    Ok(observed)
}

#[tokio::test]
async fn original_objective_reply_marks_only_missing_postwrite_ack_uncertain() -> anyhow::Result<()>
{
    assert!(matches!(
        observe_reply(Vec::new()).await?,
        Err(ControlCallError::AcknowledgementLost(_))
    ));
    Ok(())
}

#[tokio::test]
async fn original_objective_reply_rejects_malformed_overload_and_wrong_identity()
-> anyhow::Result<()> {
    let wrong_identity = AgentdResponse {
        schema_version: AGENTD_CONTROL_SCHEMA_VERSION,
        request_id: 1,
        agent_id: AgentId::parse("00000000-0000-4000-8000-000000000002")?,
        spawn_generation: 1,
        current_generation: 1,
        payload: AgentdPayload::Error {
            code: "fixture".into(),
            message: "fixture".into(),
        },
    };
    let mut wrong_identity = serde_json::to_vec(&wrong_identity)?;
    wrong_identity.push(b'\n');
    for reply in [
        b"{".to_vec(),
        b"{}\n".to_vec(),
        vec![b'x'; MAX_CONTROL_FRAME_BYTES as usize + 1],
        AGENTD_CONTROL_OVERLOAD_FRAME.to_vec(),
        wrong_identity,
    ] {
        assert!(matches!(
            observe_reply(reply).await?,
            Err(ControlCallError::Rejected(_))
        ));
    }
    Ok(())
}

#[tokio::test]
async fn original_control_expired_end_refuses_before_connect() -> anyhow::Result<()> {
    let temp = tempfile::tempdir()?;
    let client = AgentdClient::new(
        temp.path().join("absent.ctl"),
        AgentId::parse("00000000-0000-4000-8000-000000000001")?,
        /*spawn_generation*/ 1,
    )?;
    let result = client
        .send_once_with_original_end(
            AgentdRequest::capabilities(/*request_id*/ 1, /*spawn_generation*/ 1),
            Some(Instant::now()),
        )
        .await;
    assert!(
        matches!(result, Err(ControlCallError::Rejected(AgentdError::Protocol(message)))
        if message == "original agentd control end elapsed")
    );
    Ok(())
}

#[tokio::test]
async fn original_control_postwrite_deadline_keeps_uncertainty_without_resending()
-> anyhow::Result<()> {
    let temp_root = if cfg!(target_os = "macos") {
        PathBuf::from("/tmp")
    } else {
        std::env::temp_dir()
    };
    let temp = tempfile::Builder::new()
        .prefix("hctrl-")
        .tempdir_in(temp_root)?;
    let socket = temp.path().join("deadline.ctl");
    let mut listener = UnixListener::bind(&socket).await?;
    let (sent, received) = tokio::sync::oneshot::channel();
    let (release, released) = tokio::sync::oneshot::channel();
    let server = tokio::spawn(async move {
        let stream = listener.accept().await?;
        let mut reader = BufReader::new(stream);
        let mut bytes = Vec::new();
        reader.read_until(b'\n', &mut bytes).await?;
        let request: AgentdRequest = serde_json::from_slice(&bytes)?;
        assert_eq!(request.request_id, 1);
        sent.send(())
            .map_err(|_| anyhow::anyhow!("request observation lost"))?;
        released.await?;
        bytes.clear();
        // The original caller closes after its deadline; it never sends a
        // second frame or treats the missing acknowledgement as completion.
        assert_eq!(reader.read_until(b'\n', &mut bytes).await?, 0);
        Ok::<_, anyhow::Error>(())
    });
    let client = AgentdClient::new(
        socket,
        AgentId::parse("00000000-0000-4000-8000-000000000001")?,
        /*spawn_generation*/ 1,
    )?;
    let end = Instant::now() + std::time::Duration::from_millis(500);
    let reply = client.send_once_with_original_end(
        AgentdRequest::capabilities(/*request_id*/ 1, /*spawn_generation*/ 1),
        Some(end),
    );
    let combined = tokio::time::timeout(std::time::Duration::from_secs(2), async {
        tokio::join!(received, reply)
    })
    .await;
    let Ok((observed, result)) = combined else {
        server.abort();
        let _cancelled = server.await;
        anyhow::bail!("original deadline fixture did not terminate");
    };
    observed?;
    assert!(Instant::now() >= end);
    assert!(matches!(
        result,
        Err(ControlCallError::AcknowledgementLost(_))
    ));
    release
        .send(())
        .map_err(|_| anyhow::anyhow!("peer release lost"))?;
    server.await??;
    Ok(())
}
