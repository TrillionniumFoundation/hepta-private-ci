//! Local stdio composition. No network listener, login or credential issuance.
use codex_hepta_contracts::AgentId;
use codex_hepta_matrixd::MatrixAgentdConnectArgs;
use codex_hepta_matrixd::chat::AgentChatSession;
use codex_hepta_matrixd::chat::wire::ChatRequest;
use codex_hepta_matrixd::chat::wire::MAX_CHAT_FRAME_BYTES;
use codex_utils_absolute_path::AbsolutePathBuf;
use std::io::BufRead;
use std::io::Read;
use std::io::Write;

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let args: Vec<String> = std::env::args().skip(1).collect();
    if args.len() != 6 {
        return Err("expected SOCKET AGENT GENERATION PROJECT WORKSPACE SESSION".into());
    }
    let generation = args[2].parse()?;
    let owner = AgentChatSession::connect(
        MatrixAgentdConnectArgs::new(
            args[0].clone().into(),
            AgentId::parse(args[1].clone())?,
            generation,
            env!("CARGO_PKG_VERSION"),
        ),
        args[3].clone(),
        AbsolutePathBuf::from_absolute_path(&args[4])?,
        args[5].clone(),
        generation,
    )
    .await?;
    let mut input = std::io::stdin().lock();
    let mut output = std::io::stdout().lock();
    loop {
        let mut bytes = Vec::new();
        let read = input
            .by_ref()
            .take(MAX_CHAT_FRAME_BYTES as u64 + 1)
            .read_until(b'\n', &mut bytes)?;
        if read == 0 {
            break;
        }
        if bytes.len() > MAX_CHAT_FRAME_BYTES || bytes.last() != Some(&b'\n') {
            return Err("invalid chat frame".into());
        }
        let result = match serde_json::from_slice::<ChatRequest>(&bytes) {
            Ok(request) => match owner.dispatch(request).await {
                Ok(response) => serde_json::json!({"response": response}),
                Err(_) => {
                    serde_json::json!({"error": "chat_request_failed", "reconcileMutation": true})
                }
            },
            Err(_) => {
                serde_json::json!({"error": "invalid_chat_request", "reconcileMutation": false})
            }
        };
        serde_json::to_writer(&mut output, &result)?;
        output.write_all(b"\n")?;
        output.flush()?;
    }
    Ok(())
}
