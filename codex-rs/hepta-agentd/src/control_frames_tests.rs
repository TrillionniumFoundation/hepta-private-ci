use tokio::io::AsyncWriteExt;

use super::*;

#[tokio::test]
async fn original_control_frame_rejects_partial_input_with_unchanged_io_budget() {
    let (mut peer, reader) = tokio::io::duplex(/*max_buf_size*/ 16);
    peer.write_all(b"{").await.expect("partial transport frame");
    let error = read_frame(reader)
        .await
        .expect_err("partial frame cannot admit a request");
    assert!(matches!(
        error,
        AgentdError::Protocol(message) if message == "agentd control request frame timed out"
    ));
}

#[tokio::test]
async fn original_control_frame_rejects_oversize_input_before_admission() {
    let (mut peer, reader) = tokio::io::duplex(/*max_buf_size*/ 256);
    let sender = tokio::spawn(async move {
        peer.write_all(&vec![b'x'; MAX_CONTROL_FRAME_BYTES as usize + 1])
            .await
    });
    let error = read_frame(reader)
        .await
        .expect_err("oversize frame cannot admit a request");
    assert!(matches!(
        error,
        AgentdError::Protocol(message)
            if message == "agentd control request must be one bounded newline JSON frame"
    ));
    let _closed_peer = sender.await.expect("bounded oversized frame sender");
}

#[tokio::test]
async fn original_control_frame_bounds_a_nonreading_response_peer() {
    let (mut writer, _nonreading_peer) = tokio::io::duplex(/*max_buf_size*/ 1);
    let error = write_frame(&mut writer, b"response\n")
        .await
        .expect_err("slow reader must not hold the connection indefinitely");
    assert!(matches!(
        error,
        AgentdError::Protocol(message) if message == "agentd control response frame timed out"
    ));
}
