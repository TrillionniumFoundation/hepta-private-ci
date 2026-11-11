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
