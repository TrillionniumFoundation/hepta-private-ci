//! Complete original row integrity and response bounds, not exporter custody.
use super::*;
use tokio::io::AsyncBufReadExt;
use tokio::io::AsyncWriteExt;
use tokio::io::BufReader;

#[tokio::test]
async fn whole_completed_client_preserves_actual_bytes_and_denies_partial_changed_or_oversized_packets()
 {
    let (fixture, expected, _) = large_original_row();
    let whole = expected.to_bytes().expect("original full packet");
    for fault in 0..7 {
        let path = fixture
            ._runtime_root
            .path()
            .join(format!("packet-{fault}.sock"));
        let mut listener = codex_uds::UnixListener::bind(&path)
            .await
            .expect("test socket");
        let agent = fixture.state.identity().agent_id.clone();
        let client = crate::AgentdClient::new(path, agent.clone(), 7)
            .expect("client")
            .with_peer_process(unsafe { libc::geteuid() }, std::process::id())
            .expect("actual transport peer");
        let proposal_id = expected.proposal.proposal_id.clone();
        let mut packet = whole.clone();
        match fault {
            1 => packet.truncate(packet.len() / 2),
            2 => packet[20] ^= 1,
            3 => {
                packet = vec![
                    0;
                    codex_hepta_agent_components::plasticity::MAX_COMPLETED_PROPOSAL_BYTES_V1
                        + 1
                ]
            }
            _ => {}
        }
        let serving = tokio::spawn(async move {
            let stream = listener.accept().await.expect("connection");
            let (reader, mut writer) = tokio::io::split(stream);
            let mut frame = Vec::new();
            BufReader::new(reader)
                .read_until(b'\n', &mut frame)
                .await
                .expect("request");
            let request: crate::AgentdRequest =
                serde_json::from_slice(&frame).expect("original request codec");
            assert!(
                matches!(&request.method, crate::AgentdMethod::PlasticityCompletedProposal { proposal_id: actual } if actual == proposal_id.as_str())
            );
            let payload = crate::AgentdPayload::PlasticityCompletedProposal {
                proposal_id: if fault == 4 {
                    "foreign.proposal".into()
                } else {
                    proposal_id.to_string()
                },
                observation_hex: Some(crate::client::encode_hex(&packet)),
            };
            let response = crate::AgentdResponse {
                schema_version: crate::AGENTD_CONTROL_SCHEMA_VERSION,
                request_id: request.request_id,
                agent_id: agent,
                spawn_generation: 7,
                current_generation: 8,
                payload,
            };
            let mut frame = serde_json::to_vec(&response).expect("original response codec");
            if fault == 6 {
                frame.resize(
                    crate::canary_operation_receipt::MAX_COMPLETED_PROPOSAL_RESPONSE_BYTES_V1
                        as usize
                        + 1,
                    b' ',
                );
            }
            if fault != 5 {
                frame.push(b'\n');
            }
            // A bounded reader may close the oversized producer stream early.
            let write = writer.write_all(&frame).await;
            if fault != 6 {
                write.expect("whole test producer writes its actual frame");
            }
            let _ = writer.shutdown().await;
        });
        let result = client
            .plasticity_completed_proposal(expected.proposal.proposal_id.clone())
            .await;
        serving.await.expect("actual response producer retired");
        if fault == 0 {
            assert_eq!(
                result.expect("whole original decode"),
                (8, Some(expected.clone()))
            );
        } else {
            assert!(
                result.is_err(),
                "fault {fault} must not yield any partial receipt"
            );
        }
    }
    // The separate actual server test authenticates the original kernel Root
    // gate. A raw transport peer does not establish completed-proposal custody.
}
