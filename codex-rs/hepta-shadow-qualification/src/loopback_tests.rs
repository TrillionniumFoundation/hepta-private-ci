use tokio::io::AsyncReadExt;
use tokio::io::AsyncWriteExt;
use tokio::net::TcpStream;

use super::driver::QualificationDriverRun;
use super::loopback::LoopbackHandle;
use crate::QualificationError;
use crate::Surface;

#[tokio::test]
async fn persists_exact_http_requests_and_responses() -> Result<(), QualificationError> {
    let temp = tempfile::tempdir()?;
    let cwd = temp.path().join("work");
    std::fs::create_dir(&cwd)?;
    let run = QualificationDriverRun::create(temp.path().join("observer"), &cwd)?;
    let loopback = LoopbackHandle::start(
        Surface::AppServer,
        run.run_root(),
        std::time::Duration::from_secs(5),
    )
    .await?;
    for sample in 1..=2 {
        send(loopback.address(), first_body(sample)).await?;
        send(loopback.address(), second_body(sample)).await?;
    }
    let records = loopback.finish().await?;
    assert_eq!(records.len(), 4);
    assert_eq!(records[0].sample_ordinal(), 1);
    assert_eq!(records[3].post_ordinal(), 2);
    assert_eq!(records[3].surface(), Surface::AppServer);
    assert!(records[3].validated_output_sha256().is_some());
    assert_eq!(std::fs::read_dir(run.run_root().join("http"))?.count(), 16);
    Ok(())
}

fn first_body(sample: u8) -> Vec<u8> {
    serde_json::to_vec(&serde_json::json!({
        "input": prior_outputs(sample),
        "model": "hepta-shadow-qualification",
        "stream": true,
        "tools": [{"name": "shell_command", "type": "function"}],
    }))
    .unwrap_or_default()
}

fn second_body(sample: u8) -> Vec<u8> {
    let mut input = prior_outputs(sample);
    input.push(output(sample));
    serde_json::to_vec(&serde_json::json!({
        "input": input,
        "model": "hepta-shadow-qualification",
        "stream": true,
        "tools": [{"name": "shell_command", "type": "function"}],
    }))
    .unwrap_or_default()
}

fn prior_outputs(sample: u8) -> Vec<serde_json::Value> {
    (1..sample).map(output).collect()
}

fn output(sample: u8) -> serde_json::Value {
    serde_json::json!({
        "call_id": format!("app_server-{sample}-call-v1"),
        "output": "Exit code: 0\nWall time: 0.01 seconds\nOutput:\nhepta-shadow-probe",
        "type": "function_call_output",
    })
}

async fn send(address: std::net::SocketAddr, body: Vec<u8>) -> Result<(), QualificationError> {
    let mut stream = TcpStream::connect(address).await?;
    let header = format!(
        "POST /v1/responses HTTP/1.1\r\nHost: {address}\r\nContent-Type: application/json\r\nContent-Length: {}\r\n\r\n",
        body.len()
    );
    stream.write_all(header.as_bytes()).await?;
    stream.write_all(&body).await?;
    stream.flush().await?;
    let mut response = Vec::new();
    stream.read_to_end(&mut response).await?;
    assert!(response.starts_with(b"HTTP/1.1 200 OK\r\n"));
    Ok(())
}
